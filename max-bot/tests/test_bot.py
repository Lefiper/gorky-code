import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from bot import Bot, Store, event_key, handler_for, keyboard


def event(text="Завтра встреча", mid="m1", uid=123):
    return {"update_type": "message_created", "message": {
        "sender": {"user_id": uid}, "recipient": {"chat_type": "dialog"},
        "body": {"mid": mid, "text": text}}}


class BotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "state.db")
        self.store = Store(self.path)
        self.http, self.api = Mock(), Mock()
        self.bot = Bot(self.store, self.http, self.api)
        self.env = patch.dict(os.environ, {"AGENT_MODE": "http", "AGENT_URL": "http://agent/chat",
                                           "MINI_APP_LINK": "", "STT_URL": "http://stt/transcribe",
                                           "AUDIO_ALLOWED_HOSTS": "cdn.example.com"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.store.db.close()
        self.temp.cleanup()

    def process(self, data):
        self.store.enqueue(data)
        self.bot.process(self.store.next_job())

    def test_duplicate_survives_restart(self):
        self.store.enqueue(event())
        self.store.db.close()
        self.store = Store(self.path)
        self.store.enqueue(event())
        self.assertEqual(self.store.execute("SELECT count(*) FROM jobs").fetchone()[0], 1)

    def test_welcome_does_not_call_agent(self):
        self.process(event("/start"))
        self.http.json.assert_not_called()
        self.assertIn("Напомни завтра", self.api.send.call_args.args[1])

    def test_today_and_stable_context_and_user_isolation(self):
        self.http.json.return_value = {"reply": "Планы", "user_id": 999}
        self.process(event("/today"))
        payload = self.http.json.call_args.args[2]
        self.assertEqual(payload["text"], "Что у меня сегодня?")
        self.assertEqual(payload["conversation_id"], "max:123")
        self.assertEqual(payload["timezone"], "Europe/Moscow")
        self.assertEqual(self.api.send.call_args.args[0], 123)

    def test_followup_uses_same_conversation(self):
        self.http.json.return_value = {"reply": "На какое время?"}
        self.process(event("Встреча завтра"))
        first = self.http.json.call_args.args[2]
        self.process(event("В три", mid="m2"))
        second = self.http.json.call_args.args[2]
        self.assertEqual(first["conversation_id"], second["conversation_id"])
        self.assertNotEqual(first["message_id"], second["message_id"])

    def test_delivery_retry_does_not_call_agent_twice(self):
        self.http.json.return_value = {"reply": "Создано"}
        self.api.send.side_effect = [None, OSError("network"), None]
        self.store.enqueue(event())
        with self.assertRaises(OSError):
            self.bot.process(self.store.next_job())
        self.bot.process(self.store.next_job())
        self.assertEqual(self.http.json.call_count, 1)
        self.assertIsNone(self.store.next_job())

    def test_failure_does_not_confirm_creation(self):
        self.http.json.side_effect = TimeoutError()
        self.process(event())
        self.assertIn("не могу подтвердить", self.api.send.call_args.args[1])

    def test_group_ignored(self):
        data = event()
        data["message"]["recipient"]["chat_type"] = "chat"
        self.process(data)
        self.api.send.assert_not_called()
        self.http.json.assert_not_called()

    def test_audio_transcription_and_agent(self):
        data = event("")
        data["message"]["body"]["attachments"] = [{"type": "audio", "payload": {
            "url": "https://cdn.example.com/audio.ogg"}}]
        self.http.raw.side_effect = [b"audio", json.dumps({"text": "Позвонить Ивану"}).encode()]
        self.http.json.return_value = {"reply": "На какое время?"}
        self.process(data)
        self.assertEqual(self.http.json.call_args.args[2]["text"], "Позвонить Ивану")
        self.assertIn(b'filename="voice.ogg"', self.http.raw.call_args.args[2])

    def test_untrusted_audio_url_rejected(self):
        with self.assertRaises(ValueError):
            self.bot.speech({"payload": {"url": "https://localhost/secret"}})
        self.http.raw.assert_not_called()

    def test_callback_acknowledged(self):
        self.http.json.return_value = {"reply": "Завтрашние планы"}
        self.process({"update_type": "message_callback", "callback": {
            "callback_id": "cb1", "user": {"user_id": 123}, "payload": "tomorrow"}})
        self.api.call.assert_called_once_with("POST", "/answers", {}, callback_id="cb1")
        self.assertEqual(self.http.json.call_args.args[2]["text"], "Что у меня завтра?")

    def test_reminder_registration_is_idempotent(self):
        item = {"id": "r1", "user_id": 123, "text": "Позвонить", "due_at": "2020-01-01T10:00:00+03:00"}
        self.store.remind(item)
        self.bot.reminders()
        self.store.remind(item)
        self.bot.reminders()
        self.api.send.assert_called_once_with(123, "Напоминание: Позвонить")
        with self.assertRaises(ValueError):
            self.store.remind({**item, "user_id": 999})

    def test_naive_reminder_date_rejected(self):
        with self.assertRaises(ValueError):
            self.store.remind({"id": "r", "user_id": 1, "text": "x", "due_at": "2026-10-25T10:00:00"})

    def test_long_answer_split(self):
        self.http.json.return_value = {"reply": "я" * 8001}
        self.process(event())
        messages = self.api.send.call_args_list[1:]
        self.assertEqual(len(messages), 3)
        self.assertTrue(all(len(c.args[1]) <= 3500 for c in messages))

    def test_mini_app_button(self):
        with patch.dict(os.environ, {"MINI_APP_LINK": "https://max.ru/example_bot?startapp"}):
            self.assertEqual(keyboard()[0]["payload"]["buttons"][-1][0]["type"], "link")

    def test_webhook_auth_and_durable_ack(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(self.bot))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}/webhook"
        try:
            with patch.dict(os.environ, {"WEBHOOK_SECRET": "test-secret"}):
                request = Request(url, data=json.dumps(event()).encode(), method="POST")
                with self.assertRaises(HTTPError) as error:
                    urlopen(request)
                self.assertEqual(error.exception.code, 403)
                request.add_header("X-Max-Bot-Api-Secret", "test-secret")
                with urlopen(request) as response:
                    self.assertEqual(response.status, 200)
                self.assertIsNotNone(self.store.next_job())
                self.api.send.assert_not_called()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
