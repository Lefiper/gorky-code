"""API-хранилище без HTTP-маршрутов; изменения/удаления только вымышленных событий."""

from dataclasses import replace
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

import psycopg

from app.api_storage import APIEventService, local_datetime_to_iso
from app.config import Settings
from app.db.connection import connect
from app.events import ConflictError, ValidationError


class APIValidationTests(unittest.TestCase):
    def setUp(self):
        self.service = APIEventService(Settings("localhost", 5432, "unused", "unused", "unused"))

    def test_invalid_duration_status_id_and_timezone_never_connect(self):
        with patch("app.events.connect") as connection:
            for duration in (0, -1, True, "60", 1.5, 2147483648):
                with self.subTest(duration=duration), self.assertRaises(ValidationError):
                    self.service.create_event("fake", "project", "Test", "2030-01-01T10:00:00Z", duration_minutes=duration)
            with self.assertRaises(ValidationError):
                self.service.update_event_status("fake", str(uuid4()), "unknown")
            for event_id in (1, True, "123", "not-a-uuid"):
                with self.subTest(event_id=event_id), self.assertRaises(ValidationError):
                    self.service.delete_event("fake", event_id)
            with self.assertRaises(ValidationError):
                self.service.set_user_timezone("fake", "Mars/Olympus")
            connection.assert_not_called()

    def test_local_date_time_and_dst(self):
        self.assertEqual(local_datetime_to_iso("2030-01-02", "15:30", "Europe/Moscow"), "2030-01-02T12:30:00Z")
        for date, time, zone in (("2030-02-30", "15:30", "Europe/Moscow"),
                                 ("2030-01-02", "25:30", "Europe/Moscow"),
                                 ("2030-01-02", "15:30+03:00", "Europe/Moscow"),
                                 ("2026-03-29", "02:30", "Europe/Berlin"),
                                 ("2026-10-25", "02:30", "Europe/Berlin")):
            with self.subTest(date=date, time=time), self.assertRaises(ValidationError):
                local_datetime_to_iso(date, time, zone)


@unittest.skipUnless(os.environ.get("STACK_MCP_URL") and os.environ.get("API_DB_PASSWORD"), "Требуется Docker-роль assistant_api")
class APIStorageTests(unittest.TestCase):
    def setUp(self):
        self.settings = replace(Settings.load(), user="assistant_api", password=os.environ["API_DB_PASSWORD"])
        self.service = APIEventService(self.settings)
        self.user = "test:api:" + uuid4().hex

    def test_project_duration_and_all_ui_statuses(self):
        created = self.service.create_event(self.user, "project", "Вымышленный проект", "2035-01-02T10:00:00Z", duration_minutes=90, idempotency_key="same")
        event = created["event"]
        self.assertEqual(event["duration_minutes"], 90)
        self.assertEqual(event["status"], "new")
        repeated = self.service.create_event(self.user, "project", "Вымышленный проект", "2035-01-02T10:00:00Z", duration_minutes=90, idempotency_key="same")
        self.assertFalse(repeated["created"])
        with self.assertRaises(ConflictError):
            self.service.create_event(self.user, "project", "Вымышленный проект", "2035-01-02T10:00:00Z", duration_minutes=60, idempotency_key="same")
        for status in ("progress", "blocked", "done", "new", "cancelled", "pending"):
            self.assertEqual(self.service.update_event_status(self.user, event["id"], status)["status"], status)
        page = self.service.get_event(self.user, "2035-01-02T00:00:00Z", "2035-01-03T00:00:00Z", event_type="project")
        self.assertEqual(page["items"][0]["duration_minutes"], 90)
        self.assertEqual(self.service.get_event_by_query(self.user, "вымышленный проект")["items"][0]["id"], event["id"])

    def test_update_delete_user_isolation_and_missing_ids(self):
        event = self.service.create_event(self.user, "task", "Тест удаления", "2035-01-02T10:00:00Z")["event"]
        other = "test:api:other:" + uuid4().hex
        self.assertIsNone(self.service.update_event_status(other, event["id"], "done"))
        self.assertFalse(self.service.delete_event(other, event["id"]))
        self.assertEqual(self.service.update_event_status(self.user, event["id"], "done")["status"], "done")
        self.assertTrue(self.service.delete_event(self.user, event["id"]))
        self.assertFalse(self.service.delete_event(self.user, event["id"]))
        self.assertIsNone(self.service.update_event_status(self.user, event["id"], "new"))

    def test_shared_timezone_upsert_and_resolution(self):
        self.assertIsNone(self.service.get_user_timezone(self.user))
        with self.assertRaises(ValidationError):
            self.service.resolve_local_datetime(self.user, "2035-01-02", "10:00")
        self.service.set_user_timezone(self.user, "Europe/Moscow")
        self.assertEqual(self.service.resolve_local_datetime(self.user, "2035-01-02", "10:00"), "2035-01-02T07:00:00Z")
        self.service.set_user_timezone(self.user, "Asia/Yekaterinburg")
        another_process_service = APIEventService(self.settings)
        self.assertEqual(another_process_service.get_user_timezone(self.user), "Asia/Yekaterinburg")
        self.assertIsNone(self.service.get_user_timezone("test:missing:" + uuid4().hex))

    def test_database_timezone_validation_even_for_direct_sql(self):
        with self.assertRaises(psycopg.errors.CheckViolation):
            with connect(self.settings) as conn:
                conn.execute("INSERT INTO public.user_profiles (user_id, timezone) VALUES (%s, %s)", (self.user, "Mars/Olympus"))

    def test_api_cannot_change_ownership_or_migrate_schema(self):
        for query in ("UPDATE public.events SET user_id='other' WHERE false",
                      "CREATE TABLE public.api_should_not_create (id int)",
                      "SELECT * FROM public.schema_migrations"):
            with self.subTest(query=query), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                with connect(self.settings) as conn:
                    conn.execute(query)

    def test_mcp_role_still_cannot_patch_or_delete(self):
        settings = replace(Settings.load(), user="assistant_app", password=os.environ["APP_DB_PASSWORD"])
        for query in ("UPDATE public.events SET status='done' WHERE false", "DELETE FROM public.events WHERE false"):
            with self.subTest(query=query), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                with connect(settings) as conn:
                    conn.execute(query)


if __name__ == "__main__":
    unittest.main()
