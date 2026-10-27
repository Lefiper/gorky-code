from __future__ import annotations

import unittest
from datetime import UTC, date, datetime, timedelta

from app.errors import ValidationError
from app.storage import day_bounds, normalize_range


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
