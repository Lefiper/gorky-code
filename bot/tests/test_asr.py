import json
import unittest
from unittest.mock import Mock

from asr.base import ASRError, build_provider


def transport(response: bytes):
    mock = Mock()
    mock.raw.return_value = response
    return mock


class ProviderTests(unittest.TestCase):
    def test_gigaam_posts_multipart_to_configured_service(self):
        t = transport(json.dumps({"text": "Позвонить Ивану"}).encode())
        text = build_provider("gigaam", t, {"GIGAAM_URL": "http://asr:8001/v1/audio/transcriptions",
                                            "GIGAAM_API_KEY": "k1"}).transcribe(b"ogg-bytes", ".ogg")
        self.assertEqual(text, "Позвонить Ивану")
        method, url, body, headers = t.raw.call_args.args
        self.assertEqual((method, url), ("POST", "http://asr:8001/v1/audio/transcriptions"))
        self.assertIn(b'name="model"\r\n\r\ngigaam', body)
        self.assertIn(b'filename="voice.ogg"', body)
        self.assertEqual(headers["Authorization"], "Bearer k1")
        self.assertTrue(headers["Content-Type"].startswith("multipart/form-data; boundary="))

    def test_whisper_uses_model_from_env(self):
        t = transport('{"text":"Привет"}'.encode())
        build_provider("whisper", t, {"WHISPER_URL": "http://w/v1", "WHISPER_MODEL": "medium"}).transcribe(b"a", ".ogg")
        self.assertIn(b"\r\n\r\nmedium", t.raw.call_args.args[2])

    def test_yandex_sends_raw_audio_with_api_key(self):
        t = transport('{"result": "Встреча в пятницу"}'.encode())
        text = build_provider("yandex", t, {"YANDEX_API_KEY": "yk", "YANDEX_FOLDER_ID": "f1"}).transcribe(b"opus")
        self.assertEqual(text, "Встреча в пятницу")
        method, url, body, headers = t.raw.call_args.args
        self.assertIn("lang=ru-RU", url)
        self.assertIn("format=oggopus", url)
        self.assertIn("folderId=f1", url)
        self.assertEqual(body, b"opus")
        self.assertEqual(headers["Authorization"], "Api-Key yk")

    def test_elevenlabs_uses_xi_api_key_and_text_field(self):
        t = transport('{"text": "Напомни в 10"}'.encode())
        text = build_provider("elevenlabs", t, {"ELEVENLABS_API_KEY": "ek"}).transcribe(b"x", ".ogg")
        self.assertEqual(text, "Напомни в 10")
        self.assertEqual(t.raw.call_args.args[3]["xi-api-key"], "ek")
        self.assertIn(b"scribe_v1", t.raw.call_args.args[2])

    def test_deepgram_reads_nested_transcript(self):
        payload = {"results": {"channels": [{"alternatives": [{"transcript": "Что у меня завтра"}]}]}}
        t = transport(json.dumps(payload).encode())
        text = build_provider("deepgram", t, {"DEEPGRAM_API_KEY": "dk"}).transcribe(b"x", ".ogg")
        self.assertEqual(text, "Что у меня завтра")
        self.assertEqual(t.raw.call_args.args[3]["Authorization"], "Token dk")

    def test_empty_transcript_is_error(self):
        t = transport(b'{"result": "   "}')
        with self.assertRaises(ASRError):
            build_provider("yandex", t, {"YANDEX_API_KEY": "yk"}).transcribe(b"x")

    def test_missing_key_is_error_without_request(self):
        t = transport(b"{}")
        with self.assertRaises(ASRError):
            build_provider("deepgram", t, {}).transcribe(b"x")
        t.raw.assert_not_called()

    def test_unknown_provider_is_rejected(self):
        with self.assertRaises(ASRError):
            build_provider("unknown-provider", transport(b"{}"), {})


if __name__ == "__main__":
    unittest.main()
