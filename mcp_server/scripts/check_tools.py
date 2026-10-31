"""Прямой вызов трёх MCP-инструментов по HTTP: create_event → get_event → get_event_by_query.

    python -m scripts.check_tools --url http://127.0.0.1:8001/mcp

Использует вымышленного пользователя с префиксом test:check: и уникальный ключ операции.
Завершается с кодом 1, если результат не совпал с ожидаемым.
"""

import os
import argparse
import asyncio
import sys
import uuid

from fastmcp import Client


async def run(url: str) -> int:
    user = "test:check:" + uuid.uuid4().hex[:12]
    key = "check-" + uuid.uuid4().hex
    async with Client(url, auth=os.environ.get("MCP_AUTH_TOKEN") or None) as client:
        names = sorted(tool.name for tool in await client.list_tools())
        print("tools:", ", ".join(names))
        created = (await client.call_tool("create_event", {
            "user_id": user, "event_type": "meeting", "name": "Встреча с Иваном",
            "description": "Обсудить смету", "datetime": "2030-01-02T15:00:00+03:00",
            "idempotency_key": key,
        })).structured_content
        print("create_event:", created["created"], created["event"]["event_at"])
        found = (await client.call_tool("get_event", {
            "user_id": user, "start_time": "2030-01-02T00:00:00+03:00",
            "end_time": "2030-01-03T00:00:00+03:00", "event_type": ["meeting"],
        })).structured_content["items"]
        print("get_event:", [item["name"] for item in found])
        matched = (await client.call_tool("get_event_by_query", {
            "user_id": user, "text": "смету",
        })).structured_content["items"]
        print("get_event_by_query:", [item["name"] for item in matched])
    ok = (created["created"] is True
          and [item["id"] for item in found] == [created["event"]["id"]]
          and [item["id"] for item in matched] == [created["event"]["id"]])
    print("RESULT:", "OK" if ok else "FAILED")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка трёх MCP-инструментов")
    parser.add_argument("--url", default="http://127.0.0.1:8001/mcp")
    args = parser.parse_args()
    return asyncio.run(run(args.url))


if __name__ == "__main__":
    sys.exit(main())
