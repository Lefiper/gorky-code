"""Генерирует подписанный MAX initData для локальных curl-запросов.

Пример:
    python scripts/make_init_data.py --user-id 123

Токен берётся из --bot-token, переменной MAX_BOT_TOKEN или .env.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from urllib.parse import urlencode


def _token_from_env_file(path: Path | None = None) -> str | None:
    env_path = path or Path(".env")
    if not env_path.is_file():
        return None
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "MAX_BOT_TOKEN":
            return value.strip().strip('"').strip("'") or None
    return None


def resolve_bot_token(value: str | None = None) -> str:
    token = (
        value or os.environ.get("MAX_BOT_TOKEN") or _token_from_env_file() or ""
    ).strip()
    if not token:
        raise SystemExit(
            "Не найден MAX_BOT_TOKEN: передайте --bot-token, задайте переменную "
            "окружения или заполните MAX_BOT_TOKEN в .env."
        )
    return token


def build_init_data(bot_token: str, user_id: str, query_id: str = "local-cli") -> str:
    user = {
        "id": int(user_id) if user_id.isdigit() else user_id,
        "first_name": "Local",
        "last_name": "Developer",
        "username": "local_dev",
        "language_code": "ru",
        "photo_url": None,
    }
    data = {
        "auth_date": str(int(time.time())),
        "query_id": query_id,
        "user": json.dumps(user, separators=(",", ":"), ensure_ascii=False),
    }
    launch_params = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    data["hash"] = hmac.new(
        secret_key, launch_params.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return urlencode(data)


def main() -> int:
    parser = argparse.ArgumentParser(description="Сгенерировать MAX initData для локальной проверки.")
    parser.add_argument(
        "--bot-token",
        default=None,
        help="Токен бота. По умолчанию MAX_BOT_TOKEN из окружения или .env.",
    )
    parser.add_argument("--user-id", default="123", help="ID пользователя MAX (по умолчанию 123).")
    parser.add_argument("--query-id", default="local-cli", help="Произвольный query_id.")
    args = parser.parse_args()
    print(build_init_data(resolve_bot_token(args.bot_token), args.user_id, args.query_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
