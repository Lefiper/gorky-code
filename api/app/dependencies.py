"""Зависимости FastAPI: настройки, репозиторий и текущий пользователь."""

from __future__ import annotations

from fastapi import Depends, Header, Request

from app.auth import MaxUser, validate_init_data
from app.config import Settings
from app.errors import AuthError
from app.storage import EventRepository


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_repository(request: Request) -> EventRepository:
    return request.app.state.repository


def get_current_user(
    settings: Settings = Depends(get_settings),
    x_max_init_data: str | None = Header(default=None, alias="X-Max-InitData"),
    x_debug_user_id: str | None = Header(default=None, alias="X-Debug-User-Id"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> MaxUser:
    if settings.auth_dev_mode:
        user_id = (x_debug_user_id or settings.dev_user_id).strip()
        if not user_id:
            raise AuthError("DEV_USER_ID не задан.")
        return MaxUser(id=user_id, first_name="Dev", last_name="User")

    init_data = x_max_init_data
    if not init_data and authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            init_data = value.strip()

    if not init_data:
        raise AuthError("Не переданы данные авторизации MAX.")

    return validate_init_data(
        init_data,
        settings.max_bot_token.get_secret_value(),
        settings.max_init_data_ttl_seconds,
    )
