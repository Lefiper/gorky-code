"""Три MCP-инструмента через настоящий клиент FastMCP: create → get → get_by_query.

Нужна PostgreSQL с миграциями (ASSISTANT_RUN_DB_TESTS=1), иначе тест пропускается.
"""

import os
import unittest
import uuid

from fastmcp import Client

from app.config import Settings
from app.events import EventService
from app.mcp_server import create_server

RUN_DB = os.environ.get("ASSISTANT_RUN_DB_TESTS") == "1"


@unittest.skipUnless(RUN_DB, "Задайте ASSISTANT_RUN_DB_TESTS=1 и параметры PostgreSQL")
class ThreeToolsFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_get_and_search_return_consistent_results(self):
        user = "test:flow:" + uuid.uuid4().hex
        server = create_server(EventService(Settings.load()))
        async with Client(server) as client:
            names = {tool.name for tool in await client.list_tools()}
            self.assertEqual(names, {"create_event", "get_event", "get_event_by_query", "delete_event", "update_event_time"})

            created = (await client.call_tool("create_event", {
                "user_id": user, "event_type": "meeting", "name": "Встреча с Иваном",
                "description": "Обсудить смету и сроки", "datetime": "2030-01-02T15:00:00+03:00",
                "idempotency_key": "flow-" + user,
            })).structured_content
            self.assertTrue(created["created"])
            self.assertEqual(created["event"]["event_at"], "2030-01-02T12:00:00Z")

            repeated = (await client.call_tool("create_event", {
                "user_id": user, "event_type": "meeting", "name": "Встреча с Иваном",
                "description": "Обсудить смету и сроки", "datetime": "2030-01-02T15:00:00+03:00",
                "idempotency_key": "flow-" + user,
            })).structured_content
            self.assertFalse(repeated["created"])
            self.assertEqual(repeated["event"]["id"], created["event"]["id"])

            period = await client.call_tool("get_event", {
                "user_id": user, "start_time": "2030-01-02T00:00:00+03:00",
                "end_time": "2030-01-03T00:00:00+03:00", "event_type": ["meeting", "task"],
            })
            items = period.structured_content["items"]
            self.assertEqual([item["id"] for item in items], [created["event"]["id"]])

            found = (await client.call_tool("get_event_by_query", {
                "user_id": user, "text": "смету сроки",
            })).structured_content["items"]
            self.assertEqual([item["name"] for item in found], ["Встреча с Иваном"])

            missing = (await client.call_tool("get_event_by_query", {
                "user_id": user, "text": "стоматолог",
            })).structured_content
            self.assertEqual(missing, {"items": [], "has_more": False})

            other_user = (await client.call_tool("get_event", {
                "user_id": user + "-other", "start_time": "2030-01-02T00:00:00+03:00",
                "end_time": "2030-01-03T00:00:00+03:00",
            })).structured_content
            self.assertEqual(other_user["items"], [])

    async def test_invalid_arguments_are_rejected_by_tool_schema_or_service(self):
        server = create_server(EventService(Settings.load()))
        async with Client(server) as client:
            with self.assertRaises(Exception):
                await client.call_tool("create_event", {
                    "user_id": "test:flow:bad", "event_type": "party", "name": "x",
                    "datetime": "2030-01-02T15:00:00+03:00",
                })
            with self.assertRaises(Exception):
                await client.call_tool("get_event", {
                    "user_id": "test:flow:bad", "start_time": "2030-01-02T00:00:00",
                    "end_time": "2030-01-03T00:00:00+03:00",
                })


if __name__ == "__main__":
    unittest.main()
