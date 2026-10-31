"""Real PostgreSQL: durable retries, minimal-role grants and user isolation."""
import os
import unittest
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from app.config import Settings
from app.events import EventService, ValidationError, ConflictError

@unittest.skipUnless(os.environ.get("ASSISTANT_RUN_DB_TESTS") == "1", "Requires PostgreSQL")
class MutationTests(unittest.TestCase):
    def setUp(self):
        self.service = EventService(Settings.load())
        self.user = "test:mutation:" + uuid4().hex
        self.created = self.service.create_event(self.user, "reminder", "Проверка", "2035-01-02T15:00:00+03:00", idempotency_key="create")
        self.eid = self.created["event"]["id"]

    def test_delete_retry_after_commit_and_restart(self):
        first = self.service.delete_event(self.user, self.eid, "delete-once")
        restarted = EventService(Settings.load())
        second = restarted.delete_event(self.user, self.eid, "delete-once")
        self.assertEqual(first, second)
        self.assertTrue(second["deleted"])
        with self.assertRaises(ValidationError):
            restarted.delete_event(self.user + "other", self.eid, "delete-once")

    def test_move_retry_does_not_add_another_week(self):
        first = self.service.update_event_time(self.user,self.eid,"2035-01-09T15:00:00+03:00","move-once")
        second = self.service.update_event_time(self.user,self.eid,"2035-01-09T15:00:00+03:00","move-once")
        self.assertEqual(first,second)
        self.assertEqual(first["event"]["event_at"],"2035-01-09T12:00:00Z")
        with self.assertRaises(ConflictError):
            self.service.update_event_time(self.user,self.eid,"2035-01-10T15:00:00+03:00","move-once")

    def test_other_user_cannot_move(self):
        with self.assertRaises(ValidationError):
            self.service.update_event_time(self.user+'other',self.eid,"2035-01-09T15:00:00+03:00","move")

    def test_identical_create_with_different_messages_is_merged(self):
        def create(n):
            return self.service.create_event(self.user,"reminder","Проверка","2035-01-02T15:00:00+03:00",idempotency_key=f"repeat-{n}")
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(create,range(8)))
        self.assertEqual({r["event"]["id"] for r in results},{self.eid})
        self.assertTrue(all(not r["created"] for r in results))

    def test_sent_reminder_becomes_pending_and_can_send_again(self):
        with self.service._connection() as conn:
            conn.execute("UPDATE events SET status='done' WHERE id=%s",(self.eid,))
            conn.execute("INSERT INTO reminder_deliveries(event_id,state) VALUES (%s,'sent')",(self.eid,))
        moved=self.service.update_event_time(self.user,self.eid,"2035-01-09T15:00:00+03:00","move")
        self.assertEqual(moved["event"]["status"],"pending")
        with self.service._connection() as conn:
            self.assertIsNone(conn.execute("SELECT state FROM reminder_deliveries WHERE event_id=%s",(self.eid,)).fetchone())

    def test_inflight_reminder_cannot_be_rescheduled(self):
        with self.service._connection() as conn:
            conn.execute("INSERT INTO reminder_deliveries(event_id,state) VALUES (%s,'inflight')",(self.eid,))
        with self.assertRaises(ConflictError):
            self.service.update_event_time(self.user,self.eid,"2035-01-09T15:00:00+03:00","move")

    def test_minimal_mcp_role_can_delete_and_move(self):
        settings=replace(Settings.load(),user="assistant_app",password=os.environ["APP_DB_PASSWORD"])
        app=EventService(settings)
        app.update_event_time(self.user,self.eid,"2035-01-09T15:00:00+03:00","role-move")
        self.assertTrue(app.delete_event(self.user,self.eid,"role-delete")["deleted"])
