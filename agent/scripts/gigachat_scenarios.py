"""Сценарии на настоящем GigaChat. Нужны GIGACHAT_CREDENTIALS и MCP_URL (работающий MCP-сервер).

    python -m scripts.gigachat_scenarios

Сценарии идут по одному пользователю подряд, контекст хранится в Redis (REDIS_URL).
Ничего не выполняется без ключа: скрипт завершится с кодом 2 и понятным сообщением.
"""

import asyncio
import sys
import uuid

from redis import Redis

from app.agent import CalendarAgent
from app.config import ConfigError, Settings
from app.history import ChatHistory
from app.llm import build_chat_model
from app.mcp_client import CalendarMCP

SCENARIOS = [
    "создай встречу завтра в 15:00",
    "что у меня на этой неделе",
    "найди про врача",
    "запиши задачу",
    "привет, как дела?",
]


async def main() -> int:
    try:
        settings = Settings.from_env()
        if not settings.llm_configured:
            raise ConfigError("GIGACHAT_CREDENTIALS не задан.")
        llm = build_chat_model(settings)
    except ConfigError as exc:
        print(f"Нельзя запустить сценарии: {exc}", file=sys.stderr)
        return 2
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    history = ChatHistory(redis, prefix=settings.redis_key_prefix, limit=settings.history_limit,
                          ttl_seconds=settings.history_ttl_seconds,
                          idempotency_ttl_seconds=settings.idempotency_ttl_seconds)
    agent = CalendarAgent(llm=llm, mcp=CalendarMCP(settings.mcp_url), history=history, settings=settings)
    user = "scenario:" + uuid.uuid4().hex[:12]
    for number, text in enumerate(SCENARIOS, start=1):
        reply = await agent.reply(user_id=user, message_id=f"scenario:{number}", text=text,
                                  timezone_name=settings.default_timezone)
        print(f"> {text}\n< {reply}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
