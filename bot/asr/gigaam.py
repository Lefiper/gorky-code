"""GigaAM-v3 через собственный сервис распознавания (bot/asr/gigaam_server)."""

from __future__ import annotations

from asr.base import ASRProvider, multipart


class GigaAMProvider(ASRProvider):
    name = "gigaam"

    def transcribe(self, audio: bytes, suffix: str = ".ogg") -> str:
        url = self._required("GIGAAM_URL")
        body, content_type = multipart({"model": "gigaam", "language": "ru"}, audio, "voice" + suffix)
        headers = {"Content-Type": content_type}
        key = self.env.get("GIGAAM_API_KEY", "").strip()
        if key:
            headers["Authorization"] = "Bearer " + key
        return self._checked(self._json(self.transport.raw("POST", url, body, headers)).get("text"))
