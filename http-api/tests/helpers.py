from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode
from uuid import uuid4

from app.config import Settings

BOT_TOKEN = "test-bot-token"
USER_ID = 123


def sign_init_data(data: dict[str, str], bot_token: str = BOT_TOKEN) -> str:
    """Подписывает произвольный набор полей так же, как MAX."""
    launch_params = "\n".join(
        f"{key}={value}" for key, value in sorted(data.items()) if key != "hash"
    )
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    payload = dict(data)
    payload["hash"] = hmac.new(
        secret_key, launch_params.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return urlencode(payload)


def make_init_data(
    bot_token: str = BOT_TOKEN,
    user_id: int = USER_ID,
    auth_date: int | None = None,
    hash_override: str | None = None,
    extra: dict[str, str] | None = None,
) -> str:
    data = {
        "auth_date": str(int(time.time()) if auth_date is None else auth_date),
        "query_id": "test-query-id",
        "user": json.dumps(
            {
                "id": user_id,
                "first_name": "Test",
                "last_name": "User",
                "username": "test_user",
                "language_code": "ru",
                "photo_url": None,
            },
            separators=(",", ":"),
            ensure_ascii=False,
        ),
    }
    if extra:
        data.update(extra)

    if hash_override is not None:
        data["hash"] = hash_override
        return urlencode(data)

    return sign_init_data(data, bot_token)


def make_settings(**overrides) -> Settings:
    values = {
        "app_env": "test",
        "api_prefix": "/api/v1",
        "cors_origins": "*",
        "default_timezone": "Europe/Moscow",
        "pg_host": "127.0.0.1",
        "pg_port": 55432,
        "pg_database": "assistant_mvp",
        "pg_user": "assistant_app",
        "pg_password": "test-password",
        "pg_connect_timeout": 5,
        "max_bot_token": BOT_TOKEN,
        "max_init_data_ttl_seconds": 3600,
        "auth_dev_mode": False,
        "dev_user_id": "dev:1",
    }
    values.update(overrides)
    return Settings(**values)


def event_payload(**overrides) -> dict:
    payload = {
        "id": str(uuid4()),
        "user_id": str(USER_ID),
        "event_type": "task",
        "name": "Тестовая задача",
        "description": "Описание",
        "event_at": "2026-10-24T09:00:00Z",
        "created_at": "2026-10-23T20:00:00Z",
        "status": "pending",
    }
    payload.update(overrides)
    return payload
