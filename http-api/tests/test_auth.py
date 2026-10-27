from __future__ import annotations

import time
import unittest
from urllib.parse import parse_qsl, urlencode

from app.auth import validate_init_data
from app.errors import AuthError
from tests.helpers import BOT_TOKEN, make_init_data, sign_init_data


class ValidateInitDataTest(unittest.TestCase):
    def test_valid(self) -> None:
        user = validate_init_data(make_init_data(), BOT_TOKEN, 3600)
        self.assertEqual(user.id, "123")
        self.assertEqual(user.first_name, "Test")
        self.assertEqual(user.last_name, "User")

    def test_tampered_user(self) -> None:
        data = dict(parse_qsl(make_init_data()))
        data["user"] = data["user"].replace('"id":123', '"id":456')
        with self.assertRaises(AuthError):
            validate_init_data(urlencode(data), BOT_TOKEN, 3600)

    def test_wrong_bot_token(self) -> None:
        with self.assertRaises(AuthError):
            validate_init_data(make_init_data(bot_token="another-token"), BOT_TOKEN, 3600)

    def test_expired(self) -> None:
        raw = make_init_data(auth_date=int(time.time()) - 7200)
        with self.assertRaises(AuthError):
            validate_init_data(raw, BOT_TOKEN, 3600)

    def test_from_future(self) -> None:
        raw = make_init_data(auth_date=int(time.time()) + 3600)
        with self.assertRaises(AuthError):
            validate_init_data(raw, BOT_TOKEN, 3600)

    def test_bad_hash(self) -> None:
        raw = make_init_data(hash_override="deadbeef")
        with self.assertRaises(AuthError):
            validate_init_data(raw, BOT_TOKEN, 3600)

    def test_non_hex_hash(self) -> None:
        raw = make_init_data(hash_override="не-хеш")
        with self.assertRaises(AuthError):
            validate_init_data(raw, BOT_TOKEN, 3600)

    def test_wrong_hash_length(self) -> None:
        raw = make_init_data(hash_override="a" * 63)
        with self.assertRaises(AuthError):
            validate_init_data(raw, BOT_TOKEN, 3600)

    def test_uppercase_hash_accepted(self) -> None:
        data = dict(parse_qsl(make_init_data()))
        data["hash"] = data["hash"].upper()
        user = validate_init_data(urlencode(data), BOT_TOKEN, 3600)
        self.assertEqual(user.id, "123")

    def test_duplicate_hash(self) -> None:
        raw = make_init_data()
        with self.assertRaises(AuthError):
            validate_init_data(raw + "&hash=" + "0" * 64, BOT_TOKEN, 3600)

    def test_missing_hash(self) -> None:
        raw = make_init_data()
        without_hash = raw.rsplit("&hash=", 1)[0]
        with self.assertRaises(AuthError):
            validate_init_data(without_hash, BOT_TOKEN, 3600)

    def test_missing_user(self) -> None:
        raw = sign_init_data(
            {
                "auth_date": str(int(time.time())),
                "query_id": "q",
            }
        )
        with self.assertRaises(AuthError):
            validate_init_data(raw, BOT_TOKEN, 3600)

    def test_bad_user_fields(self) -> None:
        raw = sign_init_data(
            {
                "auth_date": str(int(time.time())),
                "user": '{"id":123,"first_name":[]}',
            }
        )
        with self.assertRaises(AuthError):
            validate_init_data(raw, BOT_TOKEN, 3600)

    def test_missing_auth_date(self) -> None:
        raw = sign_init_data(
            {
                "query_id": "q",
                "user": '{"id":123,"first_name":"Test"}',
            }
        )
        with self.assertRaises(AuthError):
            validate_init_data(raw, BOT_TOKEN, 3600)

    def test_empty(self) -> None:
        with self.assertRaises(AuthError):
            validate_init_data("", BOT_TOKEN, 3600)

    def test_malformed(self) -> None:
        with self.assertRaises(AuthError):
            validate_init_data("not-a-query-string", BOT_TOKEN, 3600)
