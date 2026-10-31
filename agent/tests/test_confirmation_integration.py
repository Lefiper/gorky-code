"""Full server boundary with real PostgreSQL, Redis and authenticated MCP."""
import importlib.util
import os
from pathlib import Path
import unittest
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.config import Settings
from app.main import create_app
from app.mcp_client import CalendarMCP
from tests.fakes import ScriptedGigaChat


@unittest.skipUnless(os.getenv("AGENT_TEST_MCP_URL") and os.getenv("API_TEST_URL"), "Requires local stack")
class ConfirmationIntegration(unittest.TestCase):
    def test_miniapp_timezone_confirmation_restart_and_idempotency(self):
        spec = importlib.util.spec_from_file_location("signer", Path(__file__).parents[2] / "api/scripts/make_init_data.py")
        signer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(signer)
        uid = str(int(uuid4().hex[:12], 16))
        headers = {"X-Max-InitData": signer.build_init_data(os.environ["MAX_BOT_TOKEN"], uid)}
        api = httpx.Client(base_url=os.environ["API_TEST_URL"], headers=headers)
        self.assertEqual(api.put("/api/timezone", json={"timezone": "Asia/Yekaterinburg"}).status_code, 200)
        settings = Settings.from_env()
        model = ScriptedGigaChat(script=[AIMessage(content="", tool_calls=[{
            "id": "proposal", "name": "create_event", "args": {
                "event_type": "meeting", "name": "Врач", "datetime": "2030-01-02T15:00:00+05:00"}}])])
        agent = TestClient(create_app(settings, llm=model, mcp=CalendarMCP(os.environ["AGENT_TEST_MCP_URL"])))
        auth = {"Authorization": "Bearer " + settings.agent_api_key}
        body = {"user_id": uid, "message_id": "propose", "text": "создай встречу завтра в 15:00", "timezone": "UTC"}
        response = agent.post("/chat", json=body, headers=auth)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("Подтвердите", response.json()["reply"])
        self.assertIn("Asia/Yekaterinburg", model.calls[0][0])
        self.assertEqual(api.get("/api/tasks/search", params={"q": "врач"}).json()["items"], [])
        confirmed = agent.post("/chat", json=body | {"message_id": "confirm", "text": "да"}, headers=auth)
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        # Recreate all app objects: Redis stores pending/replies independently of process memory.
        restarted = TestClient(create_app(settings, llm=ScriptedGigaChat(script=[])))
        repeated = restarted.post("/chat", json=body | {"message_id": "confirm", "text": "да"}, headers=auth)
        self.assertEqual(repeated.json(), confirmed.json())
        items = api.get("/api/tasks/search", params={"q": "врач"}).json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["event_at"], "2030-01-02T10:00:00Z")
        api.close()
