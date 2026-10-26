# ASR Platform (GigaAM-v3)

Сервис распознавания речи для MAX-бота. Принимает аудио как есть (OGG/Opus из MAX),
сам приводит к 16 кГц моно WAV и отдаёт текст.

## Подключение бота (`max-bot/.env`)

```dotenv
STT_URL=http://asr:8001/v1/audio/transcriptions   # в compose — имя сервиса; локально http://127.0.0.1:8001/...
STT_API_KEY=<тот же, что API_KEY у сервиса>        # необязательно
STT_MODEL=gigaam                                    # имя движка: gigaam | whisper; любое другое значение -> основной
AUDIO_ALLOWED_HOSTS=<точный хост CDN из attachments[].payload.url>
```

Бот шлёт multipart `file`, `model`, `language=ru` и ждёт `200 {"text": "..."}` — это и возвращает
`POST /v1/audio/transcriptions`. Для остальных случаев есть `POST /v1/transcribe`
(`{"text","engine","audio_sec","latency_ms"}`) и `GET /health`.

## Запуск

```bash
pip install -r requirements.txt        # нужны ffmpeg и git
API_KEY=secret uvicorn asr.main:app --host 0.0.0.0 --port 8001
curl -H "Authorization: Bearer secret" -F "file=@voice.ogg" -F model=gigaam \
     http://localhost:8001/v1/audio/transcriptions
```

## Переменные окружения

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `ENGINES` | `gigaam` | список движков, первый — основной (`gigaam,whisper`) |
| `GIGAAM_MODEL` | `v3_e2e_rnnt` | модель GigaAM; `GIGAAM_CHECKPOINT` — свой дообученный чекпоинт |
| `API_KEY` | пусто | если задан, требуется `Authorization: Bearer <ключ>` |
| `MAX_SEC` / `MAX_MB` | `120` / `20` | лимиты длительности и размера |
| `CONCURRENCY` | `1` | сколько распознаваний одновременно |
| `HF_TOKEN` | — | нужен только для аудио длиннее 25 с (pyannote) |

Коды ошибок: `413` — слишком длинное/большое, `415` — аудио не читается, `401` — неверный ключ,
`503` — все движки отказали. Бот на любую ошибку отвечает пользователю
«Не удалось распознать голосовое».
