"""HTTP-контракт для MAX Bot: POST /chat, GET /health.

Запуск: uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8003
"""

from __future__ import annotations

import asyncio
import hmac
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from redis import Redis
from redis.exceptions import RedisError

from app.agent import CalendarAgent
from app.config import Settings
from app.history import ChatHistory, HistoryError
from app.llm import build_chat_model
from app.mcp_client import CalendarMCP

logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: str = Field(min_length=1, max_length=128)
    message_id: str = Field(min_length=1, max_length=200)
    conversation_id: str = Field(default="", max_length=200)
    text: str = Field(min_length=1, max_length=16000)
    timezone: str = Field(default="", max_length=64)
    source: Literal["text", "voice"] = "text"


class ChatResponse(BaseModel):
    reply: str
    confirmation_key: str | None = None


def create_app(settings: Settings | None = None, *, llm=None, mcp=None, history: ChatHistory | None = None, confirmations=None, profile_reader=None) -> FastAPI:
    settings = settings or Settings.from_env()
    if llm is None and settings.llm_configured:
        llm = build_chat_model(settings)
    mcp = mcp or CalendarMCP(settings.mcp_url)
    owned_redis: Redis | None = None
    if history is None:
        owned_redis = Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=5, socket_connect_timeout=5)
        history = ChatHistory(owned_redis, prefix=settings.redis_key_prefix, limit=settings.history_limit,
                              ttl_seconds=settings.history_ttl_seconds,
                              idempotency_ttl_seconds=settings.idempotency_ttl_seconds)
    from app.confirmation import Confirmations
    confirmations = confirmations or Confirmations()
    agent = CalendarAgent(llm=llm, mcp=mcp, history=history, settings=settings, confirmations=confirmations) if llm is not None else None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not settings.agent_api_key:
            logger.warning("AGENT_API_KEY не задан: /chat доступен без проверки Bearer-ключа.")
        if not settings.llm_configured:
            logger.warning("GIGACHAT_CREDENTIALS не задан: /chat вернёт 503 до настройки LLM.")
        yield
        if owned_redis is not None:
            owned_redis.close()

    app = FastAPI(title="Gorky Code — Agent Backend", version="0.2.0", lifespan=lifespan)

    @app.post("/chat", response_model=ChatResponse, response_model_exclude_none=True)
    async def chat(
        body: ChatRequest,
        authorization: str | None = Header(default=None),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> ChatResponse:
        if settings.agent_api_key and not hmac.compare_digest(
            authorization or "", "Bearer " + settings.agent_api_key
        ):
            raise HTTPException(status_code=401, detail="Неверный ключ агента.")
        if body.timezone:
            try:
                ZoneInfo(body.timezone)
            except (ZoneInfoNotFoundError, ValueError):
                raise HTTPException(status_code=422, detail="Unknown timezone") from None
        from shared.profiles import get_timezone
        try:
            zone_name = await asyncio.to_thread(profile_reader or get_timezone, body.user_id, settings.default_timezone)
        except Exception:
            raise HTTPException(status_code=503, detail="Профиль временно недоступен.") from None
        try:
            ZoneInfo(zone_name)
        except (ZoneInfoNotFoundError, ValueError):
            raise HTTPException(status_code=422, detail="Неизвестный часовой пояс.") from None
        key = body.user_id + ":" + (idempotency_key or body.message_id)
        lock = None
        if hasattr(history, "client"):
            lock = history.client.lock(history._messages_key(body.user_id) + ":lock", timeout=300, blocking_timeout=10,
                                       thread_local=False)
            try:
                acquired = await asyncio.to_thread(lock.acquire)
            except RedisError:
                raise HTTPException(status_code=503, detail="Контекст диалога временно недоступен.") from None
            if not acquired:
                raise HTTPException(status_code=409, detail="Предыдущий запрос ещё обрабатывается.")
        try:
            try:
                cached = await asyncio.to_thread(history.get_reply, key)
                if cached is not None:
                    return ChatResponse(reply=str(cached), confirmation_key=getattr(cached, "confirmation_key", None))
                if agent is None:
                    raise HTTPException(status_code=503, detail="LLM не настроен: задайте GIGACHAT_CREDENTIALS.")
                try:
                    reply = await asyncio.wait_for(agent.reply(user_id=body.user_id, message_id=key, text=body.text,
                                              timezone_name=zone_name, source=body.source), timeout=240)
                except HistoryError:
                    raise
                except Exception as exc:
                    # Ошибки GigaChat/сети не отдаём клиенту: могут содержать адреса и параметры.
                    logger.warning("agent_failed type=%s", type(exc).__name__)
                    raise HTTPException(status_code=503, detail="Агент временно недоступен. Повторите запрос позже.") from None
                await asyncio.to_thread(history.put_reply, key, reply)
            except HistoryError:
                raise HTTPException(status_code=503, detail="Контекст диалога временно недоступен.") from None
            return ChatResponse(reply=str(reply), confirmation_key=getattr(reply, "confirmation_key", None))
        finally:
            if lock is not None:
                try:
                    await asyncio.to_thread(lock.release)
                except RedisError:
                    logger.warning("dialogue_lock_release_failed")

    @app.get("/health")
    async def health():
        redis_ok = await asyncio.to_thread(history.ping)
        mcp_ok = False
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                mcp_ok = (await client.get(settings.mcp_health_url)).status_code == 200
        except httpx.HTTPError:
            mcp_ok = False
        payload = {"status": "ok" if redis_ok and mcp_ok else "unavailable", "redis": redis_ok,
                   "mcp": mcp_ok, "llm_configured": settings.llm_configured}
        if payload["status"] != "ok":
            raise HTTPException(status_code=503, detail=payload)
        return payload

    return app
