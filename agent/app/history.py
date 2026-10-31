"""Контекст диалога в Redis/Valkey: последние сообщения и результаты Idempotency-Key."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from redis import Redis
from redis.exceptions import RedisError


class HistoryError(RuntimeError):
    """Redis недоступен. Ответ агента нельзя выдавать без сохранения контекста."""


class ChatHistory:
    def __init__(self, client: Redis, *, prefix: str, limit: int, ttl_seconds: int, idempotency_ttl_seconds: int):
        self.client = client
        self.prefix = prefix
        self.limit = limit
        self.ttl = ttl_seconds
        self.idempotency_ttl = idempotency_ttl_seconds

    def _digest(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _messages_key(self, user_id: str) -> str:
        return f"{self.prefix}:{{{self._digest(user_id)}}}:messages"

    def _reply_key(self, idempotency_key: str) -> str:
        return f"{self.prefix}:idem:{self._digest(idempotency_key)}"

    def get(self, user_id: str) -> list[dict]:
        try:
            raw = self.client.lrange(self._messages_key(user_id), 0, -1)
        except RedisError:
            raise HistoryError("Redis недоступен.") from None
        return [json.loads(item) for item in raw]

    def append(self, user_id: str, messages: list[tuple[str, str]]) -> None:
        key = self._messages_key(user_id)
        now = datetime.now(timezone.utc).isoformat()
        try:
            pipe = self.client.pipeline(transaction=True)
            for role, content in messages:
                pipe.rpush(key, json.dumps({"role": role, "content": content, "created_at": now}, ensure_ascii=False))
            pipe.ltrim(key, -self.limit, -1)
            pipe.expire(key, self.ttl)
            pipe.execute()
        except RedisError:
            raise HistoryError("Redis недоступен.") from None

    def get_reply(self, idempotency_key: str) -> str | None:
        try:
            value = self.client.get(self._reply_key(idempotency_key))
            if value and value.startswith('{"_reply_v":'):
                data = json.loads(value)
                from app.agent import Reply
                return Reply(data["reply"], data.get("confirmation_key"))
            return value
        except RedisError:
            raise HistoryError("Redis недоступен.") from None

    def put_reply(self, idempotency_key: str, reply: str) -> None:
        try:
            self.client.set(self._reply_key(idempotency_key), json.dumps({"_reply_v": 1, "reply": str(reply), "confirmation_key": getattr(reply, "confirmation_key", None)}, ensure_ascii=False), ex=self.idempotency_ttl)
        except RedisError:
            raise HistoryError("Redis недоступен.") from None

    def ping(self) -> bool:
        try:
            return bool(self.client.ping())
        except RedisError:
            return False
