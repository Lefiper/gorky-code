"""Точка сборки FastAPI-приложения.

Запуск:
    uvicorn app.main:create_app --factory --reload --port 8002
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import Settings
from app.errors import ApiError
from app.routers import events, health, me
from app.storage import EventRepository

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    repository: EventRepository | None = None,
) -> FastAPI:
    settings = settings or Settings()
    repo = repository or EventRepository(settings.pg_config())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        repo.open()
        try:
            yield
        finally:
            repo.close()

    app = FastAPI(
        title="Gorky Code — HTTP API",
        version="0.1.0",
        description=(
            "HTTP API календаря для MAX Mini App. "
            "Читает и создаёт события в общей таблице public.events."
        ),
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.repository = repo

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "X-Max-InitData",
            "X-Debug-User-Id",
            "Authorization",
            "Idempotency-Key",
        ],
    )

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        headers = {}
        if exc.status_code == 401:
            headers["WWW-Authenticate"] = "MaxInitData"
        return JSONResponse(
            {"detail": exc.detail},
            status_code=exc.status_code,
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            {
                "detail": "Некорректные параметры запроса.",
                "errors": jsonable_encoder(exc.errors()),
            },
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse({"detail": "Внутренняя ошибка сервиса."}, status_code=500)

    app.include_router(health.router)
    app.include_router(me.router, prefix=settings.api_prefix)
    app.include_router(events.router, prefix=settings.api_prefix)

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {
            "service": "gorky-code-http-api",
            "docs": "/docs",
            "health": "/health",
        }

    return app
