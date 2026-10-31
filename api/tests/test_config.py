from __future__ import annotations

import unittest

from tests.helpers import make_settings


class SettingsTest(unittest.TestCase):
    def test_empty_pg_password_rejected(self) -> None:
        with self.assertRaises(ValueError):
            make_settings(pg_password="")

    def test_production_requires_bot_token(self) -> None:
        with self.assertRaises(ValueError):
            make_settings(app_env="production", auth_dev_mode=False, max_bot_token="")

    def test_dev_mode_forbidden_outside_development(self) -> None:
        with self.assertRaises(ValueError):
            make_settings(app_env="test", auth_dev_mode=True)

    def test_invalid_timezone_rejected(self) -> None:
        with self.assertRaises(ValueError):
            make_settings(default_timezone="Mars/Olympus")

    def test_invalid_api_prefix_rejected(self) -> None:
        with self.assertRaises(ValueError):
            make_settings(api_prefix="/api/v1/")

    def test_pg_port_out_of_range_rejected(self) -> None:
        with self.assertRaises(ValueError):
            make_settings(pg_port=70000)

    def test_cors_origins_parsed(self) -> None:
        settings = make_settings(cors_origins="https://a.example, https://b.example")
        self.assertEqual(
            settings.cors_origin_list(),
            ["https://a.example", "https://b.example"],
        )

    def test_cors_wildcard(self) -> None:
        self.assertEqual(make_settings(cors_origins="*").cors_origin_list(), ["*"])

    def test_pg_config_repr_hides_password(self) -> None:
        settings = make_settings(pg_password="super-secret-password")
        self.assertNotIn("super-secret-password", repr(settings.pg_config()))
