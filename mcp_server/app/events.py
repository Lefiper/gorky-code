"""Обычные Python-функции для событий. Здесь нет зависимости от MCP."""

from contextlib import contextmanager
from datetime import datetime as DateTime, timezone
from uuid import UUID, uuid4
import hashlib
import json
from psycopg.types.json import Jsonb

import psycopg

from app.config import Settings
from app.db.connection import connect

EVENT_TYPES = {"task", "reminder", "meeting", "project"}
COLUMNS = "id, user_id, event_type, name, description, event_at, created_at, status"


class ValidationError(ValueError):
    """Некорректные параметры запроса."""


class ConflictError(ValueError):
    """Ключ операции уже использован с другими данными."""


class StorageError(RuntimeError):
    """Безопасная ошибка хранилища без параметров подключения."""


def _text(value, field, maximum=None, allow_empty=False):
    if not isinstance(value, str):
        raise ValidationError(f"{field}: ожидается строка.")
    value = value.strip()
    if (not value and not allow_empty) or (maximum is not None and len(value) > maximum):
        raise ValidationError(f"{field}: пустое или слишком длинное значение.")
    return value


def _event_type(value):
    if not isinstance(value, str) or value not in EVENT_TYPES:
        raise ValidationError("event_type: допустимы task, reminder, meeting, project.")
    return value


def _event_types(value):
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= len(EVENT_TYPES):
        raise ValidationError("event_type: список типов или null.")
    return sorted({_event_type(item) for item in value})


def _time(value, field):
    if isinstance(value, str):
        # Внешний контракт требует дату и время, а не одну дату.
        if "T" not in value:
            raise ValidationError(f"{field}: нужен ISO 8601 с T и часовым смещением.")
        try:
            value = DateTime.fromisoformat(value)
        except ValueError:
            raise ValidationError(f"{field}: некорректная дата ISO 8601.") from None
    if not isinstance(value, DateTime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError(f"{field}: обязательно часовое смещение, например +03:00.")
    try:
        return value.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise ValidationError(f"{field}: дата вне допустимого диапазона.") from None


def _range(start_time, end_time, required=False):
    if required and (start_time is None or end_time is None):
        raise ValidationError("Укажите start_time и end_time.")
    start = _time(start_time, "start_time") if start_time is not None else None
    end = _time(end_time, "end_time") if end_time is not None else None
    if start is not None and end is not None and start >= end:
        raise ValidationError("start_time должен быть раньше end_time.")
    return start, end


def _pagination(limit, offset):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValidationError("limit: целое число от 1 до 100.")
    if type(offset) is not int or offset < 0 or offset > 9223372036854775807:
        raise ValidationError("offset: неотрицательное целое число в диапазоне bigint.")


def _serialize(row):
    result = dict(row)
    result["id"] = str(result["id"])
    for field in ("event_at", "created_at"):
        result[field] = result[field].astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return result


class EventService:
    columns = COLUMNS
    def __init__(self, settings: Settings):
        self.settings = settings

    @contextmanager
    def _connection(self):
        try:
            with connect(self.settings) as conn:
                yield conn
        except psycopg.Error:
            # Не передаём наружу сообщение драйвера: оно может содержать настройки.
            raise StorageError("Не удалось выполнить операцию с PostgreSQL.") from None

    def create_event(self, user_id, event_type, name, datetime, description="", idempotency_key=None):
        user_id = _text(user_id, "user_id")
        event_type = _event_type(event_type)
        name = _text(name, "name", 200)
        description = _text(description, "description", 10000, allow_empty=True)
        event_at = _time(datetime, "datetime")
        key = _text(idempotency_key, "idempotency_key", 200) if idempotency_key is not None else None
        with self._connection() as conn:
            fingerprint = hashlib.sha256(json.dumps([user_id,event_type,name.casefold(),description,event_at.isoformat()], ensure_ascii=False).encode()).hexdigest()
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("create:" + fingerprint,))
            if key is not None:
                previous = conn.execute(f"SELECT {COLUMNS} FROM public.events WHERE user_id=%s AND idempotency_key=%s", (user_id,key)).fetchone()
                if previous:
                    if (previous["event_type"],previous["name"],previous["description"],previous["event_at"]) != (event_type,name,description,event_at):
                        raise ConflictError("idempotency_key уже использован с другими данными.")
                    return {"event": _serialize(previous), "created": False}
            previous = conn.execute(f"SELECT {COLUMNS} FROM public.events WHERE user_id=%s AND event_type=%s AND lower(name)=lower(%s) AND description=%s AND event_at=%s ORDER BY created_at,id LIMIT 1", (user_id,event_type,name,description,event_at)).fetchone()
            if previous and key is not None:
                return {"event": _serialize(previous), "created": False}
            row = conn.execute(
                f"""INSERT INTO public.events
                (id, user_id, event_type, name, description, event_at, idempotency_key)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, idempotency_key) DO NOTHING
                RETURNING {COLUMNS}""",
                (uuid4(), user_id, event_type, name, description, event_at, key),
            ).fetchone()
            created = row is not None
            if not created:
                # Отдельный SELECT при READ COMMITTED видит победивший конкурентный INSERT.
                row = conn.execute(
                    f"SELECT {COLUMNS} FROM public.events WHERE user_id = %s AND idempotency_key = %s",
                    (user_id, key),
                ).fetchone()
                if row is None:
                    raise StorageError("Не удалось прочитать результат повторной операции.")
                if (row["event_type"], row["name"], row["description"], row["event_at"]) != (
                    event_type, name, description, event_at
                ):
                    raise ConflictError("idempotency_key уже использован с другими данными.")
        # COMMIT завершён: только теперь сообщаем об успехе.
        return {"event": _serialize(row), "created": created}

    def _select(self, user_id, start, end, limit, offset, event_type=None, text=None):
        clauses = ["user_id = %s"]
        params = [user_id]
        if start is not None:
            clauses.append("event_at >= %s")
            params.append(start)
        if end is not None:
            clauses.append("event_at < %s")
            params.append(end)
        if event_type is not None:
            clauses.append("event_type = ANY(%s)")
            params.append(event_type)
        if text is not None:
            clauses.append("to_tsvector('russian', name || ' ' || description) @@ plainto_tsquery('russian', %s)")
            params.append(text)
        # Здесь соединяются только постоянные SQL-фрагменты. Значения всегда в params.
        query = f"SELECT {self.columns} FROM public.events WHERE " + " AND ".join(clauses)
        query += " ORDER BY event_at, id LIMIT %s OFFSET %s"
        params.extend((limit + 1, offset))
        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            if text is not None:
                # Probe with offset zero so pagination cannot switch query semantics.
                probe = list(params)
                probe[-2:] = [1, 0]
                if not conn.execute(query, probe).fetchone():
                    fallback = query.replace("plainto_tsquery('russian', %s)",
                        "to_tsquery('russian', array_to_string(tsvector_to_array(to_tsvector('russian', %s)), ' | '))")
                    rows = conn.execute(fallback, params).fetchall()

        return {"items": [_serialize(row) for row in rows[:limit]], "has_more": len(rows) > limit}

    def get_event(self, user_id, start_time, end_time, event_type=None, limit=100, offset=0):
        user_id = _text(user_id, "user_id")
        start, end = _range(start_time, end_time, required=True)
        event_type = _event_types(event_type)
        _pagination(limit, offset)
        return self._select(user_id, start, end, limit, offset, event_type=event_type)

    def get_event_by_query(self, user_id, text, start_time=None, end_time=None, limit=100, offset=0):
        user_id = _text(user_id, "user_id")
        text = _text(text, "text", 1000)
        start, end = _range(start_time, end_time)
        _pagination(limit, offset)
        return self._select(user_id, start, end, limit, offset, text=text)

    def _mutate(self, action, user_id, event_id, datetime=None, idempotency_key=None):
        user_id = _text(user_id, "user_id")
        try:
            event_id = str(UUID(event_id))
        except (ValueError, TypeError, AttributeError):
            raise ValidationError("event_id: ожидается UUID.") from None
        new_time = _time(datetime, "datetime") if action == "reschedule" else None
        key = _text(idempotency_key, "idempotency_key", 200) if idempotency_key is not None else str(uuid4())
        payload = {"datetime": new_time.isoformat() if new_time else None}
        with self._connection() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("mutation:" + user_id + ":" + key,))
            previous = conn.execute("SELECT action,event_id,payload,result FROM public.event_operations WHERE user_id=%s AND idempotency_key=%s", (user_id, key)).fetchone()
            if previous:
                if previous["action"] != action or str(previous["event_id"]) != event_id or previous["payload"] != payload:
                    raise ConflictError("Ключ операции уже использован с другими параметрами.")
                return previous["result"]
            row = conn.execute(f"SELECT {COLUMNS} FROM public.events WHERE id=%s AND user_id=%s FOR UPDATE", (event_id, user_id)).fetchone()
            if row is None:
                raise ValidationError("Событие не найдено.")
            if action == "delete":
                conn.execute("DELETE FROM public.events WHERE id=%s AND user_id=%s", (event_id, user_id))
                result = {"deleted": True, "event": _serialize(row)}
            else:
                # Do not race an uncertain external reminder delivery.
                delivery = conn.execute("SELECT state FROM public.reminder_deliveries WHERE event_id=%s FOR UPDATE", (event_id,)).fetchone()
                if delivery and delivery["state"] == "inflight":
                    raise ConflictError("Напоминание сейчас отправляется. Повторите перенос позже.")
                conn.execute("DELETE FROM public.reminder_deliveries WHERE event_id=%s", (event_id,))
                row = conn.execute(f"UPDATE public.events SET event_at=%s, status=CASE WHEN event_type='reminder' THEN 'pending' ELSE status END WHERE id=%s AND user_id=%s RETURNING {COLUMNS}", (new_time, event_id, user_id)).fetchone()
                result = {"updated": True, "event": _serialize(row)}
            conn.execute("INSERT INTO public.event_operations(user_id,idempotency_key,action,event_id,payload,result) VALUES (%s,%s,%s,%s,%s,%s)", (user_id,key,action,event_id,Jsonb(payload),Jsonb(result)))
        return result

    def delete_event(self, user_id, event_id, idempotency_key=None):
        return self._mutate("delete", user_id, event_id, idempotency_key=idempotency_key)

    def update_event_time(self, user_id, event_id, datetime, idempotency_key=None):
        return self._mutate("reschedule", user_id, event_id, datetime, idempotency_key)
