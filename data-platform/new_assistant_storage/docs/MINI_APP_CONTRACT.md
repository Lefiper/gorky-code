# Стыковка Mini App, API и БД — обновление 26 октября 2026

В этой копии проекта нет mini-app/max-mini-app.html, кода HTTP API и SQLite бота.
Сопоставление основано на присланном описании, а не на проверке этих файлов.
Наши изменения закрывают хранение и доступ к данным. HTTP-маршруты и HTML не реализованы.

## Что исправлено в нашей части

- Миграция 003 добавляет project, статусы new/progress/blocked и nullable duration_minutes.
- task/reminder/meeting и pending/done/cancelled сохранены; существующие записи не переписываются.
- user_profiles хранит общий IANA-пояс пользователя, например Europe/Moscow.
- APIEventService предоставляет создание, чтение, PATCH статуса, DELETE и работу с поясом.
- assistant_api получает права SELECT/INSERT/DELETE событий и UPDATE только status.
  Изменять id/user_id, схему и историю миграций эта роль не может.
- assistant_app остаётся ролью MCP с SELECT/INSERT. Три MCP-инструмента и их аргументы сохранены.

## Что делает разработчик HTTP API / Mini App

| Поле Mini App | Каноническое поле | Действие |
| --- | --- | --- |
| id | id UUID | В JSON передавать строкой; убрать Number/parseInt и числовые сравнения ID |
| title | name | Преобразование JSON-полей в API в обе стороны |
| desc | description | Преобразование JSON-полей в API в обе стороны |
| date + time | event_at | Использовать общий пояс, преобразовать местное время в ISO 8601 с UTC/смещением |
| dur | duration_minutes | Длительность в минутах (подтверждено пользователем), положительное целое или null |
| task/project/meeting | event_type | Все три доступны; reminder остаётся для агента |
| new/progress/done/blocked | status | Все четыре доступны; прежние pending/cancelled также допустимы |

pending можно отображать как new, сохраняя понятную семантику. cancelled нельзя
молча превращать в blocked: отмена и блокировка различны. Mini App нужно либо
добавить cancelled и reminder, либо согласовать явную политику фильтрации/отображения.
Никаких неоговорённых замен reminder→project или cancelled→blocked в хранилище нет.
dur=0 не считается длительностью: неизвестное значение передавать как null.
Проект в MVP — отдельный тип события с датой; иерархия проектов/подзадач не добавлена.
Если у макета есть задачи без даты, это ещё один контракт, которого исходно не было.

fetch('/api/tasks') требует реального HTTP API на том же origin или настроенного
proxy. Наш /mcp не является /api/tasks. Пути GET/POST /api/tasks,
PATCH /api/tasks/{uuid}, DELETE /api/tasks/{uuid} реализует владелец HTTP API.
Авторизация и доверенный user_id должны приходить из backend, не из поля формы.
Обёртка выдачи массива/пагинации должна совпадать с тем, что читает HTML.

## Как подключиться к API-хранилищу

В Docker: PGHOST=postgres, PGPORT=5432, PGDATABASE=assistant_mvp,
PGUSER=assistant_api, PGPASSWORD=значение STACK_API_PASSWORD из своего .env.docker.
На компьютере: PGHOST=127.0.0.1, PGPORT=55432. Пароль не передавать браузеру.
Внешний HTTP API должен явно использовать новую роль; его конфигурацию мы не видим.

```python
from app.api_storage import APIEventService
from app.config import Settings

storage = APIEventService(Settings.load())  # окружение именно assistant_api

# При изменении пояса ботом/пользователем: сохранять также в общую БД.
storage.set_user_timezone(trusted_user_id, "Europe/Moscow")
when = storage.resolve_local_datetime(trusted_user_id, body["date"], body["time"])
created = storage.create_event(
    user_id=trusted_user_id,
    event_type=body["type"],  # сверить фактическое имя поля в HTML
    name=body["title"],
    description=body.get("desc", ""),
    datetime=when,
    duration_minutes=body.get("dur"),
    status="new",
    idempotency_key=request_operation_key,
)
updated = storage.update_event_status(trusted_user_id, str(event_uuid), body["status"])
deleted = storage.delete_event(trusted_user_id, str(event_uuid))
```

Это фрагменты для разных обработчиков, не один выполняемый HTTP endpoint.
Функции синхронные: в async FastAPI используйте threadpool/asyncio.to_thread либо
обычный def endpoint. Ошибка ValidationError → 422, ConflictError → 409,
StorageError → 503; update=None или delete=False → 404 без раскрытия чужих ID.
Успешный PATCH возвращает событие, DELETE — bool. Адаптацию имён полей ответа делает API.
Физический DELETE освобождает и ключ операции: нельзя затем повторять старое создание
как новую доставку. Если нужен аудит/неограниченная дедупликация после удаления,
следующим решением будут мягкое удаление или отдельный журнал операций.

## Часовые пояса и SQLite бота

Таблица user_profiles не копирует значения из неизвестной нам SQLite автоматически.
Владелец бота должен один раз перенести существующие user_id/timezone и затем
писать смену пояса в общую БД (через свой API или APIEventService).
Поля/формат старой SQLite не предоставлены, поэтому импорт наугад не выполнялся.
До заполнения профиля get_user_timezone возвращает None; преобразование date/time
отклоняется вместо предположения, что пользователь в Москве.

На чтении API берёт event_at (UTC), переводит в профильный ZoneInfo и формирует
date/time для Mini App. Переходы DST проверяются: двойное и несуществующее местное
время отклоняется, требуется уточнение. Смещение UTC+3 не заменяет IANA-пояс
для произвольного пользователя. Методы MCP продолжают требовать время со смещением.

## Обновление существующей установки

Запустить обновлённый scripts/start.ps1 или scripts/start.sh. Скрипт допишет
STACK_API_PASSWORD, не заменяя прежние пароли. migrate применит только 003,
bootstrap создаст assistant_api. Удаление volume, переинициализация БД и замена
SQL 001/002 не нужны. На установленном вручную PostgreSQL: python -m app.db migrate;
Docker-роли там автоматически не создаются, их настраивает владелец БД.

## Кто отвечает за замечания

Хранилище/миграция/роли/общий профиль — наша часть, выполнено.
JSON-адаптер, маршруты, UUID в JS и отображение типов/статусов — API/Mini App.
Перенос и последующая синхронизация поясов из SQLite — бот совместно с API.
Поэтому ответ «это целиком не моя работа» был бы неточен: задача разделена.
