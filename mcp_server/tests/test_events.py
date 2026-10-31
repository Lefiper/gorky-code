"""Безопасные проверки входных данных без подключения к PostgreSQL."""

import unittest
from unittest.mock import patch

from app.config import Settings
from app.events import EventService, ValidationError


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.service = EventService(Settings("localhost", 5432, "unused", "unused", "unused"))

    def test_invalid_create_never_opens_connection(self):
        base = dict(user_id="fictional", event_type="task", name="Проверка", datetime="2030-01-02T10:00:00+03:00")
        cases = [dict(user_id=" "), dict(user_id=1), dict(event_type="unknown"),
                 dict(event_type=[]), dict(name=" "), dict(name="x" * 201),
                 dict(description=None), dict(description="x" * 10001),
                 dict(datetime="2030-01-02T10:00:00"), dict(datetime="bad"),
                 dict(datetime="2030-01-02"), dict(idempotency_key="")]
        with patch("app.events.connect") as connection:
            for changes in cases:
                with self.subTest(changes=changes), self.assertRaises(ValidationError):
                    self.service.create_event(**(base | changes))
            connection.assert_not_called()

    def test_invalid_reads(self):
        start, end = "2030-01-02T00:00:00Z", "2030-01-03T00:00:00Z"
        with patch("app.events.connect") as connection:
            for changes in [dict(start_time=end), dict(end_time=None), dict(limit=True),
                            dict(limit=101), dict(offset=-1), dict(event_type="invalid")]:
                with self.subTest(changes=changes), self.assertRaises(ValidationError):
                    self.service.get_event(**(dict(user_id="fake", start_time=start, end_time=end) | changes))
            for text in ["", "   ", None, "x" * 1001]:
                with self.subTest(text=text), self.assertRaises(ValidationError):
                    self.service.get_event_by_query("fake", text)
            connection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
