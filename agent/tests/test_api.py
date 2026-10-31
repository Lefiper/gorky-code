import unittest

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.config import ConfigError, Settings
from app.main import create_app
from tests.fakes import FakeMCP, MemoryHistory, ScriptedGigaChat, NoPending


def client(script=None, *, key="", llm_configured=True, mcp=None):
    settings = Settings(agent_api_key=key, gigachat_credentials="test-credentials" if llm_configured else "")
    llm = ScriptedGigaChat(script=list(script or [])) if llm_configured else None
    app = create_app(settings, llm=llm, mcp=mcp or FakeMCP(), history=MemoryHistory(), confirmations=NoPending(), profile_reader=lambda uid, default: default)
    return TestClient(app), llm


BODY = {"user_id": "42", "message_id": "message:1", "conversation_id": "max:42",
        "text": "привет", "timezone": "Europe/Moscow", "now": "2026-10-29T12:00:00+03:00"}


class ChatEndpointTests(unittest.TestCase):
    def test_chat_returns_reply_in_contract_shape(self):
        test_client, _ = client(["Здравствуйте!"])
        response = test_client.post("/chat", json=BODY)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"reply": "Здравствуйте!"})

    def test_bearer_key_is_required_when_configured(self):
        test_client, _ = client(["Здравствуйте!"], key="secret-key")
        self.assertEqual(test_client.post("/chat", json=BODY).status_code, 401)
        self.assertEqual(test_client.post("/chat", json=BODY, headers={"Authorization": "Bearer wrong"}).status_code, 401)
        ok = test_client.post("/chat", json=BODY, headers={"Authorization": "Bearer secret-key"})
        self.assertEqual(ok.status_code, 200)

    def test_same_idempotency_key_returns_stored_reply_without_llm(self):
        test_client, llm = client(["Первый ответ", "Второй ответ"])
        first = test_client.post("/chat", json=BODY, headers={"Idempotency-Key": "message:1"})
        second = test_client.post("/chat", json=BODY, headers={"Idempotency-Key": "message:1"})
        self.assertEqual(first.json()["reply"], "Первый ответ")
        self.assertEqual(second.json()["reply"], "Первый ответ")
        self.assertEqual(len(llm.calls), 1)

    def test_unknown_timezone_is_422(self):
        test_client, _ = client(["x"])
        response = test_client.post("/chat", json=BODY | {"timezone": "Mars/Olympus"})
        self.assertEqual(response.status_code, 422)

    def test_empty_text_is_rejected(self):
        test_client, _ = client(["x"])
        self.assertEqual(test_client.post("/chat", json=BODY | {"text": ""}).status_code, 422)

    def test_missing_llm_is_503_not_fake_success(self):
        test_client, _ = client(llm_configured=False)
        response = test_client.post("/chat", json=BODY)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("reply", response.json())

    def test_user_id_from_body_is_the_only_identity_used_for_tools(self):
        mcp = FakeMCP({"get_event": {"items": [], "has_more": False}})
        script = [AIMessage(content="", tool_calls=[{"name": "get_event", "id": "c1", "args": {
            "start_time": "2026-10-29T00:00:00+03:00", "end_time": "2026-10-30T00:00:00+03:00"}}]),
            "Событий нет."]
        test_client, _ = client(script, mcp=mcp)
        response = test_client.post("/chat", json=BODY | {"text": "что сегодня"})
        self.assertEqual(response.json()["reply"], "Событий нет.")
        self.assertEqual(mcp.calls[0][1]["user_id"], "42")


class ConfigTests(unittest.TestCase):
    def test_secrets_are_hidden_in_repr(self):
        settings = Settings.from_env({"GIGACHAT_CREDENTIALS": "very-secret", "AGENT_API_KEY": "key-secret"})
        self.assertNotIn("very-secret", repr(settings))
        self.assertNotIn("key-secret", repr(settings))
        self.assertTrue(settings.llm_configured)

    def test_defaults_and_model_name(self):
        settings = Settings.from_env({})
        self.assertEqual(settings.gigachat_model, "GigaChat-2-Max")
        self.assertEqual(settings.gigachat_scope, "GIGACHAT_API_PERS")
        self.assertFalse(settings.llm_configured)

    def test_invalid_values_fail_fast(self):
        with self.assertRaises(ConfigError):
            Settings.from_env({"DEFAULT_TIMEZONE": "Nowhere/City"})
        with self.assertRaises(ConfigError):
            Settings.from_env({"AGENT_HISTORY_LIMIT": "101"})
        with self.assertRaises(ConfigError):
            Settings.from_env({"GIGACHAT_VERIFY_SSL_CERTS": "maybe"})


if __name__ == "__main__":
    unittest.main()
