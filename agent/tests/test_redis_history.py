"""Контекст в настоящем Redis. Нужен AGENT_TEST_REDIS_URL, иначе тесты пропускаются."""

import os
import unittest
import uuid

from redis import Redis

from app.history import ChatHistory

REDIS_URL = os.environ.get("AGENT_TEST_REDIS_URL", "")


@unittest.skipUnless(REDIS_URL, "Задайте AGENT_TEST_REDIS_URL для проверки Redis")
class RedisHistoryTests(unittest.TestCase):
    def setUp(self):
        self.prefix = "agenttest:" + uuid.uuid4().hex[:8]
        self.user = "test:" + uuid.uuid4().hex
        self.client = Redis.from_url(REDIS_URL, decode_responses=True)

    def tearDown(self):
        for key in self.client.scan_iter(self.prefix + "*"):
            self.client.delete(key)
        self.client.close()

    def history(self, limit=10, ttl=900):
        return ChatHistory(self.client, prefix=self.prefix, limit=limit, ttl_seconds=ttl, idempotency_ttl_seconds=60)

    def test_context_survives_between_replicas(self):
        # Два разных объекта с одним Redis: как две реплики агента.
        self.history().append(self.user, [("user", "Встреча с Иваном"), ("assistant", "На какое время?")])
        other = ChatHistory(Redis.from_url(REDIS_URL, decode_responses=True), prefix=self.prefix,
                            limit=10, ttl_seconds=900, idempotency_ttl_seconds=60)
        items = other.get(self.user)
        self.assertEqual([i["content"] for i in items], ["Встреча с Иваном", "На какое время?"])

    def test_only_last_messages_are_kept(self):
        history = self.history(limit=4)
        for n in range(6):
            history.append(self.user, [("user", f"u{n}")])
        self.assertEqual([i["content"] for i in history.get(self.user)], ["u2", "u3", "u4", "u5"])

    def test_users_are_isolated(self):
        history = self.history()
        history.append(self.user, [("user", "секрет")])
        self.assertEqual(history.get(self.user + "-other"), [])

    def test_ttl_is_set_and_refreshed_by_writes(self):
        history = self.history(ttl=120)
        history.append(self.user, [("user", "a")])
        keys = list(self.client.scan_iter(self.prefix + "*messages"))
        self.assertEqual(len(keys), 1)
        self.assertTrue(0 < self.client.ttl(keys[0]) <= 120)

    def test_idempotent_reply_is_stored(self):
        history = self.history()
        key = "message:" + uuid.uuid4().hex
        self.assertIsNone(history.get_reply(key))
        history.put_reply(key, "готово")
        self.assertEqual(history.get_reply(key), "готово")

    def test_unreachable_redis_is_error_not_empty_context(self):
        from app.history import HistoryError

        broken = ChatHistory(Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2),
                             prefix=self.prefix, limit=10, ttl_seconds=900, idempotency_ttl_seconds=60)
        with self.assertRaises(HistoryError):
            broken.get(self.user)
        self.assertFalse(broken.ping())


if __name__ == "__main__":
    unittest.main()
