"""MCP-протокол: ошибки без БД, затем отдельные процессы stdio и HTTP с БД."""

import asyncio
import os
import socket
import subprocess
import sys
import unittest
from unittest.mock import Mock
from uuid import uuid4

from fastmcp import Client
from fastmcp.client.transports import StdioTransport, StreamableHttpTransport
import httpx2

from app.config import PROJECT_ROOT
from app.events import EventService, StorageError
from app.mcp_server import create_server


class MCPValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_schema_and_invalid_request(self):
        service = Mock(spec=EventService)
        async with Client(create_server(service)) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            self.assertEqual(set(tools), {"create_event", "get_event", "get_event_by_query"})
            self.assertEqual(set(tools["create_event"].input_schema["required"]), {"user_id", "event_type", "name", "datetime"})
            self.assertEqual(set(tools["get_event"].input_schema["required"]), {"user_id", "start_time", "end_time"})
            self.assertEqual(set(tools["get_event_by_query"].input_schema["required"]), {"user_id", "text"})
            self.assertIsNotNone(tools["create_event"].output_schema)
            self.assertTrue(tools["get_event"].annotations.read_only_hint)
            for changes in ({"limit": True}, {"limit": "10"}, {"limit": 101}, {"user_id": 123}, {"unexpected": "value"}):
                with self.subTest(changes=changes):
                    result = await client.call_tool("get_event", {
                        "user_id": "fake", "start_time": "2030-01-01T00:00:00Z",
                        "end_time": "2030-01-02T00:00:00Z", **changes,
                    }, raise_on_error=False)
                    self.assertTrue(result.is_error)
            service.get_event.assert_not_called()

    async def test_storage_failure_is_protocol_error(self):
        service = Mock(spec=EventService)
        service.create_event.side_effect = StorageError("private-driver-message")
        async with Client(create_server(service)) as client:
            result = await client.call_tool("create_event", {
                "user_id": "fake", "event_type": "task", "name": "Проверка ошибки",
                "datetime": "2030-01-01T00:00:00Z",
            }, raise_on_error=False)
            self.assertTrue(result.is_error)
            self.assertIn("STORAGE_ERROR", result.content[0].text)
            self.assertNotIn("private-driver-message", result.content[0].text)


@unittest.skipUnless(os.environ.get("ASSISTANT_RUN_DB_TESTS") == "1", "Нужен ASSISTANT_RUN_DB_TESTS=1")
class MCPProcessTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, client):
        tools = await client.list_tools()
        self.assertEqual({tool.name for tool in tools}, {"create_event", "get_event", "get_event_by_query"})
        user_id = "test:mcp:" + str(uuid4())
        args = dict(user_id=user_id, event_type="meeting", name="Обсуждение презентации",
                    description="Подготовка материалов для команды", datetime="2031-05-03T15:00:00+03:00",
                    idempotency_key="confirmation-001")
        created = await client.call_tool("create_event", args)
        self.assertFalse(created.is_error)
        data = created.structured_content
        self.assertTrue(data["created"])
        self.assertEqual(data["event"]["event_at"], "2031-05-03T12:00:00Z")
        repeated = await client.call_tool("create_event", args)
        self.assertFalse(repeated.structured_content["created"])
        self.assertEqual(repeated.structured_content["event"]["id"], data["event"]["id"])
        period = dict(user_id=user_id, start_time="2031-05-03T00:00:00+03:00", end_time="2031-05-04T00:00:00+03:00")
        page = await client.call_tool("get_event", period)
        self.assertEqual(page.structured_content, {"items": [data["event"]], "has_more": False})
        for text in ("презентация", "материалы команды"):
            result = await client.call_tool("get_event_by_query", {"user_id": user_id, "text": text})
            self.assertEqual(result.structured_content["items"][0]["id"], data["event"]["id"])
        empty = await client.call_tool("get_event", period | {"user_id": "test:absent:" + str(uuid4())})
        self.assertEqual(empty.structured_content["items"], [])
        invalid = await client.call_tool("create_event", args | {"datetime": "2031-05-03T15:00:00"}, raise_on_error=False)
        self.assertTrue(invalid.is_error)
        self.assertIn("VALIDATION_ERROR", invalid.content[0].text)
        conflict = await client.call_tool("create_event", args | {"name": "Другие данные"}, raise_on_error=False)
        self.assertTrue(conflict.is_error)
        self.assertIn("CONFLICT", conflict.content[0].text)

    async def test_stdio_separate_process(self):
        # Явно передаём лишь настройки БД; пароль не попадает в аргументы процесса.
        env = {key: value for key, value in os.environ.items() if key in {
            "PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD", "PGCONNECT_TIMEOUT"
        }}
        env["PYTHONIOENCODING"] = "utf-8"
        transport = StdioTransport(command=sys.executable, args=["-m", "app.mcp_server"],
                                   cwd=str(PROJECT_ROOT), env=env)
        async with Client(transport, timeout=20) as client:
            await self.exercise(client)

    async def test_http_separate_process(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        process = subprocess.Popen(
            [sys.executable, "-m", "app.mcp_server", "--transport", "http", "--port", str(port)],
            cwd=PROJECT_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=os.environ | {"PYTHONIOENCODING": "utf-8"},
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        try:
            # Ждём готовность TCP, затем проверяем именно MCP handshake и tools/call.
            for _ in range(150):
                if process.poll() is not None:
                    self.fail("HTTP MCP-сервер завершился до подключения клиента")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                        break
                except OSError:
                    await asyncio.sleep(0.1)
            else:
                self.fail("HTTP MCP-сервер не открыл порт за 15 секунд")
            # Локальный трафик не должен идти через системный HTTP-прокси.
            transport = StreamableHttpTransport(
                f"http://127.0.0.1:{port}/mcp",
                httpx_client_factory=lambda **kwargs: httpx2.AsyncClient(trust_env=False, **kwargs),
            )
            async with Client(transport, timeout=20) as client:
                await self.exercise(client)
        finally:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait, timeout=5)


if __name__ == "__main__":
    unittest.main()
