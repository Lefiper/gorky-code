"""Реальная БД: opt-in ASSISTANT_RUN_DB_TESTS=1. Только вымышленные записи.

Записи намеренно остаются в БД: DELETE/DROP/TRUNCATE не выполняются.
Каждый запуск использует новые изолированные user_id с префиксом test:.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os
import subprocess
import sys
import unittest
from uuid import uuid4

from app.config import Settings
from app.events import ConflictError, EventService, StorageError


@unittest.skipUnless(os.environ.get("ASSISTANT_RUN_DB_TESTS") == "1", "Требуется явное включение интеграционных тестов")
class PostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = EventService(Settings.load())
        cls.user = "test:" + str(uuid4())
        cls.other = "test:" + str(uuid4())
        cls.start = "2030-01-02T00:00:00+03:00"
        cls.end = "2030-01-03T00:00:00+03:00"
        cls.task = cls.service.create_event(cls.user, "task", "Презентация проекта", "2030-01-02T10:00:00+03:00", "Подготовить материалы для команды", "task")
        cls.meeting = cls.service.create_event(cls.user, "meeting", "Обсуждение", "2030-01-02T15:00:00+03:00", "Встреча по разработке календаря", "meeting")
        cls.service.create_event(cls.other, "task", "Презентация проекта", "2030-01-02T10:00:00+03:00", idempotency_key="task")
        cls.service.create_event(cls.user, "reminder", "Граница дня", cls.end)

    def test_create_types_and_utc(self):
        self.assertTrue(self.task["created"])
        self.assertEqual(self.task["event"]["event_type"], "task")
        self.assertEqual(self.meeting["event"]["event_type"], "meeting")
        self.assertEqual(self.task["event"]["event_at"], "2030-01-02T07:00:00Z")

    def test_period_isolation_and_half_open_boundary(self):
        page = self.service.get_event(self.user, self.start, self.end)
        self.assertEqual([e["id"] for e in page["items"]], [self.task["event"]["id"], self.meeting["event"]["id"]])
        self.assertFalse(page["has_more"])
        self.assertTrue(all(e["user_id"] == self.user for e in page["items"]))
        self.assertEqual(len(self.service.get_event(self.user, self.start, self.end, event_type="meeting")["items"]), 1)

    def test_empty_period(self):
        self.assertEqual(self.service.get_event(self.user, "2040-01-01T00:00:00Z", "2040-01-02T00:00:00Z"), {"items": [], "has_more": False})

    def test_russian_name_description_and_missing_query(self):
        for text, expected in [("презентации", self.task), ("разработка календаря", self.meeting)]:
            with self.subTest(text=text):
                items = self.service.get_event_by_query(self.user, text)["items"]
                self.assertEqual([row["id"] for row in items], [expected["event"]["id"]])
        for text in ("несуществующий жираф", "и в на", "' OR 1=1 --"):
            self.assertEqual(self.service.get_event_by_query(self.user, text)["items"], [])

    def test_optional_search_bounds(self):
        self.assertEqual(self.service.get_event_by_query(self.user, "презентация", start_time=self.end)["items"], [])
        self.assertEqual(self.service.get_event_by_query(self.user, "презентация", end_time=self.start)["items"], [])

    def test_pagination(self):
        first = self.service.get_event(self.user, self.start, self.end, limit=1)
        second = self.service.get_event(self.user, self.start, self.end, limit=1, offset=1)
        self.assertTrue(first["has_more"])
        self.assertFalse(second["has_more"])
        self.assertNotEqual(first["items"][0]["id"], second["items"][0]["id"])

    def test_idempotency_and_conflict_rollback(self):
        repeated = self.service.create_event(self.user, "task", "Презентация проекта", "2030-01-02T07:00:00Z", "Подготовить материалы для команды", "task")
        self.assertFalse(repeated["created"])
        self.assertEqual(repeated["event"], self.task["event"])
        with self.assertRaises(ConflictError):
            self.service.create_event(self.user, "task", "Другая задача", self.start, idempotency_key="task")
        self.assertEqual(self.service.get_event_by_query(self.user, "презентация")["items"][0], self.task["event"])

    def test_concurrent_idempotency(self):
        user = "test:" + str(uuid4())
        def create(_):
            return self.service.create_event(user, "task", "Параллельная проверка", self.start, idempotency_key="same")
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(create, range(4)))
        self.assertEqual(sum(r["created"] for r in results), 1)
        self.assertEqual(len({r["event"]["id"] for r in results}), 1)

    def test_no_key_allows_distinct_operations(self):
        user = "test:" + str(uuid4())
        one = self.service.create_event(user, "reminder", "Проверка", self.start)
        two = self.service.create_event(user, "reminder", "Проверка", self.start)
        self.assertNotEqual(one["event"]["id"], two["event"]["id"])

    def test_persists_in_new_python_process(self):
        code = "from app.config import Settings; from app.events import EventService; import sys,json; print(json.dumps(EventService(Settings.load()).get_event(sys.argv[1],sys.argv[2],sys.argv[3])))"
        result = subprocess.run([sys.executable, "-c", code, self.user, self.start, self.end], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, "Чтение из отдельного процесса не удалось; stderr скрыт для защиты настроек")
        self.assertEqual(json.loads(result.stdout)["items"][0]["id"], self.task["event"]["id"])

    def test_connection_failure_is_safe(self):
        broken = EventService(replace(self.service.settings, host="127.0.0.1", port=1, connect_timeout=1))
        with self.assertRaises(StorageError) as error:
            broken.get_event(self.user, self.start, self.end)
        self.assertNotIn(self.service.settings.password, str(error.exception))


if __name__ == "__main__":
    unittest.main()
