import hmac
import os
import subprocess
import tempfile
import threading
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Form, Header, HTTPException, UploadFile

from .engines import build_engines

MAX_SEC = float(os.getenv("MAX_SEC", "120"))
MAX_BYTES = int(os.getenv("MAX_MB", "20")) * 1024 * 1024  # бот режет аудио на 20 МБ
API_KEY = os.getenv("API_KEY", "")  # если задан — бот шлёт его как GIGAAM_API_KEY
ENGINES: dict = {}
ORDER: list[str] = []
slots = threading.Semaphore(int(os.getenv("CONCURRENCY", "1")))  # защита GPU/CPU


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ENGINES.update(build_engines())
    ORDER.extend(ENGINES.keys())  # первый в списке ENGINES — основной
    yield


app = FastAPI(title="ASR Platform", lifespan=lifespan)


def check_auth(authorization: str | None = Header(default=None)):
    if not API_KEY:
        return
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(token, API_KEY):
        raise HTTPException(401, "invalid api key")


def audio_seconds(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True, check=True,
    ).stdout
    return float(out.strip())


def run_transcription(upload: UploadFile, engine: str | None) -> dict:
    data = upload.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "file too large")
    if engine and engine not in ENGINES:
        raise HTTPException(400, f"unknown engine, available: {list(ENGINES)}")

    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.audio")
        wav = os.path.join(tmp, "in.wav")
        with open(src, "wb") as f:
            f.write(data)
        try:
            dur = audio_seconds(src)
        except (subprocess.CalledProcessError, ValueError):
            raise HTTPException(415, "unsupported audio")
        if dur > MAX_SEC:
            raise HTTPException(413, f"audio longer than {MAX_SEC:.0f}s")

        # Бот отдаёт голосовые как есть (OGG/Opus), поэтому приводим к 16 кГц моно WAV здесь.
        conv = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", src, "-vn", "-ar", "16000", "-ac", "1", wav],
            capture_output=True,
        )
        if conv.returncode != 0:
            raise HTTPException(415, "cannot decode audio")

        t0 = time.time()
        for name in ([engine] if engine else ORDER):
            try:
                with slots:
                    text = ENGINES[name].transcribe(wav, dur)
            except Exception:
                continue  # пробуем следующий движок
            return {
                "text": text,
                "engine": ENGINES[name].name,
                "audio_sec": round(dur, 2),
                "latency_ms": int((time.time() - t0) * 1000),
            }
    raise HTTPException(503, "all engines failed")


@app.post("/v1/transcribe", dependencies=[Depends(check_auth)])
def transcribe(file: UploadFile, engine: str | None = None):
    """Родной формат: {"text", "engine", "audio_sec", "latency_ms"}."""
    return run_transcription(file, engine)


@app.post("/v1/audio/transcriptions", dependencies=[Depends(check_auth)])
def multipart_transcriptions(
    file: UploadFile,
    model: str | None = Form(default=None),
    language: str | None = Form(default=None),  # принимаем и игнорируем: язык задаёт движок
):
    """Multipart-маршрут, который вызывает бот (GIGAAM_URL).

    Бот шлёт multipart: file, model (gigaam или whisper), language=ru.
    Если model совпадает с именем движка (gigaam / whisper) — используем его,
    иначе берём основной. Ответ: {"text": "..."}.
    """
    result = run_transcription(file, model if model in ENGINES else None)
    return {"text": result["text"]}


@app.get("/health")
def health():
    return {"ok": bool(ENGINES), "engines": [e.name for e in ENGINES.values()]}
