"""Проверка MAX initData.

Алгоритм из https://dev.max.ru/docs/webapps/validation:
  secret_key = HMAC-SHA256(key="WebAppData", data=bot_token)
  hash       = hex(HMAC-SHA256(key=secret_key, data=launch_params))

launch_params — все поля кроме hash, отсортированные по ключу и склеенные
через "\n" в виде key=value. Значения предварительно URL-декодируются.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from urllib.parse import parse_qsl

from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as PydanticValidationError

from app.errors import AuthError

_HASH_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


class MaxUser(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None
    photo_url: str | None = None


def _parse_init_data(raw: str) -> dict[str, str]:
    if not raw or not raw.strip():
        raise AuthError("Не переданы данные авторизации MAX.")

    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        raise AuthError("Некорректный формат данных авторизации MAX.") from None

    data: dict[str, str] = {}
    for key, value in pairs:
        if key in data:
            raise AuthError("Данные авторизации MAX содержат повторяющиеся поля.")
        data[key] = value

    if "hash" not in data:
        raise AuthError("В данных авторизации MAX отсутствует подпись.")
    return data


def validate_init_data(
    raw: str,
    bot_token: str,
    ttl_seconds: int,
    now: float | None = None,
) -> MaxUser:
    if not bot_token.strip():
        raise AuthError("Не настроен токен бота для проверки MAX initData.")

    data = _parse_init_data(raw)
    provided_hash = data.pop("hash")

    if not _HASH_PATTERN.fullmatch(provided_hash):
        raise AuthError("Подпись данных авторизации MAX имеет неверный формат.")

    launch_params = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, launch_params.encode("utf-8"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_hash, provided_hash.lower()):
        raise AuthError("Подпись данных авторизации MAX не совпадает.")

    try:
        auth_date = int(data.get("auth_date", ""))
    except ValueError:
        raise AuthError("В данных авторизации MAX нет корректного auth_date.") from None

    current = time.time() if now is None else now
    if auth_date > current + 60:
        raise AuthError("Данные авторизации MAX выданы в будущем.")
    if current - auth_date > ttl_seconds:
        raise AuthError("Данные авторизации MAX устарели. Переоткройте мини-приложение.")

    try:
        user_payload = json.loads(data.get("user", ""))
    except (TypeError, ValueError):
        raise AuthError("В данных авторизации MAX нет корректного пользователя.") from None

    if not isinstance(user_payload, dict) or "id" not in user_payload:
        raise AuthError("В данных авторизации MAX нет пользователя.")

    user_id = user_payload.get("id")
    if isinstance(user_id, bool) or not isinstance(user_id, (int, str)) or not str(user_id).strip():
        raise AuthError("Некорректный идентификатор пользователя MAX.")

    try:
        return MaxUser(
            id=str(user_id).strip(),
            first_name=user_payload.get("first_name"),
            last_name=user_payload.get("last_name"),
            username=user_payload.get("username"),
            language_code=user_payload.get("language_code"),
            photo_url=user_payload.get("photo_url"),
        )
    except PydanticValidationError:
        raise AuthError("Некорректные данные пользователя MAX.") from None
