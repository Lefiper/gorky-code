"""Whisper через self-hosted HTTP-сервис (multipart: file, model, language)."""

from __future__ import annotations

from asr.base import ASRProvider, multipart


class WhisperProvider(ASRProvider):
    name = "whisper"

    def transcribe(self, audio: bytes, suffix: str = ".ogg") -> str:
        url = self._required("WHISPER_URL")
        model = self.env.get("WHISPER_MODEL", "large-v3").strip() or "large-v3"
        body, content_type = multipart({"model": model, "language": "ru"}, audio, "voice" + suffix)
        headers = {"Content-Type": content_type}
        key = self.env.get("WHISPER_API_KEY", "").strip()
        if key:
            headers["Authorization"] = "Bearer " + key
        return self._checked(self._json(self.transport.raw("POST", url, body, headers)).get("text"))
