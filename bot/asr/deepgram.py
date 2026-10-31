"""Deepgram pre-recorded STT (тело запроса — сырое аудио)."""

from __future__ import annotations

from urllib.parse import urlencode

from asr.base import ASRProvider

DEFAULT_URL = "https://api.deepgram.com/v1/listen"


class DeepgramProvider(ASRProvider):
    name = "deepgram"

    def transcribe(self, audio: bytes, suffix: str = ".ogg") -> str:
        model = self.env.get("DEEPGRAM_MODEL", "nova-3").strip() or "nova-3"
        query = urlencode({"model": model, "language": "ru", "smart_format": "true"})
        url = (self.env.get("DEEPGRAM_URL", "").strip() or DEFAULT_URL) + "?" + query
        headers = {"Authorization": "Token " + self._required("DEEPGRAM_API_KEY"),
                   "Content-Type": "audio/ogg" if suffix == ".ogg" else "application/octet-stream"}
        data = self._json(self.transport.raw("POST", url, audio, headers))
        try:
            transcript = data["results"]["channels"][0]["alternatives"][0]["transcript"]
        except (KeyError, IndexError, TypeError):
            transcript = ""
        return self._checked(transcript)
