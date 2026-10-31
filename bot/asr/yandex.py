"""Yandex SpeechKit (STT v1, короткие запросы до 30 секунд)."""

from __future__ import annotations

from urllib.parse import urlencode

from asr.base import ASRProvider

DEFAULT_URL = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"


class YandexProvider(ASRProvider):
    name = "yandex"

    def transcribe(self, audio: bytes, suffix: str = ".ogg") -> str:
        query = {"lang": "ru-RU", "format": "oggopus"}
        folder = self.env.get("YANDEX_FOLDER_ID", "").strip()
        if folder:
            query["folderId"] = folder
        url = (self.env.get("YANDEX_STT_URL", "").strip() or DEFAULT_URL) + "?" + urlencode(query)
        headers = {"Authorization": "Api-Key " + self._required("YANDEX_API_KEY"),
                   "Content-Type": "application/octet-stream"}
        data = self._json(self.transport.raw("POST", url, audio, headers))
        return self._checked(data.get("result"))
