> Обновление 31 октября 2026: диалог хранит 40 сообщений (примерно 20 пар вопрос–ответ), TTL 24 часа с продлением при записи. `compose.persistence.yml` включает AOF Valkey и постоянный том. На первом переходе используйте `scripts/install_update_20261031.sh`, который переносит текущие AOF-данные. Добавьте файл к COMPOSE_FILE, сохранив compose.hackathon.yml и compose.webhook.yml.
>
> Создание, удаление и перенос требуют подтверждения. Кнопки привязаны к конкретному предложению; устаревшие кнопки не выполняют новое действие. Голосовые проходят через настроенный ASR в тот же агент. «На неделю» означает +7 календарных дней к дате найденного события. Неоднозначные названия нужно уточнять.
>
> MCP сохраняет результаты удаления и переноса в PostgreSQL (`005_event_operations.sql`), повтор с тем же ключом возвращает прежний результат. Создание с ключом объединяет события одного пользователя с одинаковыми типом, названием без учёта регистра, описанием и временем; другие описания/даты не объединяются. История Redis ограничена 40 сообщениями, не является бесконечной памятью. AOF everysec может потерять последнюю секунду записи при аварии хоста.
>
> Установщик не запускает тесты. При ошибке смотрите `/root/gorky-update-20261031.log`; путь к резервной копии и команда отката печатаются в нём. Секреты — только в .env; не добавляйте резервные копии в Git.

# Горький код — календарный ассистент в MAX

Текст и голос MAX → бот/ASR → FastAPI + LangChain → GigaChat и FastMCP → PostgreSQL. Единственная LLM — GigaChat через langchain-gigachat. Контекст и ожидающее подтверждения событие хранятся в Valkey (TTL 900 секунд). HTTP API и React Mini App работают с той же БД.

```text
MAX → bot → ASR
        └→ Agent FastAPI + LangChain → GigaChat
                   ├→ Valkey: история, pending, блокировки
                   └→ MCP (Bearer, внутренняя сеть) → PostgreSQL
Mini App React → HTTP API (подпись MAX initData) ───────┘
bot → PostgreSQL: user_profiles, очередь доставки напоминаний
bot → SQLite volume: durable inbox, дедупликация MAX, polling marker
```

## Быстрый запуск

Покупка VPS и размещение с Windows-ПК: [docs/WINDOWS_SERVER.md](docs/WINDOWS_SERVER.md).

Подробный запуск на Arch Linux: [docs/ARCH_LINUX.md](docs/ARCH_LINUX.md).

Нужны Docker Engine и Compose v2. Сначала создайте .env:

```sh
python scripts/init_env.py
# либо cp .env.example .env и задайте случайные пароли вручную
# впишите реальные MAX_BOT_TOKEN, GIGACHAT_CREDENTIALS и MINI_APP_LINK

docker compose build
docker compose up -d
docker compose ps
```

init_env.py генерирует отдельные случайные пароли и внутренние токены, не перезаписывает существующий .env. Заглушки внешних ключей позволяют проверить инфраструктуру, но не дают рабочих вызовов MAX/GigaChat. Моки используются только в тестах через внедрение GigaChat-интерфейса. Секреты не передаются в сборку и исключены из Git.

Локальные адреса: API localhost:8002/docs; агент localhost:8003; Mini App localhost:8080; health бота localhost:8081/health. PostgreSQL доступен только с localhost:55432, Valkey с localhost:6380. MCP не публикует порт на хост. Завершившийся migrate с кодом 0 — ожидаемое состояние одноразового сервиса; остальные должны быть healthy/running.

## Переменные и роли

Полный список — .env.example.

| Переменные | Назначение |
| --- | --- |
| POSTGRES_PASSWORD | Владелец миграций assistant_owner |
| APP_DB_PASSWORD | assistant_app: SELECT/INSERT events, без UPDATE/DELETE/DDL |
| API_DB_PASSWORD | assistant_api: CRUD событий, UPDATE только status; запись профилей |
| AGENT_DB_PASSWORD | assistant_agent: только SELECT user_profiles |
| BOT_DB_PASSWORD | assistant_bot: профили, SELECT events, UPDATE status, доставка напоминаний |
| MCP_AUTH_TOKEN | Bearer между агентом и MCP; обязателен при HTTP |
| AGENT_API_KEY | Bearer между ботом и агентом |
| GIGACHAT_CREDENTIALS, GIGACHAT_SCOPE, GIGACHAT_MODEL | Доступ к GigaChat; параметры сертификатов рядом в .env.example |
| MAX_BOT_TOKEN, MINI_APP_LINK | MAX и зарегистрированное Mini App |
| DEFAULT_TIMEZONE | Fallback IANA-пояса при отсутствии user_profiles, по умолчанию Europe/Moscow |
| VITE_API_BASE, VITE_BOT_LINK | Публичные значения, встраиваются при сборке Mini App |
| CORS_ORIGINS | Разрешённые origins браузера, через запятую |
| AGENT_MAX_TOOL_ROUNDS | Максимальное число раундов, 1–8; по умолчанию 4 |

Бот /timezone, настройка пояса Mini App и агент используют user_profiles. Время хранится в UTC; Mini App переводит локальную дату/время через /api/timezone/resolve, включая проверку неоднозначного DST. В каждый вызов модели подставляются серверное ISO-время до секунды, день недели и профильный пояс. Часовой пояс в теле /chat не переопределяет серверный профиль.

Создание всегда проходит через pending в Redis и отдельное явное подтверждение «да». До него MCP не вызывается. Повтор подтверждения с тем же Idempotency-Key возвращает сохранённый ответ; PostgreSQL дополнительно защищает ключ создания. Сообщения пользователя сериализуются Redis-блокировкой. За одно подтверждение создаётся одно событие; для трёх встреч агент сообщает об этом ограничении. Изменение/удаление доступны в Mini App, ссылка передаётся через MINI_APP_LINK.

## Голос и профили Compose

- Основной стек: docker compose up --build -d.
- GigaAM: docker compose --profile gigaam up --build -d. При ASR_PROVIDER=gigaam профиль обязателен; первая загрузка модели может быть долгой.
- Альтернативные ASR используют HTTP: задайте ASR_PROVIDER и переменные выбранного адаптера из .env.example.
- AUDIO_ALLOWED_HOSTS содержит точные хосты CDN из реальных MAX audio attachments, без схемы/пути, через запятую. Список неизвестен заранее и намеренно пуст. Отклонённый hostname журналируется без URL, query и токена. Не добавляйте wildcard.
- Если ASR не настроен, недоступен или CDN запрещён, бот предлагает повторить запись или написать текстом.
- tools: контейнер unittest для MCP.
- https: Caddy, см. ниже.

## Напоминания

Бот опрашивает PostgreSQL: reminder + pending + event_at <= now(), независимо от способа создания. Новое напоминание Mini App получает pending. Миграция 004 хранит состояния sending → inflight → sent; после успешного MAX-ответа status становится done. Row locks, SKIP LOCKED и условный claim исключают конкурентную отправку. Данные переживают перезапуск бота; застрявшие неопределённые записи не блокируют следующую пачку.

Ограничение внешнего протокола: документированный POST /messages MAX не предоставляет ключ идемпотентности. Поэтому при обрыве между отправкой и фиксацией результата нельзя доказать строго однократную доставку. Такой event остаётся inflight и не повторяется автоматически, чтобы не создавать дубли. Требуется сверка с MAX оператором. После сверки можно пометить доставку sent и событие done; возвращать sending допустимо только после подтверждения отсутствия сообщения. Документация: https://dev.max.ru/docs-api/methods/POST/messages.

SQLite сохранена для durable inbox и дедупликации MAX: один worker и один bot_state volume, без распределённых реплик бота. Профили из SQLite больше не читаются; старые значения timezone автоматически не импортируются. Пользователь задаёт пояс заново через /timezone или Mini App.

## HTTPS

Укажите PUBLIC_DOMAIN=assistant.example.org, VITE_API_BASE=https://assistant.example.org, CORS_ORIGINS=https://assistant.example.org и MINI_APP_LINK. DNS должен указывать на сервер, входящие 80/443 — доступны.

```sh
docker compose --profile https up --build -d
```

Caddy выдаёт сертификат и маршрутизирует /api/* в API, остальные пути в Mini App. После изменения VITE_* пересоберите miniapp. AUTH_DEV_MODE в production должен оставаться false. Настройка HTTPS на настоящем домене в этой среде не проверена.

## Проверки

```sh
docker compose exec mcp python -m scripts.check_tools --url http://127.0.0.1:8001/mcp
docker compose --profile tools run --rm tests
```

MCP_AUTH_TOKEN для scripts.check_tools берётся из окружения контейнера. Для локальных Python-процессов установите зависимости каждого сервиса, задайте PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD и REDIS_URL из .env, добавьте корень репозитория в PYTHONPATH. Запуск: uvicorn app.main:create_app --factory из agent/ (8003) и api/ (8002); python -m app.mcp_server --transport http из mcp_server/ (8001); python bot.py polling из bot/.

```sh
(cd agent && python -m pytest -q)
(cd api && python -m pytest -q)
(cd bot && python -m pytest -q)
(cd mcp_server && python -m unittest discover -s tests -v)
(cd miniapp && npm ci && npm run build)
```

Для интеграций: ASSISTANT_RUN_DB_TESTS=1, ASSISTANT_RUN_REDIS_TESTS=1, AGENT_TEST_REDIS_URL, AGENT_TEST_MCP_URL, API_TEST_URL, STACK_MCP_URL, STACK_MCP_HEALTH_URL. Передайте пароли ролей. Тест напоминаний создаёт отдельную тестовую БД и требует владельца с CREATEDB. API_TEST_URL — запущенный API с подписью тестового MAX_BOT_TOKEN. Полный фактический отчёт и ограничения — docs/STATUS.md.

## Бэкапы

```sh
sh scripts/backup.sh backup.dump
sh scripts/restore.sh backup.dump assistant_restore_check
```

Восстановление допускается только в новую БД. Скрипты не очищают рабочую БД. Для локального PostgreSQL есть backup.ps1/restore.ps1 (PG* из окружения и утилиты PostgreSQL в PATH). После восстановления выдайте роли запуском bootstrap с целевой PGDATABASE. Храните дампы вне репозитория с ограниченным доступом.
