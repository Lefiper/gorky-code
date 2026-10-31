# syntax=docker/dockerfile:1
# Контекст сборки — корень репозитория.
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8
WORKDIR /app

COPY bot/requirements.txt ./requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip python -m pip install -r requirements.txt

RUN useradd --create-home --uid 10002 bot && mkdir -p /app/state && chown bot:bot /app/state
COPY bot/bot.py ./bot.py
COPY bot/asr/__init__.py bot/asr/base.py bot/asr/deepgram.py bot/asr/elevenlabs.py bot/asr/gigaam.py \
     bot/asr/whisper.py bot/asr/yandex.py ./asr/
COPY shared ./shared
COPY bot/reminder_worker.py ./reminder_worker.py
RUN chmod -R a+rX /app/bot.py /app/reminder_worker.py /app/shared /app/asr
USER bot
EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=5s --retries=6 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4).read()"

CMD ["python", "bot.py", "polling"]
