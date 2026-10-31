"""Клиент к MCP Server календаря (FastMCP, Streamable HTTP)."""

from __future__ import annotations

import os
from typing import Any

from fastmcp import Client
from fastmcp.exceptions import ToolError


class MCPError(RuntimeError):
    """Безопасное сообщение об ошибке инструмента: без параметров подключения."""


class CalendarMCP:
    def __init__(self, target: Any):
        # target — URL MCP-сервера или экземпляр FastMCP (для тестов в памяти).
        self.target = target

    async def call(self, name: str, arguments: dict) -> dict:
        try:
            async with Client(self.target, auth=os.environ.get("MCP_AUTH_TOKEN") or None) as client:
                result = await client.call_tool(name, arguments)
        except ToolError as exc:
            raise MCPError(str(exc)) from None
        except Exception:
            raise MCPError("MCP-сервер календаря недоступен.") from None
        data = result.structured_content
        if not isinstance(data, dict):
            raise MCPError("Неожиданный ответ MCP-сервера.")
        return data
