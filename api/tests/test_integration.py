from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime
from uuid import uuid4

from app.config import Settings
from app.errors import ConflictError, NotFoundError, ValidationError
from app.storage import EventRepository


class IntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if os.environ.get("ASSISTANT_RUN_DB_TESTS") != "1":
            raise unittest.SkipTest("ASSISTANT_RUN_DB_TESTS != 1")
        password = os.environ.get("API_DB_PASSWORD") or os.environ.get("PGPASSWORD")
        if not password:
            raise unittest.SkipTest("API_DB_PASSWORD/PGPASSWORD is not set")
        port = int(os.environ.get("PGPORT", "55432"))
        settings = Settings(
            app_env="test",
            api_prefix="/api",
            pg_host=os.environ.get("PGHOST", "127.0.0.1"),
            pg_port=port,
            pg_database=os.environ.get("PGDATABASE", "assistant_mvp"),
            pg_user=os.environ.get("PGUSER", "assistant_api"),
            pg_password=password,
            pg_connect_timeout=5,
            max_bot_token="test-bot-token",
            auth_dev_mode=False,
        )
        cls.settings = settings
        cls.repo = EventRepository(settings.pg_config())
        try:
            cls.repo.open()
            cls.repo.ping()
        except Exception as exc:  # pragma: no cover - environment dependent
            cls.repo.close()
            raise unittest.SkipTest(f"PostgreSQL недоступен: {exc}") from exc
        cls.user_id = f"test:api:{uuid4()}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repo.close()

    def test_create_and_get(self) -> None:
        created = self.repo.create_event(
            self.user_id,
            "project",
            "Интеграционный проект",
            "2030-01-02T10:00:00+03:00",
            description="Описание",
            duration_minutes=90,
            status="new",
            idempotency_key="integration-key",
        )
        self.assertTrue(created["created"])
        event = created["event"]
        self.assertEqual(event["event_type"], "project")
        self.assertEqual(event["duration_minutes"], 90)
        self.assertEqual(event["status"], "new")
        self.assertEqual(event["event_at"], "2030-01-02T07:00:00Z")

        fetched = self.repo.get_event_by_id(self.user_id, event["id"])
        self.assertEqual(fetched["id"], event["id"])
        self.assertEqual(fetched["duration_minutes"], 90)

    def test_idempotent_replay(self) -> None:
        created = self.repo.create_event(
            self.user_id,
            "task",
            "Идемпотентная задача",
            "2030-01-02T10:00:00+03:00",
            idempotency_key="idempotent-key",
        )
        self.assertTrue(created["created"])
        repeated = self.repo.create_event(
            self.user_id,
            "task",
            "Идемпотентная задача",
            "2030-01-02T10:00:00+03:00",
            idempotency_key="idempotent-key",
        )
        self.assertFalse(repeated["created"])
        self.assertEqual(repeated["event"]["id"], created["event"]["id"])

    def test_idempotency_conflict(self) -> None:
        self.repo.create_event(
            self.user_id,
            "task",
            "Первая",
            "2030-01-02T10:00:00+03:00",
            idempotency_key="conflict-key",
        )
        with self.assertRaises(ConflictError):
            self.repo.create_event(
                self.user_id,
                "task",
                "Вторая",
                "2030-01-02T10:00:00+03:00",
                idempotency_key="conflict-key",
            )

    def test_list_filters_type_and_period(self) -> None:
        self.repo.create_event(self.user_id, "meeting", "Встреча", "2030-01-02T10:00:00+03:00")
        page = self.repo.list_events(
            self.user_id,
            datetime(2030, 1, 1, 21, 0, tzinfo=UTC),
            datetime(2030, 1, 2, 21, 0, tzinfo=UTC),
            event_types=["meeting"],
        )
        self.assertTrue(any(item["event_type"] == "meeting" for item in page["items"]))
        self.assertFalse(any(item["event_type"] == "task" for item in page["items"]))

    def test_search(self) -> None:
        self.repo.create_event(self.user_id, "task", "УникальноеСлово", "2030-01-02T10:00:00+03:00")
        page = self.repo.search_events(self.user_id, "УникальноеСлово")
        self.assertTrue(page["items"])

    def test_update_status_and_delete(self) -> None:
        created = self.repo.create_event(self.user_id, "task", "Удалить", "2030-01-02T10:00:00+03:00")
        event_id = created["event"]["id"]
        updated = self.repo.update_event_status(self.user_id, event_id, "done")
        self.assertEqual(updated["status"], "done")
        self.assertTrue(self.repo.delete_event(self.user_id, event_id))
        self.assertFalse(self.repo.delete_event(self.user_id, event_id))
        self.assertIsNone(self.repo.update_event_status(self.user_id, event_id, "new"))

    def test_user_isolation(self) -> None:
        created = self.repo.create_event(self.user_id, "task", "Чужая задача", "2030-01-02T10:00:00+03:00")
        other = f"test:api:other:{uuid4()}"
        with self.assertRaises(NotFoundError):
            self.repo.get_event_by_id(other, created["event"]["id"])
        self.assertFalse(self.repo.delete_event(other, created["event"]["id"]))

    def test_timezone_profile(self) -> None:
        self.assertIsNone(self.repo.get_user_timezone(self.user_id))
        self.assertEqual(self.repo.resolve_local_datetime(self.user_id, "2030-01-02", "10:00"), "2030-01-02T07:00:00Z")
        self.repo.set_user_timezone(self.user_id, "Europe/Moscow")
        self.assertEqual(self.repo.resolve_local_datetime(self.user_id, "2030-01-02", "10:00"), "2030-01-02T07:00:00Z")
        self.repo.set_user_timezone(self.user_id, "Asia/Yekaterinburg")
        other_service = EventRepository(self.settings.pg_config())
        other_service.open()
        try:
            self.assertEqual(other_service.get_user_timezone(self.user_id), "Asia/Yekaterinburg")
        finally:
            other_service.close()
        self.assertIsNone(self.repo.get_user_timezone(f"test:missing:{uuid4()}"))


if __name__ == "__main__":
    unittest.main()
