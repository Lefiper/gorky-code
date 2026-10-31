"""Быстрая проверка запущенного API.

Запуск:
    python -m scripts.smoke_test --base-url http://127.0.0.1:8002

Токен берётся из --bot-token, переменной MAX_BOT_TOKEN или .env.
Создаёт тестовое событие с user_id test:smoke:<uuid>. Это проверочные данные,
они остаются в БД (как и в тестах data-platform).
"""

from __future__ import annotations

import argparse
import json
import sys
from uuid import uuid4

import httpx

from scripts.make_init_data import build_init_data, resolve_bot_token


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-тест HTTP API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8002")
    parser.add_argument(
        "--bot-token",
        default=None,
        help="Токен бота. По умолчанию MAX_BOT_TOKEN из окружения или .env.",
    )
    parser.add_argument("--user-id", default="test:smoke")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    user_id = f"{args.user_id}:{uuid4()}"
    init_data = build_init_data(resolve_bot_token(args.bot_token), user_id)
    headers = {"X-Max-InitData": init_data}

    with httpx.Client(timeout=10) as client:
        for path in ("/health", "/api/me"):
            response = client.get(base_url + path, headers=headers)
            print(f"GET {path} -> {response.status_code} {response.text}")
            response.raise_for_status()

        payload = {
            "event_type": "project",
            "name": "Smoke-тест HTTP API",
            "description": "Проверка create/list/get/search/patch/delete",
            "event_at": "2030-01-02T15:00:00+03:00",
            "duration_minutes": 45,
            "status": "new",
        }
        response = client.post(
            base_url + "/api/tasks",
            json=payload,
            headers={**headers, "Idempotency-Key": f"smoke-{uuid4()}"},
        )
        print(f"POST /api/tasks -> {response.status_code} {response.text}")
        response.raise_for_status()
        event_id = response.json()["event"]["id"]

        response = client.get(
            base_url + "/api/tasks",
            params={"date": "2030-01-02", "timezone": "Europe/Moscow"},
            headers=headers,
        )
        print(
            f"GET /api/tasks -> {response.status_code} "
            f"{json.dumps(response.json(), ensure_ascii=False)}"
        )
        response.raise_for_status()

        response = client.get(
            base_url + f"/api/tasks/{event_id}",
            headers=headers,
        )
        print(f"GET /api/tasks/{event_id} -> {response.status_code} {response.text}")
        response.raise_for_status()

        response = client.patch(
            base_url + f"/api/tasks/{event_id}",
            json={"status": "done"},
            headers=headers,
        )
        print(f"PATCH /api/tasks/{event_id} -> {response.status_code} {response.text}")
        response.raise_for_status()

        response = client.get(
            base_url + "/api/tasks/search",
            params={"q": "Smoke-тест"},
            headers=headers,
        )
        print(f"GET /api/tasks/search -> {response.status_code} {response.text}")
        response.raise_for_status()

        response = client.delete(base_url + f"/api/tasks/{event_id}", headers=headers)
        print(f"DELETE /api/tasks/{event_id} -> {response.status_code}")
        response.raise_for_status()

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
