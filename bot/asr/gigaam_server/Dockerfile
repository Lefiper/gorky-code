# GPU-образ. Для CPU замените базовый образ на python:3.11-slim (+ apt install ffmpeg git).
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip ffmpeg git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-whisper.txt ./
RUN pip3 install --no-cache-dir -r requirements.txt
# Whisper как запасной движок — раскомментируйте при необходимости:
# RUN pip3 install --no-cache-dir -r requirements-whisper.txt

COPY asr ./asr

ENV ENGINES=gigaam \
    GIGAAM_MODEL=v3_e2e_rnnt
# HF_TOKEN передавайте при запуске (-e HF_TOKEN=...), он нужен только для длинного аудио.
# Веса модели скачиваются при первом запуске: примонтируйте кэш, например
#   -v gigaam_cache:/root/.cache

EXPOSE 8001
CMD ["uvicorn", "asr.main:app", "--host", "0.0.0.0", "--port", "8001"]
