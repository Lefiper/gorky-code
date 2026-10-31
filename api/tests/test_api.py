from __future__ import annotations

import unittest
from unittest.mock import Mock
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import create_app
from tests.helpers import USER_ID, event_payload, make_init_data, make_settings


def task_payload(**overrides) -> dict:
    payload = {
        "event_type": "task",
        "name": "Тестовая задача",
        "description": "Описание",
        "event_at": "2026-10-24T09:00:00Z",
        "duration_minutes": 30,
        "status": "new",
    }
    payload.update(overrides)
    return payload


class FakeRepository:
    def __init__(self) -> None:
        self.ping = Mock()
        self.list_events = Mock(return_value={"items": [], "has_more": False})
        self.search_events = Mock(return_value={"items": [], "has_more": False})
        self.get_event_by_id = Mock()
        self.create_event = Mock()
        self.update_event_status = Mock()
        self.delete_event = Mock(return_value=True)
        self.get_user_timezone = Mock(return_value=None)
        self.set_user_timezone = Mock(return_value={"user_id": str(USER_ID), "timezone": "Europe/Moscow"})
        self.resolve_local_datetime = Mock(return_value="2026-10-24T06:00:00Z")
        self.open = Mock()
        self.close = Mock()


class ApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = FakeRepository()
        self.settings = make_settings()
        self.app = create_app(settings=self.settings, repository=self.repo)
        self.client = TestClient(self.app)
        self.headers = {"X-Max-InitData": make_init_data()}

    def test_timezone_put_cors_preflight(self) -> None:
        response = self.client.options("/api/timezone", headers={
            "Origin": "http://localhost:8080", "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type,x-max-initdata"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("PUT", response.headers["access-control-allow-methods"])

    def test_health(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.repo.ping.assert_called_once()

    def test_health_unavailable(self) -> None:
        self.repo.ping.side_effect = Exception("boom")
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})

    def test_me(self) -> None:
        response = self.client.get("/api/me", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(USER_ID))

    def test_me_requires_auth(self) -> None:
        response = self.client.get("/api/me")
        self.assertEqual(response.status_code, 401)

    def test_list_by_date(self) -> None:
        response = self.client.get(
            "/api/tasks",
            params={"date": "2026-10-24", "timezone": "Europe/Moscow"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.repo.list_events.assert_called_once()
        kwargs = self.repo.list_events.call_args.kwargs
        self.assertEqual(kwargs["user_id"], str(USER_ID))
        self.assertEqual(kwargs["limit"], 100)
        self.assertEqual(kwargs["offset"], 0)

    def test_list_by_period(self) -> None:
        response = self.client.get(
            "/api/tasks",
            params={"from": "2026-10-24T00:00:00+03:00", "to": "2026-10-25T00:00:00+03:00"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)

    def test_list_rejects_naive_period(self) -> None:
        response = self.client.get(
            "/api/tasks",
            params={"from": "2026-10-24T00:00:00", "to": "2026-10-25T00:00:00+03:00"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 422)

    def test_list_filters_event_type(self) -> None:
        response = self.client.get(
            "/api/tasks",
            params={"date": "2026-10-24", "timezone": "Europe/Moscow", "event_type": ["task", "project"]},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.repo.list_events.call_args.kwargs
        self.assertEqual(kwargs["event_types"], ["task", "project"])

    def test_search(self) -> None:
        response = self.client.get("/api/tasks/search", params={"q": "созвон"}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.repo.search_events.assert_called_once()

    def test_get_event(self) -> None:
        event_id = str(uuid4())
        self.repo.get_event_by_id.return_value = event_payload(id=event_id, user_id=str(USER_ID))
        response = self.client.get(f"/api/tasks/{event_id}", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], event_id)

    def test_get_event_not_found(self) -> None:
        from app.errors import NotFoundError
        self.repo.get_event_by_id.side_effect = NotFoundError()
        response = self.client.get(f"/api/tasks/{uuid4()}", headers=self.headers)
        self.assertEqual(response.status_code, 404)

    def test_get_event_invalid_uuid(self) -> None:
        response = self.client.get("/api/tasks/not-a-uuid", headers=self.headers)
        self.assertEqual(response.status_code, 422)

    def test_create_event(self) -> None:
        self.repo.create_event.return_value = {
            "event": event_payload(id=str(uuid4()), user_id=str(USER_ID), duration_minutes=30, status="new"),
            "created": True,
        }
        response = self.client.post("/api/tasks", json=task_payload(), headers=self.headers)
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["created"])
        kwargs = self.repo.create_event.call_args.kwargs
        self.assertEqual(kwargs["user_id"], str(USER_ID))
        self.assertEqual(kwargs["event_type"], "task")
        self.assertEqual(kwargs["name"], "Тестовая задача")
        self.assertEqual(kwargs["duration_minutes"], 30)
        self.assertEqual(kwargs["status"], "new")

    def test_create_event_idempotent_replay_returns_200(self) -> None:
        self.repo.create_event.return_value = {
            "event": event_payload(id=str(uuid4()), user_id=str(USER_ID)),
            "created": False,
        }
        response = self.client.post(
            "/api/tasks",
            json=task_payload(),
            headers={**self.headers, "Idempotency-Key": "same-key"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["created"])

    def test_create_event_rejects_user_id(self) -> None:
        response = self.client.post(
            "/api/tasks",
            json={**task_payload(), "user_id": "evil"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 422)

    def test_create_event_rejects_invalid_type(self) -> None:
        response = self.client.post(
            "/api/tasks",
            json=task_payload(event_type="invalid"),
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 422)

    def test_create_event_rejects_naive_datetime(self) -> None:
        response = self.client.post(
            "/api/tasks",
            json=task_payload(event_at="2026-10-24T09:00:00"),
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 422)

    def test_create_event_rejects_bad_duration(self) -> None:
        response = self.client.post(
            "/api/tasks",
            json=task_payload(duration_minutes=0),
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 422)

    def test_update_status(self) -> None:
        event_id = str(uuid4())
        self.repo.update_event_status.return_value = event_payload(id=event_id, user_id=str(USER_ID), status="done")
        response = self.client.patch(
            f"/api/tasks/{event_id}",
            json={"status": "done"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "done")

    def test_update_status_not_found(self) -> None:
        self.repo.update_event_status.return_value = None
        response = self.client.patch(
            f"/api/tasks/{uuid4()}",
            json={"status": "done"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 404)

    def test_delete_event(self) -> None:
        event_id = str(uuid4())
        self.repo.delete_event.return_value = True
        response = self.client.delete(f"/api/tasks/{event_id}", headers=self.headers)
        self.assertEqual(response.status_code, 204)

    def test_delete_event_not_found(self) -> None:
        self.repo.delete_event.return_value = False
        response = self.client.delete(f"/api/tasks/{uuid4()}", headers=self.headers)
        self.assertEqual(response.status_code, 404)

    def test_timezone_get_set_resolve(self) -> None:
        self.repo.get_user_timezone.return_value = None
        response = self.client.get("/api/timezone", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["timezone"], "Europe/Moscow")

        self.repo.set_user_timezone.return_value = {"user_id": str(USER_ID), "timezone": "Europe/Moscow"}
        response = self.client.put("/api/timezone", json={"timezone": "Europe/Moscow"}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["timezone"], "Europe/Moscow")

        self.repo.resolve_local_datetime.return_value = "2026-10-24T07:00:00Z"
        response = self.client.post("/api/timezone/resolve", json={"date": "2026-10-24", "time": "10:00"}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["event_at"], "2026-10-24T07:00:00Z")

    def test_cors_preflight(self) -> None:
        response = self.client.options(
            "/api/tasks",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-Max-InitData,Idempotency-Key",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"), "*")

    def test_dev_mode(self) -> None:
        settings = make_settings(app_env="development", auth_dev_mode=True, max_bot_token="")
        app = create_app(settings=settings, repository=self.repo)
        client = TestClient(app)
        response = client.get("/api/me", headers={"X-Debug-User-Id": "dev:42"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], "dev:42")

    def test_dev_mode_forbidden_in_production(self) -> None:
        with self.assertRaises(ValueError):
            make_settings(app_env="production", auth_dev_mode=True, max_bot_token="")
