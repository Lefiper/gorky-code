from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import Mock

from fastapi.testclient import TestClient

from app.errors import NotFoundError, StorageError
from app.main import create_app
from tests.helpers import USER_ID, event_payload, make_init_data, make_settings


class ApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Mock()
        self.repo.list_events.return_value = {"items": [], "has_more": False}
        self.repo.search_events.return_value = {"items": [], "has_more": False}
        self.repo.get_event_by_id.return_value = event_payload()
        self.repo.create_event.return_value = {"event": event_payload(), "created": True}

        self.settings = make_settings()
        self.app = create_app(settings=self.settings, repository=self.repo)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.headers = {"X-Max-InitData": make_init_data()}

    def test_me(self) -> None:
        response = self.client.get("/api/v1/me", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(USER_ID))
        self.assertEqual(response.json()["first_name"], "Test")

    def test_me_requires_auth(self) -> None:
        response = self.client.get("/api/v1/me")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["www-authenticate"], "MaxInitData")

    def test_me_accepts_bearer(self) -> None:
        response = self.client.get(
            "/api/v1/me",
            headers={"Authorization": f"Bearer {make_init_data()}"},
        )
        self.assertEqual(response.status_code, 200)

    def test_me_rejects_bad_signature(self) -> None:
        response = self.client.get(
            "/api/v1/me",
            headers={"X-Max-InitData": make_init_data(hash_override="deadbeef")},
        )
        self.assertEqual(response.status_code, 401)

    def test_dev_mode(self) -> None:
        settings = make_settings(
            app_env="development",
            auth_dev_mode=True,
            max_bot_token="",
        )
        app = create_app(settings=settings, repository=self.repo)
        with TestClient(app) as client:
            response = client.get("/api/v1/me", headers={"X-Debug-User-Id": "dev:42"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["id"], "dev:42")

            response = client.get("/api/v1/me")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["id"], "dev:1")

    def test_dev_mode_forbidden_in_production(self) -> None:
        with self.assertRaises(ValueError):
            make_settings(app_env="production", auth_dev_mode=True, max_bot_token="")

    def test_list_by_date_moscow(self) -> None:
        response = self.client.get(
            "/api/v1/events",
            params={"date": "2026-10-24", "timezone": "Europe/Moscow"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.repo.list_events.call_args.kwargs
        self.assertEqual(kwargs["user_id"], str(USER_ID))
        self.assertEqual(
            kwargs["start_time"], datetime(2026, 10, 23, 21, 0, tzinfo=UTC)
        )
        self.assertEqual(
            kwargs["end_time"], datetime(2026, 10, 24, 21, 0, tzinfo=UTC)
        )

    def test_list_by_period_and_types(self) -> None:
        response = self.client.get(
            "/api/v1/events",
            params=[
                ("from", "2026-10-24T00:00:00+03:00"),
                ("to", "2026-10-25T00:00:00+03:00"),
                ("event_type", "task"),
                ("event_type", "meeting"),
            ],
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.repo.list_events.call_args.kwargs
        self.assertEqual(
            kwargs["start_time"], datetime(2026, 10, 23, 21, 0, tzinfo=UTC)
        )
        self.assertEqual(
            kwargs["end_time"], datetime(2026, 10, 24, 21, 0, tzinfo=UTC)
        )
        self.assertEqual(kwargs["event_types"], ["task", "meeting"])

    def test_list_requires_period(self) -> None:
        response = self.client.get("/api/v1/events", headers=self.headers)
        self.assertEqual(response.status_code, 422)
        self.assertIn("date", response.json()["detail"])

    def test_list_rejects_date_and_period(self) -> None:
        response = self.client.get(
            "/api/v1/events",
            params={"date": "2026-10-24", "from": "2026-10-24T00:00:00+03:00"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 422)

    def test_list_rejects_naive_period(self) -> None:
        response = self.client.get(
            "/api/v1/events",
            params={"from": "2026-10-24T00:00:00", "to": "2026-10-25T00:00:00"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("часовое смещение", response.json()["detail"])

    def test_list_rejects_unknown_type(self) -> None:
        response = self.client.get(
            "/api/v1/events",
            params={"date": "2026-10-24", "event_type": "project"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("errors", response.json())

    def test_search(self) -> None:
        response = self.client.get(
            "/api/v1/events/search",
            params={"q": "тест", "from": "2026-10-01T00:00:00+03:00"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.repo.search_events.call_args.kwargs
        self.assertEqual(kwargs["text"], "тест")
        self.assertEqual(
            kwargs["start_time"], datetime(2026, 9, 30, 21, 0, tzinfo=UTC)
        )
        self.assertIsNone(kwargs["end_time"])

    def test_get_event(self) -> None:
        payload = event_payload()
        self.repo.get_event_by_id.return_value = payload
        response = self.client.get(f"/api/v1/events/{payload['id']}", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], payload["id"])
        self.assertEqual(body["event_at"], "2026-10-24T09:00:00Z")
        self.assertEqual(body["status"], "pending")

    def test_get_event_not_found(self) -> None:
        self.repo.get_event_by_id.side_effect = NotFoundError()
        response = self.client.get(
            "/api/v1/events/00000000-0000-0000-0000-000000000000",
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Событие не найдено.")

    def test_get_event_invalid_uuid(self) -> None:
        response = self.client.get("/api/v1/events/not-a-uuid", headers=self.headers)
        self.assertEqual(response.status_code, 422)
        self.assertIn("errors", response.json())

    def test_create_event(self) -> None:
        payload = {
            "event_type": "meeting",
            "name": "  Демо  ",
            "description": "  ",
            "event_at": "2026-10-27T15:00:00+03:00",
        }
        response = self.client.post(
            "/api/v1/events",
            json=payload,
            headers={**self.headers, "Idempotency-Key": "demo-1"},
        )
        self.assertEqual(response.status_code, 201)
        kwargs = self.repo.create_event.call_args.kwargs
        self.assertEqual(kwargs["user_id"], str(USER_ID))
        self.assertEqual(kwargs["event_type"], "meeting")
        self.assertEqual(kwargs["name"], "Демо")
        self.assertEqual(kwargs["description"], "")
        self.assertEqual(
            kwargs["event_at"], datetime.fromisoformat("2026-10-27T15:00:00+03:00")
        )
        self.assertEqual(kwargs["idempotency_key"], "demo-1")

    def test_create_event_idempotent_replay_returns_200(self) -> None:
        self.repo.create_event.return_value = {"event": event_payload(), "created": False}
        response = self.client.post(
            "/api/v1/events",
            json={
                "event_type": "task",
                "name": "Задача",
                "event_at": "2026-10-27T15:00:00+03:00",
            },
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["created"])

    def test_create_event_rejects_user_id(self) -> None:
        response = self.client.post(
            "/api/v1/events",
            json={
                "event_type": "task",
                "name": "Задача",
                "event_at": "2026-10-27T15:00:00+03:00",
                "user_id": "999",
            },
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("errors", response.json())

    def test_create_event_rejects_naive_datetime(self) -> None:
        response = self.client.post(
            "/api/v1/events",
            json={
                "event_type": "task",
                "name": "Задача",
                "event_at": "2026-10-27T15:00:00",
            },
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("errors", response.json())

    def test_create_event_rejects_project_type(self) -> None:
        response = self.client.post(
            "/api/v1/events",
            json={
                "event_type": "project",
                "name": "Проект",
                "event_at": "2026-10-27T15:00:00+03:00",
            },
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 422)

    def test_health(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_health_unavailable(self) -> None:
        self.repo.ping.side_effect = StorageError()
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})

    def test_cors_preflight(self) -> None:
        response = self.client.options(
            "/api/v1/events",
            headers={
                "Origin": "https://htmlpreview.github.io",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-Max-InitData",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "*")
        self.assertIn(
            "x-max-initdata",
            response.headers["access-control-allow-headers"].lower(),
        )
