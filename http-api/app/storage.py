"""Доступ к public.events.

SQL и правила совпадают с data-platform/assistant-storage/app/events.py.
При изменении схемы или контракта обновляйте оба места.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, time, timedelta
from datetime import date as Date
from datetime import datetime as DateTime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolClosed, PoolTimeout

from app.errors import ConflictError, NotFoundError, StorageError, ValidationError

EVENT_TYPES = ("task", "reminder", "meeting")
EVENT_STATUSES = ("pending", "done", "cancelled")
COLUMNS = "id, user_id, event_type, name, description, event_at, created_at, status"


@dataclass(frozen=True)
class PgConfig:
    host: str
    port: int
    dbname: str
    user: str
    password: str = field(repr=False)
    connect_timeout: int = 5


def _text(value: object, field: str, maximum: int | None = None, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field}: ожидается строка.")
    value = value.strip()
    if (not value and not allow_empty) or (maximum is not None and len(value) > maximum):
        raise ValidationError(f"{field}: пустое или слишком длинное значение.")
    return value


def _event_type(value: object) -> str:
    if not isinstance(value, str) or value not in EVENT_TYPES:
        raise ValidationError("event_type: допустимы task, reminder, meeting.")
    return value


def _event_types(values: Sequence[str] | str | None) -> list[str] | None:
    if values is None:
        return None
    if isinstance(values, str):
        values = [values]
    result = [_event_type(value) for value in values]
    deduplicated = list(dict.fromkeys(result))
    return deduplicated or None


def _time(value: object, field: str) -> DateTime:
    if isinstance(value, str):
        if "T" not in value:
            raise ValidationError(f"{field}: нужен ISO 8601 с T и часовым смещением.")
        try:
            value = DateTime.fromisoformat(value)
        except ValueError:
            raise ValidationError(f"{field}: некорректная дата ISO 8601.") from None
    if not isinstance(value, DateTime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError(f"{field}: обязательно часовое смещение, например +03:00.")
    try:
        return value.astimezone(UTC)
    except (ValueError, OverflowError):
        raise ValidationError(f"{field}: дата вне допустимого диапазона.") from None


def _range(
    start_time: object | None,
    end_time: object | None,
    required: bool = False,
) -> tuple[DateTime | None, DateTime | None]:
    if required and (start_time is None or end_time is None):
        raise ValidationError("Укажите start_time и end_time.")
    start = _time(start_time, "start_time") if start_time is not None else None
    end = _time(end_time, "end_time") if end_time is not None else None
    if start is not None and end is not None and start >= end:
        raise ValidationError("start_time должен быть раньше end_time.")
    return start, end


def normalize_range(
    start_time: object | None,
    end_time: object | None,
    required: bool = False,
) -> tuple[DateTime | None, DateTime | None]:
    """Публичная обёртка: проверяет даты и приводит их к UTC."""
    return _range(start_time, end_time, required=required)


def _pagination(limit: int, offset: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValidationError("limit: целое число от 1 до 100.")
    if type(offset) is not int or offset < 0 or offset > 9223372036854775807:
        raise ValidationError("offset: неотрицательное целое число в диапазоне bigint.")


def _serialize(row: dict) -> dict:
    result = dict(row)
    result["id"] = str(result["id"])
    for column in ("event_at", "created_at"):
        result[column] = result[column].astimezone(UTC).isoformat().replace("+00:00", "Z")
    return result


def day_bounds(day: Date, timezone_name: str) -> tuple[DateTime, DateTime]:
    """Границы дня [00:00, 00:00 следующего дня) в часовом поясе IANA."""
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        raise ValidationError("timezone: неизвестный часовой пояс IANA.") from None
    start = DateTime.combine(day, time.min, tzinfo=tz)
    end = DateTime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)


class EventRepository:
    def __init__(self, config: PgConfig) -> None:
        self._config = config
        self._pool = ConnectionPool(
            conninfo=psycopg.conninfo.make_conninfo(
                host=config.host,
                port=config.port,
                dbname=config.dbname,
                user=config.user,
                password=config.password,
                connect_timeout=config.connect_timeout,
            ),
            min_size=0,
            max_size=10,
            timeout=5,
            open=False,
            kwargs={
                "row_factory": dict_row,
                "options": "-c timezone=UTC -c statement_timeout=10000 -c lock_timeout=5000",
                "application_name": "gorky_http_api",
            },
        )

    def open(self) -> None:
        self._pool.open()

    def close(self) -> None:
        self._pool.close()

    @contextmanager
    def _connection(self) -> Iterator[psycopg.Connection]:
        try:
            with self._pool.connection() as conn:
                yield conn
        except (psycopg.Error, PoolTimeout, PoolClosed):
            raise StorageError() from None

    def ping(self) -> None:
        with self._connection() as conn:
            conn.execute("SELECT 1 FROM public.events LIMIT 1")

    def create_event(
        self,
        user_id: str,
        event_type: str,
        name: str,
        event_at: object,
        description: str = "",
        idempotency_key: str | None = None,
    ) -> dict:
        user_id = _text(user_id, "user_id")
        event_type = _event_type(event_type)
        name = _text(name, "name", 200)
        description = _text(description, "description", 10000, allow_empty=True)
        event_at_utc = _time(event_at, "event_at")
        key = _text(idempotency_key, "idempotency_key", 200) if idempotency_key is not None else None

        with self._connection() as conn:
            row = conn.execute(
                f"""INSERT INTO public.events
                (id, user_id, event_type, name, description, event_at, idempotency_key)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, idempotency_key) DO NOTHING
                RETURNING {COLUMNS}""",
                (uuid4(), user_id, event_type, name, description, event_at_utc, key),
            ).fetchone()
            created = row is not None
            if not created:
                row = conn.execute(
                    f"SELECT {COLUMNS} FROM public.events WHERE user_id = %s AND idempotency_key = %s",
                    (user_id, key),
                ).fetchone()
                if row is None:
                    raise StorageError("Не удалось прочитать результат повторной операции.")
                if (row["event_type"], row["name"], row["description"], row["event_at"]) != (
                    event_type,
                    name,
                    description,
                    event_at_utc,
                ):
                    raise ConflictError("idempotency_key уже использован с другими данными.")

        return {"event": _serialize(row), "created": created}

    def list_events(
        self,
        user_id: str,
        start_time: object,
        end_time: object,
        event_types: Sequence[str] | str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        user_id = _text(user_id, "user_id")
        start, end = _range(start_time, end_time, required=True)
        types = _event_types(event_types)
        _pagination(limit, offset)
        return self._select(user_id, start, end, limit, offset, event_types=types)

    def search_events(
        self,
        user_id: str,
        text: str,
        start_time: object | None = None,
        end_time: object | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        user_id = _text(user_id, "user_id")
        text = _text(text, "q", 1000)
        start, end = _range(start_time, end_time)
        _pagination(limit, offset)
        return self._select(user_id, start, end, limit, offset, text=text)

    def get_event_by_id(self, user_id: str, event_id: UUID | str) -> dict:
        user_id = _text(user_id, "user_id")
        try:
            event_uuid = UUID(str(event_id))
        except (ValueError, AttributeError):
            raise ValidationError("event_id: ожидается UUID.") from None

        with self._connection() as conn:
            row = conn.execute(
                f"SELECT {COLUMNS} FROM public.events WHERE user_id = %s AND id = %s",
                (user_id, event_uuid),
            ).fetchone()

        if row is None:
            raise NotFoundError()
        return _serialize(row)

    def _select(
        self,
        user_id: str,
        start: DateTime | None,
        end: DateTime | None,
        limit: int,
        offset: int,
        event_types: list[str] | None = None,
        text: str | None = None,
    ) -> dict:
        clauses = ["user_id = %s"]
        params: list[object] = [user_id]

        if start is not None:
            clauses.append("event_at >= %s")
            params.append(start)
        if end is not None:
            clauses.append("event_at < %s")
            params.append(end)
        if event_types:
            clauses.append("event_type = ANY(%s)")
            params.append(event_types)
        if text is not None:
            clauses.append(
                "to_tsvector('russian', name || ' ' || description) @@ plainto_tsquery('russian', %s)"
            )
            params.append(text)

        # Соединяются только постоянные SQL-фрагменты; значения всегда в params.
        query = f"SELECT {COLUMNS} FROM public.events WHERE " + " AND ".join(clauses)
        query += " ORDER BY event_at, id LIMIT %s OFFSET %s"
        params.extend((limit + 1, offset))

        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()

        return {
            "items": [_serialize(row) for row in rows[:limit]],
            "has_more": len(rows) > limit,
        }
