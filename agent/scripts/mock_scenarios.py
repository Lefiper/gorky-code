"""POST /chat scenarios with a scripted GigaChat interface and real MCP/Redis/DB.

Run from agent/ with PYTHONPATH containing the repository root and PG*/REDIS_URL configured.
This checks orchestration, not live model quality.
"""
import asyncio
from datetime import datetime, timedelta
import uuid
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.config import Settings
from app.main import create_app
from app.mcp_client import CalendarMCP
from tests.fakes import ScriptedGigaChat


def call(name, arguments, key):
    return AIMessage(content="", tool_calls=[{"name": name, "args": arguments, "id": key}])


def main():
    settings = Settings.from_env()
    zone = ZoneInfo(settings.default_timezone)
    now = datetime.now(zone)
    tomorrow = (now + timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0)
    week = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    llm = ScriptedGigaChat(script=[
        call("create_event", {"event_type": "meeting", "name": "Врач", "datetime": tomorrow.isoformat()}, "proposal"),
        call("get_event", {"start_time": week.isoformat(), "end_time": (week + timedelta(days=7)).isoformat()}, "week"),
        "Список событий получен.",
        call("get_event_by_query", {"text": "врач"}, "search"), "Поиск выполнен.",
        "Как назвать задачу и на какое время её записать?", "Здравствуйте!",
    ])
    mcp = CalendarMCP(settings.mcp_url)
    client = TestClient(create_app(settings, llm=llm, mcp=mcp))
    user = "test:scenarios:" + uuid.uuid4().hex
    headers = {"Authorization": "Bearer " + settings.agent_api_key}
    scenarios = ["создай встречу завтра в 15:00", "да", "что у меня на этой неделе",
                 "найди про врача", "запиши задачу", "привет, как дела?"]
    for number, text in enumerate(scenarios):
        body = {"user_id": user, "message_id": str(number), "text": text}
        response = client.post("/chat", json=body, headers=headers)
        assert response.status_code == 200, response.text
        if number == 0:
            before = asyncio.run(mcp.call("get_event_by_query", {"user_id": user, "text": "врач"}))
            assert before["items"] == []
        if number == 1:
            after = asyncio.run(mcp.call("get_event_by_query", {"user_id": user, "text": "врач"}))
            assert len(after["items"]) == 1
            assert datetime.fromisoformat(after["items"][0]["event_at"].replace("Z", "+00:00")) == tomorrow
            assert client.post("/chat", json=body, headers=headers).json() == response.json()
        print(f"POST /chat {text!r} -> 200: {response.json()['reply']}")
    assert len(llm.calls) == 7
    print("OK: confirmation, relative time, weekly lookup, search, clarification, small talk, idempotency")


if __name__ == "__main__":
    main()
