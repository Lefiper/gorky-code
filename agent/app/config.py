"""Настройки Agent Backend. Секреты только из переменных окружения."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ConfigError(ValueError):
    """Ошибка настройки без вывода секретных значений."""


def _int(env, name, default, low, high):
    raw = env.get(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        raise ConfigError(f"{name}: нужно целое число.") from None
    if not low <= value <= high:
        raise ConfigError(f"{name}: допустимо от {low} до {high}.")
    return value


def _bool(env, name, default):
    raw = env.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name}: используйте true или false.")


@dataclass(frozen=True)
class Settings:
    gigachat_credentials: str = field(default="", repr=False)
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_model: str = "GigaChat-2-Max"
    gigachat_verify_ssl: bool = True
    gigachat_ca_bundle_file: str = ""
    mcp_url: str = "http://127.0.0.1:8001/mcp"
    mcp_health_url: str = "http://127.0.0.1:8001/health"
    redis_url: str = field(default="redis://127.0.0.1:6379/0", repr=False)
    redis_key_prefix: str = "assistant:agent"
    agent_api_key: str = field(default="", repr=False)
    default_timezone: str = "Europe/Moscow"
    history_limit: int = 40
    history_ttl_seconds: int = 86400
    max_tool_rounds: int = 4
    idempotency_ttl_seconds: int = 3600

    @classmethod
    def from_env(cls, env=None) -> "Settings":
        env = os.environ if env is None else env
        timezone_name = env.get("DEFAULT_TIMEZONE", "Europe/Moscow").strip() or "Europe/Moscow"
        try:
            ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError):
            raise ConfigError("DEFAULT_TIMEZONE: неизвестный часовой пояс IANA.") from None
        prefix = env.get("REDIS_KEY_PREFIX", "assistant:agent").strip()
        if not re.fullmatch(r"[a-zA-Z0-9:_-]{1,100}", prefix):
            raise ConfigError("REDIS_KEY_PREFIX: 1–100 символов a-z, 0-9, :, _, -.")
        return cls(
            gigachat_credentials=env.get("GIGACHAT_CREDENTIALS", "").strip(),
            gigachat_scope=env.get("GIGACHAT_SCOPE", "GIGACHAT_API_PERS").strip() or "GIGACHAT_API_PERS",
            gigachat_model=env.get("GIGACHAT_MODEL", "GigaChat-2-Max").strip() or "GigaChat-2-Max",
            gigachat_verify_ssl=_bool(env, "GIGACHAT_VERIFY_SSL_CERTS", True),
            gigachat_ca_bundle_file=env.get("GIGACHAT_CA_BUNDLE_FILE", "").strip(),
            mcp_url=env.get("MCP_URL", "http://127.0.0.1:8001/mcp").strip(),
            mcp_health_url=env.get("MCP_HEALTH_URL", "http://127.0.0.1:8001/health").strip(),
            redis_url=env.get("REDIS_URL", "redis://127.0.0.1:6379/0").strip(),
            redis_key_prefix=prefix,
            agent_api_key=env.get("AGENT_API_KEY", "").strip(),
            default_timezone=timezone_name,
            history_limit=_int(env, "AGENT_HISTORY_LIMIT", 40, 1, 100),
            history_ttl_seconds=_int(env, "AGENT_HISTORY_TTL_SECONDS", 86400, 60, 604800),
            max_tool_rounds=_int(env, "AGENT_MAX_TOOL_ROUNDS", 4, 1, 8),
            idempotency_ttl_seconds=_int(env, "AGENT_IDEMPOTENCY_TTL_SECONDS", 3600, 60, 86400),
        )

    @property
    def llm_configured(self) -> bool:
        return bool(self.gigachat_credentials)
