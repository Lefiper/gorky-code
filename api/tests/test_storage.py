from __future__ import annotations

import unittest
from datetime import UTC, date, datetime, timedelta

from uuid import UUID

from app.errors import ValidationError
from app.storage import _uuid, day_bounds, local_datetime_to_iso, normalize_range


class DayBoundsTest(unittest.TestCase):
    def test_moscow(self) -> None:
        start, end = day_bounds(date(2026, 10, 24), "Europe/Moscow")
        self.assertEqual(start, datetime(2026, 10, 23, 21, 0, tzinfo=UTC))
        self.assertEqual(end, datetime(2026, 10, 24, 21, 0, tzinfo=UTC))

    def test_dst_day_is_23_hours(self) -> None:
        start, end = day_bounds(date(2026, 3, 8), "America/New_York")
        self.assertEqual(end - start, timedelta(hours=23))

    def test_unknown_timezone(self) -> None:
        with self.assertRaises(ValidationError):
            day_bounds(date(2026, 10, 24), "Mars/Olympus")


class NormalizeRangeTest(unittest.TestCase):
    def test_converts_to_utc(self) -> None:
        start, end = normalize_range(
            datetime.fromisoformat("2026-10-24T00:00:00+03:00"),
            datetime.fromisoformat("2026-10-25T00:00:00+03:00"),
            required=True,
        )
        self.assertEqual(start, datetime(2026, 10, 23, 21, 0, tzinfo=UTC))
        self.assertEqual(end, datetime(2026, 10, 24, 21, 0, tzinfo=UTC))

    def test_requires_both_bounds(self) -> None:
        with self.assertRaises(ValidationError):
            normalize_range(datetime.now(UTC), None, required=True)

    def test_rejects_naive(self) -> None:
        with self.assertRaises(ValidationError):
            normalize_range(datetime(2026, 10, 24), datetime(2026, 10, 25), required=True)

    def test_rejects_reverse(self) -> None:
        with self.assertRaises(ValidationError):
            normalize_range(
                datetime(2026, 10, 25, tzinfo=UTC),
                datetime(2026, 10, 24, tzinfo=UTC),
                required=True,
            )


class LocalDatetimeTest(unittest.TestCase):
    def test_moscow(self) -> None:
        self.assertEqual(local_datetime_to_iso("2030-01-02", "10:00", "Europe/Moscow"), "2030-01-02T07:00:00Z")

    def test_dst_ambiguous(self) -> None:
        with self.assertRaises(ValidationError):
            local_datetime_to_iso("2026-10-25", "02:30", "Europe/Berlin")

    def test_invalid_date(self) -> None:
        with self.assertRaises(ValidationError):
            local_datetime_to_iso("2030-02-30", "10:00", "Europe/Moscow")


class EventIdTest(unittest.TestCase):
    def test_uuid_object_from_router_is_accepted(self) -> None:
        value = UUID("0f5c0f8e-1111-4a2b-9c3d-000000000001")
        self.assertEqual(_uuid(value), value)

    def test_uuid_string_is_accepted(self) -> None:
        self.assertEqual(_uuid("0f5c0f8e-1111-4a2b-9c3d-000000000001"), UUID("0f5c0f8e-1111-4a2b-9c3d-000000000001"))

    def test_invalid_id_is_validation_error(self) -> None:
        with self.assertRaises(ValidationError):
            _uuid("not-a-uuid")
        with self.assertRaises(ValidationError):
            _uuid(42)
