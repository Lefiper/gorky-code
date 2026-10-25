# PostgreSQL + Redis + MCP

Самостоятельная часть командного проекта: постоянное хранение событий, три MCP-инструмента и временная память диалога. MAX Bot, ASR, LLM-агент и HTTP API разрабатываются отдельно.

Обновление 26 октября: добавлены project, duration_minutes, статусы Mini App, общие часовые пояса и отдельная роль HTTP API. [Сопоставление полей и границы работы](docs/MINI_APP_CONTRACT.md). HTTP-маршруты /api/tasks этим обновлением не добавлены.

## Быстрый запуск для проверяющих

Нужен только работающий Docker Desktop с Linux-контейнерами (на Linux — Docker Engine и Compose v2+). Python, PostgreSQL и Redis на компьютере устанавливать не требуется. Первый запуск скачивает образы и Python-пакеты: нужен интернет.

Скачайте и распакуйте репозиторий, откройте терминал в его корне.

Windows PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

Linux/macOS:

```sh
sh scripts/start.sh
```

Скрипт один раз создаёт `.env.docker` со случайными паролями, собирает приложение, запускает PostgreSQL и Redis, применяет миграции и запускает MCP. Повторный запуск сохраняет пароли и данные. Локальный `.env` не используется и не перезаписывается. Пароли не выводятся и не входят в Git.

| Компонент | Адрес на компьютере |
| --- | --- |
| MCP, Streamable HTTP | http://127.0.0.1:8001/mcp |
| Проверка готовности MCP и чтения БД | http://127.0.0.1:8001/health |
| PostgreSQL | 127.0.0.1:55432, БД assistant_mvp |
| Redis | redis://127.0.0.1:6380/0 |

Адрес `/mcp` предназначен для MCP-клиента; это не веб-интерфейс. `/health` можно открыть в браузере: ожидается `{"status":"ok"}`. Порты опубликованы только на localhost. Это сборка для разработки и независимой проверки, без публичной авторизации/TLS.

## Проверить, что всё работает

```sh
docker compose --env-file .env.docker -f compose.full.yaml ps
docker compose --env-file .env.docker -f compose.full.yaml exec -T mcp python -m app.check_mcp --transport http
docker compose --env-file .env.docker -f compose.full.yaml --profile tools run --rm tests
```

Ожидается: postgres/redis/mcp healthy, migrate завершился с кодом 0; клиент видит create_event/get_event/get_event_by_query; тесты заканчиваются `OK`. Тесты создают вымышленные события с user_id `test:` и временные ключи Redis. API-тесты удаляют только собственные фикстуры при проверке DELETE; остальные события остаются в тестовой БД. Реальные данные не нужны. В тестах неверных запросов сообщения Error/Warning ожидаемы — смотрите итог `OK`/`FAILED`.

Проверка индексов на 100000 искусственных событий во временной таблице:

```sh
docker compose --env-file .env.docker -f compose.full.yaml --profile tools run --rm benchmark
```

Планы EXPLAIN ANALYZE сохраняются в `docs/reports/index_plans.json`. Это синтетический эксперимент, не обещание производительности продукта. Обоснование и реальные замеры — [docs/INDEXES.md](docs/INDEXES.md).

## Остановка и повторный запуск

```sh
docker compose --env-file .env.docker -f compose.full.yaml stop
```

Для запуска снова выполните соответствующий `start.ps1`/`start.sh`. События PostgreSQL находятся в именованном Docker volume и сохраняются между остановками и перезапусками. Redis специально не пишет контекст на диск: после перезапуска память диалога теряется, сохранённые события остаются.

Сохраняйте `.env.docker`: его пароли соответствуют созданной БД. Изменение пароля в файле не меняет пароль существующей роли PostgreSQL. Автоматического удаления БД, volumes или сброса данных скрипты не выполняют.

## Что предоставляет модуль

- `create_event(user_id, event_type, name, datetime, description="", idempotency_key=None)`.
- `get_event(user_id, start_time, end_time, event_type=None, limit=100, offset=0)`.
- `get_event_by_query(user_id, text, start_time=None, end_time=None, limit=100, offset=0)`.

Параметры передаются по именам. `user_id` — непустая строка, которую backend берёт из доверенного источника. Типы: `task`, `reminder`, `meeting`. Название 1–200 символов, описание до 10000, текст поиска 1–1000. `limit` 1–100, `offset` неотрицательный bigint. Неопределённый исходный параметр `list` заменён согласованными limit/offset.

Время — ISO 8601 с обязательным часовым смещением, например `2030-01-02T15:00:00+03:00`. В PostgreSQL используется timestamptz, ответы в UTC с Z. Исходное название часового пояса не хранится. Агент получает Europe/Moscow и текущее время из своего backend, уточняет «завтра» и неоднозначное «в три». Период `[start_time, end_time)`: начало включено, конец исключён. Сортировка по event_at, id. При поиске можно опустить обе границы или любую одну.

Создание возвращает `{"event": {...}, "created": true}`. Повтор той же операции с тем же ключом возвращает прежнее событие и created=false; другие данные с тем же ключом — конфликт. Без ключа одинаковые события разрешены. Ключ уникален в пределах пользователя. При потере ответа сохранение могло состояться — повторяйте с прежним ключом.

Чтение возвращает `{"items": [...], "has_more": false}`. Пустой items — нормальный результат. Ошибки входных данных, конфликта и БД возвращаются как ошибки MCP; успех приходит только после COMMIT. Русский поиск учитывает формы слов, требует все значимые слова и не исправляет опечатки. Запрос из стоп-слов возвращает пустой список. Это не семантический поиск.

Redis хранит последние 10 сообщений всего (user/assistant), метаданные ASR и отдельное предложение события с ключом операции. TTL 15 минут обновляется записью сообщения/предложения, чтение его не продлевает. Данные пользователей разделены. При недоступном Redis выдаётся ошибка; пустая память не имитируется. После истечения предложения требуется новое уточнение, а не создание по одному слову «да».

## Подключение остальных частей команды

[docs/TEAM_CONNECTIONS.md](docs/TEAM_CONNECTIONS.md) — схема, адреса внутри Docker, доступ HTTP API и границы ответственности.

[docs/AGENT_INTEGRATION.md](docs/AGENT_INTEGRATION.md) — использование памяти и подтверждения через Redis → MCP → PostgreSQL.

В общей Docker-сети MCP доступен по `http://mcp:8001/mcp`, Redis по `redis://redis:6379/0`, PostgreSQL по `postgres:5432`. MCP использует `assistant_app` / STACK_APP_PASSWORD. HTTP API использует отдельную роль `assistant_api` / STACK_API_PASSWORD из своего `.env.docker`: SELECT/INSERT/DELETE событий, UPDATE только status и работа с профилями. Пароль владельца для миграций агенту/API не нужен.

Обновлённый start-скрипт дописывает отсутствующий STACK_API_PASSWORD без замены прежних паролей. Миграция 003 применяется автоматически. Для API подготовлен APIEventService в app/api_storage.py, но обработчики GET/POST/PATCH/DELETE создаёт участник HTTP API. User timezone должен синхронизироваться ботом в user_profiles; автоматического импорта неизвестной SQLite нет.

Если каждый участник запустит свою копию, базы будут разными. GitHub передаёт код, а не события. Для общих данных нужен общий запуск команды или объединённый Compose. Mini App обращается к HTTP API, не к PostgreSQL напрямую. Доставка напоминаний по расписанию остаётся за компонентом команды.

## Устройство проекта

- `app/events.py` — валидация, SQL и ответы, без зависимости от MCP.
- `app/api_storage.py` — функции хранилища для API: project/длительность, статус, DELETE, общий timezone; без HTTP-маршрутов.
- `app/mcp_server.py` — регистрация трёх инструментов, HTTP/stdio и `/health`.
- `app/memory.py`, `app/confirmation.py` — временная память и сохранение подтверждённого предложения.
- `app/db/migrations.py`, `sql/` — транзакционные миграции с checksum и блокировкой параллельного запуска.
- `app/bootstrap.py` — настройка Docker-БД и ограниченной роли приложения.
- `Dockerfile`, `compose.full.yaml` — полный Linux-запуск; `compose.yaml` — прежний вариант только Redis.
- `requirements.linux.lock.txt` — зависимости Docker; `requirements.lock.txt` — проверенное Windows-окружение.
- `tests/` — проверки функций, Redis, реальных MCP-процессов и полного Docker-стека.
- `scripts/` — старт, EXPLAIN ANALYZE, контроль сохранности и сборка архива.

Для PyCharm с PostgreSQL, установленным вручную: [docs/LOCAL_DEVELOPMENT.md](docs/LOCAL_DEVELOPMENT.md). Существующую нашу схему можно безопасно принять командой `python -m app.db migrate --adopt-existing`; перед этим проверяются столбцы, значения по умолчанию и ограничения. Для новой БД используйте `python -m app.db migrate`. Старый `init` создаёт только базовую таблицу и оставлен для совместимости; предпочтителен migrate. Изменять уже применённые SQL-файлы нельзя: создавайте следующую миграцию.

## Если запуск не получается

- Docker недоступен: запустите Docker Desktop и дождитесь готовности Linux Engine.
- Порт занят: измените STACK_POSTGRES_PORT/STACK_REDIS_PORT/STACK_MCP_PORT в `.env.docker` и повторите запуск. Внутренние порты не меняются.
- БД отклоняет пароль после изменения файла: верните исходный `.env.docker`; не сбрасывайте volume с данными.
- Проверка готовности не прошла: `docker compose --env-file .env.docker -f compose.full.yaml logs --tail 50 migrate mcp`. Не публикуйте свои конфигурации/пароли в чат или Git.
- Повторный migrate ничего не меняет; ошибка checksum означает, что применённый SQL был изменён.

## Готовность и публикация

Актуальные результаты и ограничения: [docs/STATUS.md](docs/STATUS.md). Сквозная работа настоящих MAX/ASR/LLM ещё требует командной интеграции; standalone проверки не заменяют её.

Для передачи исходников можно собрать архив: `python -m scripts.package_release`. Он исключает `.env`, `.env.docker`, виртуальное окружение, Git и данные Docker. Инструкция публикации: [docs/GITHUB.md](docs/GITHUB.md). GitHub Actions workflow подготовлен; до публикации он проверяется только локальным выполнением аналогичных команд, не запускался на GitHub.
