"""Настройки подключения: окружение имеет приоритет перед файлом .env."""

import os
import re
from urllib.parse import urlsplit
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ConfigError(ValueError):
    """Ошибка настройки без вывода секретных значений."""


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    dbname: str
    user: str
    password: str = field(repr=False)
    connect_timeout: int = 5

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv(PROJECT_ROOT / ".env", override=False)
        required = ("PGHOST", "PGDATABASE", "PGUSER", "PGPASSWORD")
        missing = [key for key in required if not os.environ.get(key, "").strip()]
        if missing:
            raise ConfigError("Заполните в локальном .env: " + ", ".join(missing))
        try:
            port = int(os.environ.get("PGPORT", "5432"))
            timeout = int(os.environ.get("PGCONNECT_TIMEOUT", "5"))
        except ValueError:
            raise ConfigError("PGPORT и PGCONNECT_TIMEOUT должны быть целыми числами.") from None
        if not 1 <= port <= 65535 or not 1 <= timeout <= 60:
            raise ConfigError("PGPORT: 1–65535; PGCONNECT_TIMEOUT: 1–60 секунд.")
        dbname = os.environ["PGDATABASE"].strip()
        if dbname.lower() in {"postgres", "template0", "template1"}:
            raise ConfigError("Укажите отдельную проектную БД в PGDATABASE.")
        return cls(
            host=os.environ["PGHOST"].strip(),
            port=port,
            dbname=dbname,
            user=os.environ["PGUSER"].strip(),
            password=os.environ["PGPASSWORD"],
            connect_timeout=timeout,
        )


@dataclass(frozen=True)
class RedisSettings:
    url: str = field(default="redis://127.0.0.1:6379/0", repr=False)
    key_prefix: str = "assistant:dialogue"
    ttl_seconds: int = 900
    history_limit: int = 10

    def __post_init__(self):
        try:
            parsed = urlsplit(self.url)
            if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
                raise ValueError
            if parsed.port is not None and not 1 <= parsed.port <= 65535:
                raise ValueError
        except (ValueError, TypeError):
            raise ConfigError("REDIS_URL: нужен корректный redis:// или rediss:// URL.") from None
        if not isinstance(self.key_prefix, str) or not re.fullmatch(r"[a-zA-Z0-9:_-]{1,100}", self.key_prefix):
            raise ConfigError("REDIS_KEY_PREFIX: 1–100 латинских букв, цифр или символов :_-.")
        if type(self.ttl_seconds) is not int or not 1 <= self.ttl_seconds <= 900:
            raise ConfigError("REDIS_TTL_SECONDS: целое число от 1 до 900.")
        if type(self.history_limit) is not int or not 1 <= self.history_limit <= 10:
            raise ConfigError("REDIS_HISTORY_LIMIT: целое число от 1 до 10.")

    @classmethod
    def load(cls) -> "RedisSettings":
        load_dotenv(PROJECT_ROOT / ".env", override=False)
        try:
            ttl = int(os.environ.get("REDIS_TTL_SECONDS", "900"))
            limit = int(os.environ.get("REDIS_HISTORY_LIMIT", "10"))
        except ValueError:
            raise ConfigError("REDIS_TTL_SECONDS и REDIS_HISTORY_LIMIT должны быть целыми числами.") from None
        return cls(
            url=os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"),
            key_prefix=os.environ.get("REDIS_KEY_PREFIX", "assistant:dialogue"),
            ttl_seconds=ttl,
            history_limit=limit,
        )
