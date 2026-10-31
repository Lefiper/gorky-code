"""Агент → настоящий MCP-сервер → PostgreSQL. Нужен AGENT_TEST_MCP_URL (например http://127.0.0.1:8001/mcp).

LLM здесь заглушка: проверяется связка инструментов с реальными данными, а не качество GigaChat.
"""

import os
import unittest
import uuid
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage

from app.agent import CalendarAgent
from app.config import Settings
from app.mcp_client import CalendarMCP
from tests.fakes import MemoryHistory, ScriptedGigaChat

MCP_URL = os.environ.get("AGENT_TEST_MCP_URL", "")


def call(name, args, call_id):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


@unittest.skipUnless(MCP_URL, "Задайте AGENT_TEST_MCP_URL для проверки с настоящим MCP")
class AgentWithMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_then_search_uses_real_storage_with_server_user_id(self):
        user = "test:agent:" + uuid.uuid4().hex
        tz = "Europe/Moscow"
        # Модель выбирает инструменты; user_id в её аргументах намеренно подменён.
        script = [
            call("create_event", {"event_type": "meeting", "name": "Встреча с Иваном",
                                  "datetime": "2030-01-02T15:00:00+03:00", "user_id": "intruder"}, "c1"),
            call("get_event_by_query", {"text": "Иваном"}, "c2"),
            "Нашёл встречу с Иваном.",
        ]
        llm = ScriptedGigaChat(script=script)
        agent = CalendarAgent(llm=llm, mcp=CalendarMCP(MCP_URL), history=MemoryHistory(),
                              settings=Settings(), clock=None)
        await agent.reply(user_id=user, message_id="message:e2e-1", text="встреча с Иваном 2 января в 15", timezone_name=tz)
        await agent.reply(user_id=user, message_id="message:confirm", text="да", timezone_name=tz)
        found = await agent.reply(user_id=user, message_id="message:e2e-2", text="найди Иваном", timezone_name=tz)
        self.assertEqual(found, "Нашёл встречу с Иваном.")

        # Повтор того же сообщения (потеря ответа) не создаёт дубль.
        llm.script = [call("create_event", {"event_type": "meeting", "name": "Встреча с Иваном",
                                            "datetime": "2030-01-02T15:00:00+03:00"}, "c3"), "ok"]
        await agent.reply(user_id=user, message_id="message:e2e-1", text="повтор", timezone_name=tz)

        check = CalendarMCP(MCP_URL)
        page = await check.call("get_event", {"user_id": user, "start_time": "2030-01-02T00:00:00+03:00",
                                              "end_time": "2030-01-03T00:00:00+03:00"})
        self.assertEqual(len(page["items"]), 1)
        self.assertEqual(page["items"][0]["event_at"], "2030-01-02T12:00:00Z")
        self.assertEqual(ZoneInfo(tz).key, "Europe/Moscow")
        other = await check.call("get_event", {"user_id": "intruder", "start_time": "2030-01-02T00:00:00+03:00",
                                               "end_time": "2030-01-03T00:00:00+03:00"})
        self.assertEqual(other["items"], [])


if __name__ == "__main__":
    unittest.main()
