"""Общий интерфейс ASR: бот не знает, какой провайдер распознаёт речь."""

from __future__ import annotations

import json
import os
import uuid
from typing import Protocol

MAX_TRANSCRIPT = 16000


class ASRError(RuntimeError):
    """Провайдер не распознал речь. Текст ошибки не содержит ключей и адресов."""


class Transport(Protocol):
    def raw(self, method, url, body=None, headers=None, limit=2_000_000, timeout=90) -> bytes: ...


class ASRProvider:
    """Базовый адаптер: transcribe(audio_bytes, suffix) -> текст на русском языке."""

    name = "base"

    def __init__(self, transport: Transport, env=None):
        self.transport = transport
        self.env = os.environ if env is None else env

    def transcribe(self, audio: bytes, suffix: str = ".ogg") -> str:
        raise NotImplementedError

    def _required(self, key: str) -> str:
        value = self.env.get(key, "").strip()
        if not value:
            raise ASRError(f"{key} не задан для ASR-провайдера {self.name}.")
        return value

    def _checked(self, text) -> str:
        if not isinstance(text, str) or not text.strip():
            raise ASRError("Пустой результат распознавания.")
        text = text.strip()
        if len(text) > MAX_TRANSCRIPT:
            raise ASRError("Слишком длинный результат распознавания.")
        return text

    def _json(self, raw: bytes) -> dict:
        try:
            data = json.loads(raw)
        except ValueError:
            raise ASRError("ASR вернул не JSON.") from None
        if not isinstance(data, dict):
            raise ASRError("ASR вернул неожиданный формат.")
        return data


def multipart(fields: dict, file_bytes: bytes, file_name: str) -> tuple[bytes, str]:
    boundary = "asr" + uuid.uuid4().hex
    parts = []
    for key, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{file_name}"\r\n'
                  f'Content-Type: application/octet-stream\r\n\r\n').encode()
                 + file_bytes + f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def build_provider(name: str, transport: Transport, env=None) -> ASRProvider:
    from asr.deepgram import DeepgramProvider
    from asr.elevenlabs import ElevenLabsProvider
    from asr.gigaam import GigaAMProvider
    from asr.whisper import WhisperProvider
    from asr.yandex import YandexProvider

    providers = {
        "gigaam": GigaAMProvider,
        "yandex": YandexProvider,
        "elevenlabs": ElevenLabsProvider,
        "deepgram": DeepgramProvider,
        "whisper": WhisperProvider,
    }
    key = (name or "").strip().lower()
    if key not in providers:
        raise ASRError("ASR_PROVIDER: допустимы gigaam, yandex, elevenlabs, deepgram, whisper.")
    return providers[key](transport, env)
