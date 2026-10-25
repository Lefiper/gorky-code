"""Redis-тесты используют собственные случайные ключи, без FLUSHDB/FLUSHALL."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from app.config import ConfigError, PROJECT_ROOT, RedisSettings
from app.confirmation import ConfirmationError, save_confirmed_event
from app.memory import ConversationStore, MemoryStorageError, MemoryValidationError
import sys


class MemoryValidationTests(unittest.TestCase):
    def test_invalid_config_and_hidden_url(self):
        for changes in ({"url": "http://localhost"}, {"ttl_seconds": 0}, {"ttl_seconds": 901},
                        {"history_limit": 11}, {"history_limit": True}, {"key_prefix": "bad{key}"}):
            with self.subTest(changes=changes), self.assertRaises(ConfigError):
                RedisSettings(**changes)
        self.assertNotIn("secret", repr(RedisSettings(url="redis://:secret@localhost:6379/0")))

    def test_invalid_inputs_never_write(self):
        with ConversationStore(RedisSettings()) as store, patch.object(store.client, "eval") as execute:
            for role, content in (("system", "text"), ("user", " "), ("assistant", "x" * 10001)):
                with self.assertRaises(MemoryValidationError):
                    store.append_message("fictional", role, content)
            with self.assertRaises(MemoryValidationError):
                store.append_message("", "user", "text")
            with self.assertRaises(MemoryValidationError):
                store.set_pending_event("fictional", "task", "Проверка", "2030-01-01T10:00:00")
            with self.assertRaises(MemoryValidationError):
                store.append_asr_message("fictional", {"text": "Тест", "engine": "fake", "audio_sec": -1, "latency_ms": 1})
            execute.assert_not_called()


class ConfirmationTests(unittest.IsolatedAsyncioTestCase):
    async def test_expired_or_changed_context_never_calls_mcp(self):
        memory, client = Mock(), Mock()
        client.call_tool = AsyncMock()
        for pending in (None, {"idempotency_key": "new"}):
            memory.get_context.return_value = {"pending_event": pending}
            with self.assertRaises(ConfirmationError):
                await save_confirmed_event(memory, client, "fake", "old")
        client.call_tool.assert_not_called()

    async def test_mcp_error_preserves_pending(self):
        memory = Mock()
        memory.get_context.return_value = {"pending_event": {"idempotency_key": "same"}}
        client = Mock(call_tool=AsyncMock(side_effect=TimeoutError))
        with self.assertRaises(TimeoutError):
            await save_confirmed_event(memory, client, "fake", "same")
        memory.clear_pending_event.assert_not_called()

    async def test_cleanup_failure_does_not_hide_saved_event(self):
        memory = Mock()
        memory.get_context.return_value = {"pending_event": {"idempotency_key": "same"}}
        memory.clear_pending_event.side_effect = MemoryStorageError("unavailable")
        client = Mock(call_tool=AsyncMock(return_value=Mock(is_error=False, structured_content={"event": {"id": "fake"}, "created": True})))
        result = await save_confirmed_event(memory, client, "fake", "same")
        self.assertTrue(result["created"])
        self.assertFalse(result["context_cleared"])


@unittest.skipUnless(os.environ.get("ASSISTANT_RUN_REDIS_TESTS") == "1", "Нужен ASSISTANT_RUN_REDIS_TESTS=1")
class RedisTests(unittest.TestCase):
    def setUp(self):
        settings = replace(RedisSettings.load(), key_prefix="assistant:test:" + uuid4().hex, ttl_seconds=5)
        self.store = ConversationStore(settings)
        self.addCleanup(self.store.close)
        self.user = "test:user"

    def test_history_limit_order_and_user_isolation(self):
        for number in range(12):
            self.store.append_message(self.user, "user" if number % 2 == 0 else "assistant", str(number))
        context = self.store.get_context(self.user)
        self.assertEqual([m["content"] for m in context["messages"]], [str(n) for n in range(2, 12)])
        self.assertEqual(context["messages"][0]["role"], "user")
        self.assertEqual(self.store.get_context("another"), {"messages": [], "pending_event": None})

    def test_asr_metadata(self):
        self.store.append_asr_message(self.user, {"text": "Встреча с вымышленной командой", "engine": "test-asr", "audio_sec": 2.5, "latency_ms": 120})
        message = self.store.get_context(self.user)["messages"][0]
        self.assertEqual(message["content"], "Встреча с вымышленной командой")
        self.assertEqual(message["asr"], {"engine": "test-asr", "audio_sec": 2.5, "latency_ms": 120.0})

    def test_pending_survives_history_trimming_and_old_clear_is_safe(self):
        old = self.store.set_pending_event(self.user, "task", "Первый вариант", "2030-01-02T10:00:00+03:00")
        new = self.store.set_pending_event(self.user, "task", "Исправленный вариант", "2030-01-02T11:00:00+03:00")
        for n in range(12):
            self.store.append_message(self.user, "user", str(n))
        self.assertNotEqual(old["idempotency_key"], new["idempotency_key"])
        self.assertFalse(self.store.clear_pending_event(self.user, old["idempotency_key"]))
        self.assertEqual(self.store.get_context(self.user)["pending_event"], new)
        self.assertTrue(self.store.clear_pending_event(self.user, new["idempotency_key"]))
        self.assertIsNone(self.store.get_context(self.user)["pending_event"])

    def test_ttl_expiration_and_refresh(self):
        self.store.append_message(self.user, "user", "Запрос")
        self.store.set_pending_event(self.user, "task", "Проверка", "2030-01-02T10:00:00Z")
        keys = self.store._keys(self.user)
        # Укорачиваем TTL исключительно собственных случайных тестовых ключей.
        for key in keys:
            self.store.client.pexpire(key, 100)
        self.store.append_message(self.user, "assistant", "Создать событие?")
        for key in keys:
            self.assertGreater(self.store.client.pttl(key), 4000)
        for key in keys:
            self.store.client.pexpire(key, 100)
        deadline = time.monotonic() + 3
        while self.store.get_context(self.user) != {"messages": [], "pending_event": None}:
            if time.monotonic() > deadline:
                self.fail("Тестовый контекст не истёк")
            time.sleep(0.05)
        # Истёкшее предложение не восстанавливается новым сообщением «да».
        self.store.append_message(self.user, "user", "да")
        self.assertIsNone(self.store.get_context(self.user)["pending_event"])

    def test_concurrent_appends_keep_only_ten(self):
        def append(number):
            self.store.append_message(self.user, "user", str(number))
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(append, range(30)))
        messages = self.store.get_context(self.user)["messages"]
        self.assertEqual(len(messages), 10)
        self.assertEqual(len({m["content"] for m in messages}), 10)

    def test_corruption_is_error_not_empty_context(self):
        key = self.store._keys(self.user)[1]
        self.store.client.set(key, "not-json", ex=5)
        with self.assertRaises(MemoryStorageError):
            self.store.get_context(self.user)

    def test_connection_failure_is_safe(self):
        with ConversationStore(replace(self.store.settings, url="redis://:fictional-secret@127.0.0.1:1/0")) as broken:
            with self.assertRaises(MemoryStorageError) as error:
                broken.get_context(self.user)
            self.assertNotIn("fictional-secret", str(error.exception))


@unittest.skipUnless(os.environ.get("ASSISTANT_RUN_REDIS_TESTS") == "1" and os.environ.get("ASSISTANT_RUN_DB_TESTS") == "1", "Нужны оба интеграционных флага")
class RedisMCPPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def test_confirmation_retry_after_lost_response(self):
        settings = replace(RedisSettings.load(), key_prefix="assistant:test:" + uuid4().hex, ttl_seconds=30)
        with ConversationStore(settings) as memory:
            user = "test:confirmation:" + uuid4().hex
            memory.append_asr_message(user, {"text": "Создай встречу с командой", "engine": "fake-asr", "audio_sec": 3.2, "latency_ms": 80})
            pending = memory.set_pending_event(user, "meeting", "Встреча с вымышленной командой", "2032-01-02T15:00:00+03:00")
            memory.append_message(user, "assistant", "Создать встречу 2 января в 15:00 по Москве?")
            memory.append_message(user, "user", "да")
            env = {key: value for key, value in os.environ.items() if key in {
                "PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD", "PGCONNECT_TIMEOUT"
            }} | {"PYTHONIOENCODING": "utf-8"}
            transport = StdioTransport(command=sys.executable, args=["-m", "app.mcp_server"], cwd=str(PROJECT_ROOT), env=env)
            async with Client(transport, timeout=20) as client:
                async def lose_response(*args, **kwargs):
                    await client.call_tool(*args, **kwargs)
                    raise TimeoutError("Вымышленная потеря ответа после COMMIT")
                faulty_client = Mock(call_tool=AsyncMock(side_effect=lose_response))
                with self.assertRaises(TimeoutError):
                    await save_confirmed_event(memory, faulty_client, user, pending["idempotency_key"])
                self.assertEqual(memory.get_context(user)["pending_event"]["idempotency_key"], pending["idempotency_key"])
                saved = await save_confirmed_event(memory, client, user, pending["idempotency_key"])
                self.assertFalse(saved["created"])
                self.assertTrue(saved["context_cleared"])
                self.assertIsNone(memory.get_context(user)["pending_event"])
                # Потеря Redis-контекста не затрагивает сохранённые события PostgreSQL.
                for key in memory._keys(user):
                    memory.client.pexpire(key, 1)
                await asyncio.sleep(0.05)
                self.assertEqual(memory.get_context(user), {"messages": [], "pending_event": None})
                result = await client.call_tool("get_event", {"user_id": user, "start_time": "2032-01-02T00:00:00Z", "end_time": "2032-01-03T00:00:00Z"})
                self.assertEqual([e["id"] for e in result.structured_content["items"]], [saved["event"]["id"]])


if __name__ == "__main__":
    unittest.main()
