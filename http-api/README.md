# HTTP API — MAX Mini App

FastAPI-сервис для мини-приложения «Горький код». Читает, создаёт, изменяет статус и
удаляет события в общей таблице `public.events`, которую ведёт
`data-platform/new_assistant_storage`.

## Границы сервиса

```text
MAX Mini App  ──HTTP──>  HTTP API  ──SQL──>  PostgreSQL
```

- API **не** ходит в Redis, MCP, GigaChat и ASR.
- MCP Server — отдельный сервис для LLM. У него с API общая только база.
- Пользователь определяется **только** по подписанному MAX `initData` (исключение —
  явный dev-режим).
- API работает ролью `assistant_api`: `SELECT`/`INSERT`/`DELETE` и `UPDATE` только
  поля `status`.

## Быстрый запуск

Нужен Python 3.11+. Для работы с событиями — доступный PostgreSQL со схемой из
`data-platform/new_assistant_storage`. Без БД приложение тоже запускается — для
просмотра `/docs` и проверки контракта.

```powershell
cd http-api
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Активировать venv не обязательно: команды ниже вызывают Python из `.venv` напрямую.
Заполни в `.env`:

- `PGPASSWORD` — пароль роли `assistant_api` (в Docker-стеке это `STACK_API_PASSWORD`
  из `data-platform/new_assistant_storage/.env.docker`);
- `MAX_BOT_TOKEN` — токен бота, к которому привязано Mini App;
- либо `AUTH_DEV_MODE=true` для локальной проверки без MAX.

Запуск:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --reload --port 8002
```

- Swagger: <http://127.0.0.1:8002/docs>
- OpenAPI: <http://127.0.0.1:8002/openapi.json>
- Health: <http://127.0.0.1:8002/health>

В Swagger у защищённых методов заполни `X-Max-InitData`; альтернатива — заголовок
`Authorization: Bearer <initData>`. В dev-режиме — `X-Debug-User-Id`.

Если PostgreSQL недоступен, приложение всё равно стартует, `/docs` работает,
а `/health` возвращает `503`. Это удобно для проверки контракта без БД.

### Подключение к стеку data-platform

По умолчанию в `.env.example`:

```dotenv
PGHOST=127.0.0.1
PGPORT=55432
PGDATABASE=assistant_mvp
PGUSER=assistant_api
```

Это порты, которые `compose.full.yaml` публикует на localhost. В общей Docker-сети
используются `postgres:5432`; API нужен только PostgreSQL.

## Авторизация MAX

Mini App передаёт `window.WebApp.initData` в заголовке:

```http
X-Max-InitData: auth_date=...&query_id=...&user=...&hash=...
```

Можно также использовать `Authorization: Bearer <initData>`.

API проверяет подпись по документации MAX:

```text
secret_key = HMAC-SHA256(key="WebAppData", data=bot_token)
hash       = hex(HMAC-SHA256(key=secret_key, data=launch_params))
```

`launch_params` — все поля, кроме `hash`, отсортированные по ключу и склеенные
через `\n` в виде `key=value`. Значения URL-декодируются. Проверяется:

- подпись;
- `auth_date` (по умолчанию не старше 1 часа);
- наличие `user.id`;
- отсутствие повторяющихся полей.

`user_id` берётся только из проверенного `initData` (тот же `str(uid)`, что у бота и
MCP). Поле `user_id` в теле запроса запрещено.

### Dev-режим

Только для локальной разработки:

```dotenv
APP_ENV=development
AUTH_DEV_MODE=true
DEV_USER_ID=dev:1
```

Тогда API доверяет заголовку `X-Debug-User-Id` (или `DEV_USER_ID`, если заголовка
нет). `AUTH_DEV_MODE=true` разрешён только при `APP_ENV=development`; при
`production` настройки не запустятся. Токен бота в этом режиме не нужен:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8002/api/me" -Headers @{ "X-Debug-User-Id" = "dev:42" }
```

### Проверка с подписанным initData

Если `AUTH_DEV_MODE=false` и задан `MAX_BOT_TOKEN`, можно сгенерировать
подписанный `initData` для curl:

```powershell
$init = .\.venv\Scripts\python.exe scripts\make_init_data.py --user-id 123
Invoke-RestMethod -Uri "http://127.0.0.1:8002/api/me" -Headers @{ "X-Max-InitData" = $init }
```

Скрипт берёт `MAX_BOT_TOKEN` из `.env` или переменной окружения; `--bot-token`
тоже работает.

## Эндпоинты

Базовый префикс: `/api`. Все эндпоинты из таблицы, кроме `/health`, требуют
авторизации.

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/health` | Проверка API и PostgreSQL |
| `GET` | `/api/me` | Профиль из `initData` |
| `GET` | `/api/tasks` | События за день или период |
| `GET` | `/api/tasks/search` | Полнотекстовый поиск |
| `GET` | `/api/tasks/{id}` | Событие по UUID |
| `POST` | `/api/tasks` | Создать событие |
| `PATCH` | `/api/tasks/{id}` | Изменить статус |
| `DELETE` | `/api/tasks/{id}` | Удалить событие |
| `GET` | `/api/timezone` | Таймзона пользователя |
| `PUT` | `/api/timezone` | Установить таймзону пользователя |
| `POST` | `/api/timezone/resolve` | Локальная дата/время → UTC ISO |

### Список за день

```http
GET /api/tasks?date=2026-10-24&timezone=Europe/Moscow
```

День считается как `[00:00, 00:00 следующего дня)` в указанной IANA-таймзоне.
По умолчанию `Europe/Moscow`.

### Список за период

```http
GET /api/tasks?from=2026-10-24T00:00:00%2B03:00&to=2026-10-25T00:00:00%2B03:00
```

`from` включительно, `to` исключительно. Обе границы обязательны, если не передан
`date`. Даты — ISO 8601 с обязательным offset.

Фильтр по типу можно повторять:

```http
GET /api/tasks?...&event_type=task&event_type=project
```

Допустимые типы: `task`, `reminder`, `meeting`, `project`.

### Поиск

```http
GET /api/tasks/search?q=созвон&from=2026-10-01T00:00:00%2B03:00
```

Русский полнотекстовый поиск PostgreSQL: учитывает словоформы, требует все
значимые слова, не исправляет опечатки и не ищет по смыслу. Границы периода
необязательны.

### Создание

```http
POST /api/tasks
Content-Type: application/json
Idempotency-Key: demo-1

{
  "event_type": "project",
  "name": "Демо для куратора",
  "description": "Показать HTTP API",
  "event_at": "2026-10-27T15:00:00+03:00",
  "duration_minutes": 90,
  "status": "new"
}
```

Ответ `201`:

```json
{
  "event": {
    "id": "0f5c0f8e-...",
    "user_id": "123",
    "event_type": "project",
    "name": "Демо для куратора",
    "description": "Показать HTTP API",
    "event_at": "2026-10-27T12:00:00Z",
    "created_at": "2026-10-26T10:00:00Z",
    "status": "new",
    "duration_minutes": 90
  },
  "created": true
}
```

Повтор с тем же `Idempotency-Key` и теми же данными возвращает `200` и
`created: false`. Тот же ключ с другими данными — `409`.

### Изменение статуса

```http
PATCH /api/tasks/{id}
Content-Type: application/json

{ "status": "done" }
```

Допустимые статусы: `pending`, `new`, `progress`, `done`, `blocked`, `cancelled`.
Ответ `200` с событием или `404`.

### Удаление

```http
DELETE /api/tasks/{id}
```

Ответ `204` или `404`.

### Таймзона пользователя

```http
GET /api/timezone
PUT /api/timezone
{ "timezone": "Europe/Moscow" }

POST /api/timezone/resolve
{ "date": "2026-10-24", "time": "10:00" }
```

`resolve` возвращает `{"event_at": "2026-10-24T07:00:00Z"}` с использованием
профиля пользователя. Если профиль не задан — `422`.

### Формат списка

```json
{
  "items": [],
  "has_more": false
}
```

`limit` — 1–100, `offset` — неотрицательный. Сортировка по `event_at`, затем `id`.

## Модель события

| Поле | Тип | Комментарий |
|---|---|---|
| `id` | UUID | Генерируется API |
| `user_id` | text | Из проверенного `initData`; тот же `str(uid)`, что у бота и MCP |
| `event_type` | `task` / `reminder` / `meeting` / `project` | Как в БД |
| `name` | text | 1–200 символов |
| `description` | text | До 10000 символов |
| `event_at` | timestamptz | В ответах UTC с `Z` |
| `created_at` | timestamptz | В ответах UTC с `Z` |
| `status` | `pending` / `new` / `progress` / `done` / `blocked` / `cancelled` | Чтение и изменение через PATCH |
| `duration_minutes` | int \| null | Положительное число минут или null |

## Ошибки

```json
{"detail": "Событие не найдено."}
```

- `401` — нет/испорчен/просрочен `initData`;
- `404` — событие не найдено или принадлежит другому пользователю;
- `409` — конфликт `Idempotency-Key`;
- `422` — ошибка валидации: смотри `detail`, а для ошибок схемы запроса ещё и `errors`;
- `503` — PostgreSQL недоступен.

## Тесты

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\ruff.exe check app tests scripts
```

Сейчас: 61 тест API, авторизации, настроек, хранилища и логики дат проходят без БД,
8 интеграционных тестов с PostgreSQL по умолчанию пропускаются. Ruff
проверяет импорты, ошибки и совместимость с Python 3.11.

Интеграционные тесты:

```powershell
$env:ASSISTANT_RUN_DB_TESTS = "1"
$env:PGHOST = "127.0.0.1"
$env:PGPORT = "55432"
$env:PGDATABASE = "assistant_mvp"
$env:PGUSER = "assistant_api"
$env:PGPASSWORD = "<STACK_API_PASSWORD>"
.\.venv\Scripts\python.exe -m unittest tests.test_integration -v
```

Тесты создают события с `user_id` вида `test:api:<uuid>` и не удаляют их — как и
тесты `data-platform`. Это проверочные данные.

Smoke-тест против запущенного API (создаёт одно тестовое событие):

```powershell
.\.venv\Scripts\python.exe -m scripts.smoke_test --base-url "http://127.0.0.1:8002"
```

Скрипт также берёт `MAX_BOT_TOKEN` из `.env` или окружения.

## Docker

Сначала подними общий стек данных (команды из `http-api`):

```powershell
cd ..\data-platform\new_assistant_storage
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1
cd ..\..\http-api
```

Затем API:

```powershell
Copy-Item .env.example .env
# заполнить PGPASSWORD (STACK_API_PASSWORD) и MAX_BOT_TOKEN
docker compose up --build -d
docker compose ps
```

`compose.yaml` подключается к внешней сети `assistant-stack_default` и переопределяет
`PGHOST=postgres`, `PGPORT=5432`. Порт API — `127.0.0.1:8002`.

Если запускаешь API на хосте, Docker для него не нужен: достаточно PostgreSQL
на `127.0.0.1:55432`.

## Интеграция с Mini App

Сейчас `mini-app/max-mini-app.html` — макет с захардкоженными данными. Чтобы он
работал с API, фронту нужно:

1. Подключить MAX Bridge и брать `window.WebApp.initData`:
   ```html
   <script src="https://st.max.ru/js/max-web-app.js"></script>
   ```
   Не использовать `initDataUnsafe` для авторизации — это не подписанная строка.
   Передавать именно `initData`, а не весь URL-fragment.
2. Передавать его в каждом запросе:
   ```js
   fetch(API_BASE + "/api/tasks?date=...", {
     headers: { "X-Max-InitData": window.WebApp.initData }
   })
   ```
3. Использовать абсолютный `API_BASE`, а не относительный `/api/tasks`.
4. Заменить поля макета:
   - `title` → `name`;
   - `desc` → `description`;
   - `date` + `time` → `event_at` (ISO 8601 с offset, общий пояс пользователя);
   - `dur` → `duration_minutes` (положительное целое или null);
   - `type` → `event_type` (`task`/`project`/`meeting`; `reminder` — для агента);
   - `status` → `new`/`progress`/`done`/`blocked` (и `pending`/`cancelled`).
5. Учесть, что `id` — UUID-строка. В текущем макете `onclick="S.toggle('+t.id+')"`
   для UUID сломается: ID нужно экранировать или использовать `addEventListener`.
6. При создании нельзя отправлять `id`, `user_id` — API вернёт `422`; статус нового
   события по умолчанию `new`.
7. Исправить `isoToday()`: сейчас он берёт UTC-дату через `toISOString()`,
   а календарь должен работать в локальной таймзоне пользователя.
8. Для production указать точный origin Mini App в `CORS_ORIGINS` вместо `*`.

Пример сборки времени и запросов:

```js
const API_BASE = "https://api.example.com";
const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
const eventAt = new Date(`${date}T${time}:00`).toISOString();
const idempotencyKey = crypto.randomUUID();

const created = await fetch(`${API_BASE}/api/tasks`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "X-Max-InitData": window.WebApp.initData,
    "Idempotency-Key": idempotencyKey,
  },
  body: JSON.stringify({
    event_type: type,       // task | project | meeting
    name: title,
    description: desc,
    event_at: eventAt,
    duration_minutes: dur || null,
    status: "new",
  }),
});

const listed = await fetch(
  `${API_BASE}/api/tasks?date=${date}&timezone=${encodeURIComponent(timezone)}`,
  { headers: { "X-Max-InitData": window.WebApp.initData } },
);
```

`new Date(...)` использует таймзону устройства; для календаря передавай `timezone`
из `Intl.DateTimeFormat().resolvedOptions().timeZone` (или согласованное значение),
иначе API возьмёт `Europe/Moscow`.

`Idempotency-Key` должен быть одинаковым при повторе одной и той же операции
(например, после сетевой ошибки). Новый ключ на каждый клик создаст дубль.

Без `PATCH /api/tasks/{id}` кнопка «выполнено» в макете работать не будет. Статус
меняется через PATCH.

## Ограничения и следующие шаги

- **Только чтение + создание + изменение статуса + удаление.** `assistant_api` имеет
  `SELECT`/`INSERT`/`DELETE` и `UPDATE` только `status`. Изменять `id`/`user_id`,
  схему и историю миграций роль не может.
- **Таймзона пользователя хранится в общей БД** (`user_profiles`), но бот должен
  перенести существующие значения из своей SQLite и писать смену пояса в общую БД.
  До заполнения профиля `resolve` отклоняет запрос.
- **Нет rate limiting.** Добавлять на reverse proxy.
- **Нет уведомлений.** Напоминания доставляет MAX-бот, не API.
- **Два сервиса пишут в `public.events`.** MCP и API должны сохранять одинаковые
  правила валидации и формат дат. При изменении схемы обновляйте оба места.
- **Websocket/real-time нет.** Mini App обновляет данные запросами.

## Безопасность

- Не логировать `initData`, `MAX_BOT_TOKEN` и `PGPASSWORD`.
- Использовать роль `assistant_api`, а не владельца БД.
- `AUTH_DEV_MODE` держать выключенным вне development.
- Ограничить `CORS_ORIGINS` конкретным origin Mini App в production.
- Поставить HTTPS/reverse proxy; наружу публиковать только API, не PostgreSQL.
- Токен бота хранить в секрет-менеджере или `.env`, не в Git.
- Ограничить размер тела запроса и частоту запросов на прокси.
- В production закрыть `/docs` и `/openapi.json` на прокси или отключить их.

## Структура

```text
http-api/
  app/
    main.py          # create_app, CORS, обработчики ошибок
    config.py        # Settings из env/.env
    auth.py          # проверка MAX initData
    storage.py       # SQL к public.events/user_profiles, пул соединений
    schemas.py       # Pydantic-схемы
    dependencies.py  # settings/repository/current_user
    errors.py        # доменные ошибки -> HTTP
    routers/
      tasks.py
      timezone.py
      me.py
      health.py
  tests/
    helpers.py
    test_auth.py
    test_storage.py
    test_api.py
    test_config.py
    test_integration.py
  scripts/
    make_init_data.py
    smoke_test.py
  Dockerfile
  compose.yaml
  requirements.txt
  requirements-dev.txt
  pyproject.toml
  .env.example
```
