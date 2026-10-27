"""Проверка именно запущенного Docker MCP с отдельной ролью PostgreSQL."""

from dataclasses import replace
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
import httpx2

from app.config import Settings, RedisSettings
from app.confirmation import save_confirmed_event
from app.db.connection import connect
from app.db.migrations import migrate, MigrationError
from app.memory import ConversationStore


@unittest.skipUnless(os.environ.get("STACK_MCP_URL"), "Требуется запущенный Docker-стек")
class DockerStackTests(unittest.IsolatedAsyncioTestCase):
    async def test_running_mcp_redis_confirmation_and_health(self):
        async with httpx2.AsyncClient(trust_env=False) as http:
            response = await http.get(os.environ["STACK_MCP_HEALTH_URL"])
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"status": "ok"})
        transport = StreamableHttpTransport(os.environ["STACK_MCP_URL"],
            httpx_client_factory=lambda **kw: httpx2.AsyncClient(trust_env=False, **kw))
        with ConversationStore(replace(RedisSettings.load(), key_prefix="assistant:test:" + uuid4().hex, ttl_seconds=30)) as memory:
            user = "test:docker:" + uuid4().hex
            pending = memory.set_pending_event(user, "task", "Проверка установки с нуля", "2033-01-02T10:00:00+03:00")
            memory.append_message(user, "user", "да")
            async with Client(transport, timeout=20) as client:
                self.assertEqual({t.name for t in await client.list_tools()}, {"create_event", "get_event", "get_event_by_query"})
                saved = await save_confirmed_event(memory, client, user, pending["idempotency_key"])
                self.assertTrue(saved["created"])
                result = await client.call_tool("get_event_by_query", {"user_id": user, "text": "проверка установки"})
                self.assertEqual(result.structured_content["items"][0]["id"], saved["event"]["id"])

    async def test_migrations_indexes_and_limited_app_role(self):
        with connect(Settings.load()) as conn:
            self.assertEqual(migrate(conn), [])
            indexes = {r["indexname"] for r in conn.execute("SELECT indexname FROM pg_indexes WHERE schemaname='public' AND tablename='events'")}
            self.assertTrue({"events_user_time_idx", "events_user_type_time_idx", "events_search_gin_idx"}.issubset(indexes))
            permissions = conn.execute("""SELECT rolsuper,
                has_table_privilege('assistant_app', 'public.events', 'SELECT') AS can_read,
                has_table_privilege('assistant_app', 'public.events', 'INSERT') AS can_insert,
                has_table_privilege('assistant_app', 'public.events', 'DELETE') AS can_delete,
                has_table_privilege('assistant_app', 'public.events', 'UPDATE') AS can_update,
                has_schema_privilege('assistant_app', 'public', 'CREATE') AS can_create
                FROM pg_roles WHERE rolname='assistant_app'""").fetchone()
            self.assertEqual(permissions, {"rolsuper": False, "can_read": True, "can_insert": True, "can_delete": False, "can_update": False, "can_create": False})
        app_settings = replace(Settings.load(), user="assistant_app", password=os.environ["APP_DB_PASSWORD"])
        with connect(app_settings) as conn:
            self.assertEqual(conn.execute("SELECT current_user AS name").fetchone()["name"], "assistant_app")

    async def test_changed_migration_is_rejected(self):
        from pathlib import Path
        original = Path.read_bytes
        def changed(path):
            content = original(path)
            return content + b"\n-- unexpected change\n" if path.name == "001_create_events.sql" else content
        with self.assertRaises(MigrationError):
            with connect(Settings.load()) as conn, patch.object(Path, "read_bytes", changed):
                migrate(conn)


if __name__ == "__main__":
    unittest.main()
