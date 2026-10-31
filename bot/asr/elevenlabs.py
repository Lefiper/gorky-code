"""ElevenLabs Speech-to-Text (multipart: file, model_id, language_code)."""

from __future__ import annotations

from asr.base import ASRProvider, multipart

DEFAULT_URL = "https://api.elevenlabs.io/v1/speech-to-text"


class ElevenLabsProvider(ASRProvider):
    name = "elevenlabs"

    def transcribe(self, audio: bytes, suffix: str = ".ogg") -> str:
        url = self.env.get("ELEVENLABS_URL", "").strip() or DEFAULT_URL
        model = self.env.get("ELEVENLABS_MODEL", "scribe_v1").strip() or "scribe_v1"
        body, content_type = multipart({"model_id": model, "language_code": "rus"}, audio, "voice" + suffix)
        headers = {"Content-Type": content_type, "xi-api-key": self._required("ELEVENLABS_API_KEY")}
        return self._checked(self._json(self.transport.raw("POST", url, body, headers)).get("text"))
