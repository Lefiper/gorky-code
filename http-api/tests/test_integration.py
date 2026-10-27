from __future__ import annotations

import os
import unittest
from uuid import uuid4

from app.errors import ConflictError, NotFoundError
from app.storage import EventRepository, PgConfig

RUN_DB_TESTS = os.environ.get("ASSISTANT_RUN_DB_TESTS") == "1"


@unittest.skipUnless(
    RUN_DB_TESTS,
    "set ASSISTANT_RUN_DB_TESTS=1 to run PostgreSQL integration tests",
)
class EventRepositoryIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        password = os.environ.get("PGPASSWORD", "")
        if not password:
            raise unittest.SkipTest("PGPASSWORD is not set")

        cls.repo = EventRepository(
            PgConfig(
                host=os.environ.get("PGHOST", "127.0.0.1"),
                port=int(os.environ.get("PGPORT", "55432")),
                dbname=os.environ.get("PGDATABASE", "assistant_mvp"),
                user=os.environ.get("PGUSER", "assistant_app"),
                password=password,
                connect_timeout=5,
            )
        )
        try:
            cls.repo.open()
            cls.repo.ping()
        except Exception as exc:
            cls.repo.close()
            raise unittest.SkipTest(f"PostgreSQL is unavailable: {exc}") from exc

        cls.user_id = f"test:api:{uuid4()}"
        cls.other_user_id = f"test:api:{uuid4()}"
        cls.event_name = f"API integration {uuid4()}"
        cls.search_word = f"integration{uuid4().hex[:8]}"
        cls.event_at = "2030-01-02T15:00:00+03:00"
        cls.created = cls.repo.create_event(
            user_id=cls.user_id,
            event_type="task",
            name=cls.event_name,
            event_at=cls.event_at,
            description=f"Описание {cls.search_word}",
            idempotency_key="integration-key",
        )
        cls.event_id = cls.created["event"]["id"]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repo.close()

    def test_created(self) -> None:
        self.assertTrue(self.created["created"])
        self.assertEqual(self.created["event"]["event_at"], "2030-01-02T12:00:00Z")
        self.assertEqual(self.created["event"]["status"], "pending")

    def test_list(self) -> None:
        result = self.repo.list_events(
            self.user_id,
            "2030-01-02T00:00:00+03:00",
            "2030-01-03T00:00:00+03:00",
        )
        ids = [item["id"] for item in result["items"]]
        self.assertIn(self.event_id, ids)

    def test_list_filters_other_type(self) -> None:
        result = self.repo.list_events(
            self.user_id,
            "2030-01-02T00:00:00+03:00",
            "2030-01-03T00:00:00+03:00",
            event_types=["meeting"],
        )
        ids = [item["id"] for item in result["items"]]
        self.assertNotIn(self.event_id, ids)

    def test_get(self) -> None:
        event = self.repo.get_event_by_id(self.user_id, self.event_id)
        self.assertEqual(event["name"], self.event_name)

    def test_get_isolates_users(self) -> None:
        with self.assertRaises(NotFoundError):
            self.repo.get_event_by_id(self.other_user_id, self.event_id)

    def test_search(self) -> None:
        result = self.repo.search_events(self.user_id, self.search_word)
        ids = [item["id"] for item in result["items"]]
        self.assertIn(self.event_id, ids)

    def test_idempotent_replay(self) -> None:
        replay = self.repo.create_event(
            user_id=self.user_id,
            event_type="task",
            name=self.event_name,
            event_at=self.event_at,
            description=f"Описание {self.search_word}",
            idempotency_key="integration-key",
        )
        self.assertFalse(replay["created"])
        self.assertEqual(replay["event"]["id"], self.event_id)

    def test_idempotency_conflict(self) -> None:
        with self.assertRaises(ConflictError):
            self.repo.create_event(
                user_id=self.user_id,
                event_type="task",
                name=self.event_name + " другое",
                event_at=self.event_at,
                description=f"Описание {self.search_word}",
                idempotency_key="integration-key",
            )
