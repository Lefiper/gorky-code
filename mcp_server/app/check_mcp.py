"""Пример MCP-клиента: список инструментов и чтение без создания событий."""

import argparse
import asyncio
import os
import sys
from uuid import uuid4

from fastmcp import Client
from fastmcp.client.transports import StdioTransport, StreamableHttpTransport
import httpx2

from app.config import PROJECT_ROOT


async def check(transport_name: str, port: int):
    if transport_name == "http":
        transport = StreamableHttpTransport(
            f"http://127.0.0.1:{port}/mcp",
            httpx_client_factory=lambda **kwargs: httpx2.AsyncClient(trust_env=False, **kwargs),
        )
    else:
        env = {key: value for key, value in os.environ.items() if key in {
            "PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD", "PGCONNECT_TIMEOUT"
        }}
        env["PYTHONIOENCODING"] = "utf-8"
        transport = StdioTransport(command=sys.executable, args=["-m", "app.mcp_server"],
                                   cwd=str(PROJECT_ROOT), env=env)
    async with Client(transport, timeout=20) as client:
        tools = await client.list_tools()
        print("MCP-инструменты:", ", ".join(tool.name for tool in tools))
        # Случайный вымышленный пользователь: проверка не читает личные события.
        result = await client.call_tool("get_event_by_query", {
            "user_id": "test:check:" + str(uuid4()), "text": "проверка",
        })
        if result.structured_content != {"items": [], "has_more": False}:
            raise RuntimeError("Неожиданный результат проверки")
        print("MCP-вызов и чтение PostgreSQL работают. Новые события не создавались.")


def main():
    parser = argparse.ArgumentParser(description="Проверка MCP-клиентом")
    parser.add_argument("--transport", choices=("stdio", "http"), default="stdio")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    try:
        asyncio.run(check(args.transport, args.port))
    except Exception:
        print("Проверка MCP не прошла. Проверьте .env, PostgreSQL и запуск HTTP-сервера, если выбран HTTP.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
