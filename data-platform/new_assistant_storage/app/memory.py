"""Временная память backend агента. MCP-контракт остаётся из трёх инструментов."""

from datetime import datetime as DateTime, timezone
import hashlib
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator
from redis import Redis
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry

from app.config import ConfigError, RedisSettings

NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class MemoryValidationError(ValueError):
    """Ошибка параметров памяти без вывода содержимого диалога."""


class MemoryStorageError(RuntimeError):
    """Redis недоступен или контекст повреждён. Это не пустая история."""


class ASRResult(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    text: Annotated[NonEmpty, Field(max_length=10000)]
    engine: Annotated[NonEmpty, Field(max_length=100)]
    audio_sec: float = Field(ge=0, allow_inf_nan=False)
    latency_ms: float = Field(ge=0, allow_inf_nan=False)


class Message(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    role: Literal["user", "assistant"]
    content: Annotated[NonEmpty, Field(max_length=10000)]
    created_at: str
    asr: dict | None = None


class PendingEvent(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    event_type: Literal["task", "reminder", "meeting"]
    name: Annotated[NonEmpty, Field(max_length=200)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=10000)] = ""
    datetime: str
    idempotency_key: Annotated[NonEmpty, Field(max_length=200)] = Field(default_factory=lambda: str(uuid4()))

    @field_validator("datetime")
    @classmethod
    def aware_datetime(cls, value):
        try:
            if "T" not in value:
                raise ValueError
            parsed = DateTime.fromisoformat(value)
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError
            return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        except (ValueError, OverflowError):
            raise ValueError("Нужен ISO 8601 с часовым смещением.") from None


# Небольшие Lua-операции выполняются без вмешательства других запросов Redis.
# Это защищает ограничение длины и TTL при параллельных добавлениях сообщений.
APPEND = """
redis.call('RPUSH', KEYS[1], ARGV[1])
redis.call('LTRIM', KEYS[1], -tonumber(ARGV[2]), -1)
redis.call('EXPIRE', KEYS[1], ARGV[3])
redis.call('EXPIRE', KEYS[2], ARGV[3])
return 1
"""
SET_PENDING = """
redis.call('SET', KEYS[2], ARGV[1], 'EX', ARGV[2])
redis.call('EXPIRE', KEYS[1], ARGV[2])
return 1
"""
GET_CONTEXT = """
return {redis.call('LRANGE', KEYS[1], 0, -1), redis.call('GET', KEYS[2]) or false}
"""
CLEAR_PENDING = """
local value = redis.call('GET', KEYS[1])
if not value then return 0 end
if cjson.decode(value)['idempotency_key'] ~= ARGV[1] then return 0 end
return redis.call('DEL', KEYS[1])
"""


class ConversationStore:
    """Синхронный интерфейс для Python backend; в async-коде вызывайте через to_thread."""

    def __init__(self, settings: RedisSettings | None = None):
        self.settings = settings if settings is not None else RedisSettings.load()
        try:
            self.client = Redis.from_url(
                self.settings.url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
                retry=Retry(NoBackoff(), 0),
            )
        except (ValueError, TypeError):
            raise ConfigError("REDIS_URL: проверьте номер БД и параметры подключения.") from None

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _keys(self, user_id):
        if not isinstance(user_id, str) or not user_id.strip():
            raise MemoryValidationError("user_id: нужна непустая строка.")
        # Идентификатор не попадает в имя ключа. Общий hash tag пригоден для Redis Cluster.
        digest = hashlib.sha256(user_id.strip().encode("utf-8")).hexdigest()
        base = f"{self.settings.key_prefix}:{{{digest}}}"
        return base + ":history", base + ":pending"

    def _call(self, method, *args):
        try:
            return method(*args)
        except (RedisError, UnicodeError):
            raise MemoryStorageError("Память диалога Redis недоступна. Не подтверждайте событие без контекста.") from None

    def ping(self):
        return self._call(self.client.ping)

    def append_message(self, user_id: str, role: str, content: str):
        keys = self._keys(user_id)
        try:
            message = Message(role=role, content=content, created_at=DateTime.now(timezone.utc).isoformat())
        except ValidationError:
            raise MemoryValidationError("Сообщение: role должен быть user/assistant, content — непустой строкой до 10000 символов.") from None
        self._append(keys, message)

    def append_asr_message(self, user_id: str, payload: dict):
        keys = self._keys(user_id)
        try:
            asr = ASRResult.model_validate(payload)
        except ValidationError:
            raise MemoryValidationError("ASR: ожидаются text, engine, неотрицательные audio_sec и latency_ms.") from None
        message = Message(role="user", content=asr.text, created_at=DateTime.now(timezone.utc).isoformat(),
                          asr=asr.model_dump(exclude={"text"}))
        self._append(keys, message)

    def _append(self, keys, message):
        self._call(self.client.eval, APPEND, 2, *keys, message.model_dump_json(),
                   self.settings.history_limit, self.settings.ttl_seconds)

    def set_pending_event(self, user_id: str, event_type: str, name: str, datetime: str, description: str = "") -> dict:
        """Каждое новое предложение/исправление получает новый ключ операции."""
        keys = self._keys(user_id)
        try:
            pending = PendingEvent(event_type=event_type, name=name, datetime=datetime, description=description)
        except ValidationError:
            raise MemoryValidationError("Событие: проверьте тип, название, описание и ISO 8601 с часовым смещением.") from None
        self._call(self.client.eval, SET_PENDING, 2, *keys, pending.model_dump_json(), self.settings.ttl_seconds)
        return pending.model_dump()

    def get_context(self, user_id: str) -> dict:
        """Чтение само по себе не продлевает TTL: активность — запись сообщения/предложения."""
        keys = self._keys(user_id)
        messages, pending = self._call(self.client.eval, GET_CONTEXT, 2, *keys)
        try:
            return {
                "messages": [Message.model_validate_json(value).model_dump(exclude_none=True) for value in messages],
                "pending_event": PendingEvent.model_validate_json(pending).model_dump() if pending is not None else None,
            }
        except (ValidationError, ValueError, TypeError):
            raise MemoryStorageError("Контекст Redis повреждён. Попросите пользователя повторить детали.") from None

    def clear_pending_event(self, user_id: str, expected_idempotency_key: str) -> bool:
        """Убрать только подтверждённое/отменённое предложение, не затронув новое."""
        keys = self._keys(user_id)
        if not isinstance(expected_idempotency_key, str) or not expected_idempotency_key.strip():
            raise MemoryValidationError("Укажите ключ ожидаемого события.")
        return bool(self._call(self.client.eval, CLEAR_PENDING, 1, keys[1], expected_idempotency_key))


def main():
    # Проверка подключения не создаёт и не читает историю пользователя.
    from app.config import ConfigError
    try:
        with ConversationStore() as store:
            store.ping()
        print("Redis доступен. Память: до 10 сообщений, TTL по умолчанию 15 минут.")
        return 0
    except (ConfigError, MemoryStorageError) as exc:
        print(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
