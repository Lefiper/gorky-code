"""Функции хранилища для HTTP API команды. Маршруты HTTP здесь не реализуются.

MCP-интерфейс сохранён. API использует отдельную роль assistant_api.
"""

from datetime import date as Date, time as Time, datetime as DateTime, timezone as UTCZone
import re
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.events import (
    COLUMNS, ConflictError, EventService, StorageError, ValidationError,
    _pagination, _range, _serialize, _text, _time,
)

API_EVENT_TYPES = {"task", "reminder", "meeting", "project"}
API_STATUSES = {"pending", "new", "progress", "done", "blocked", "cancelled"}
API_COLUMNS = COLUMNS + ", duration_minutes"


def _choice(value, allowed, field):
    if not isinstance(value, str) or value not in allowed:
        raise ValidationError(f"{field}: допустимы " + ", ".join(sorted(allowed)))
    return value


def _uuid(value):
    if not isinstance(value, str):
        raise ValidationError("event_id: нужна строка UUID, а не числовой ID.")
    try:
        return UUID(value)
    except ValueError:
        raise ValidationError("event_id: некорректный UUID.") from None


def local_datetime_to_iso(date, time, timezone):
    """Без угадывания несуществующего/двойного времени при переходах DST."""
    try:
        if not isinstance(date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise ValueError
        if not isinstance(time, str) or not re.fullmatch(r"\d{2}:\d{2}(:\d{2})?", time):
            raise ValueError
        naive = DateTime.combine(Date.fromisoformat(date), Time.fromisoformat(time))
        zone = ZoneInfo(timezone)
        candidates = set()
        for fold in (0, 1):
            utc = naive.replace(tzinfo=zone, fold=fold).astimezone(UTCZone.utc)
            if utc.astimezone(zone).replace(tzinfo=None) == naive:
                candidates.add(utc)
    except (ValueError, TypeError, ZoneInfoNotFoundError, OverflowError):
        raise ValidationError("Проверьте date, time и IANA timezone.") from None
    if len(candidates) != 1:
        raise ValidationError("Местное время неоднозначно или не существует из-за смены часового пояса. Уточните время/смещение.")
    return candidates.pop().isoformat().replace("+00:00", "Z")


class APIEventService(EventService):
    columns = API_COLUMNS

    def create_event(self, user_id, event_type, name, datetime, description="", idempotency_key=None,
                     *, duration_minutes=None, status="new"):
        user_id = _text(user_id, "user_id")
        event_type = _choice(event_type, API_EVENT_TYPES, "event_type")
        status = _choice(status, API_STATUSES, "status")
        name = _text(name, "name", 200)
        description = _text(description, "description", 10000, allow_empty=True)
        event_at = _time(datetime, "datetime")
        if duration_minutes is not None and (type(duration_minutes) is not int or not 1 <= duration_minutes <= 2147483647):
            raise ValidationError("duration_minutes: положительное целое число минут или null.")
        key = _text(idempotency_key, "idempotency_key", 200) if idempotency_key is not None else None
        with self._connection() as conn:
            row = conn.execute(f"""INSERT INTO public.events
                (id, user_id, event_type, name, description, event_at, idempotency_key, duration_minutes, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, idempotency_key) DO NOTHING RETURNING {API_COLUMNS}""",
                (uuid4(), user_id, event_type, name, description, event_at, key, duration_minutes, status)).fetchone()
            created = row is not None
            if not created:
                row = conn.execute(f"SELECT {API_COLUMNS} FROM public.events WHERE user_id=%s AND idempotency_key=%s",
                                   (user_id, key)).fetchone()
                if row is None:
                    raise StorageError("Не удалось прочитать результат повторной операции.")
                if (row["event_type"], row["name"], row["description"], row["event_at"], row["duration_minutes"], row["status"]) != (
                    event_type, name, description, event_at, duration_minutes, status
                ):
                    raise ConflictError("idempotency_key уже использован с другими данными или событие изменилось.")
        return {"event": _serialize(row), "created": created}

    def get_event(self, user_id, start_time, end_time, event_type=None, limit=100, offset=0):
        user_id = _text(user_id, "user_id")
        start, end = _range(start_time, end_time, required=True)
        if event_type is not None:
            event_type = _choice(event_type, API_EVENT_TYPES, "event_type")
        _pagination(limit, offset)
        return self._select(user_id, start, end, limit, offset, event_type=event_type)

    def update_event_status(self, user_id, event_id, status):
        user_id = _text(user_id, "user_id")
        event_id = _uuid(event_id)
        status = _choice(status, API_STATUSES, "status")
        with self._connection() as conn:
            row = conn.execute(f"""UPDATE public.events SET status=%s
                WHERE user_id=%s AND id=%s RETURNING {API_COLUMNS}""", (status, user_id, event_id)).fetchone()
        return _serialize(row) if row is not None else None

    def delete_event(self, user_id, event_id):
        """Вызывается backend после авторизации; чужой или отсутствующий ID → False."""
        user_id = _text(user_id, "user_id")
        event_id = _uuid(event_id)
        with self._connection() as conn:
            row = conn.execute("DELETE FROM public.events WHERE user_id=%s AND id=%s RETURNING id",
                               (user_id, event_id)).fetchone()
        return row is not None

    def set_user_timezone(self, user_id, timezone):
        user_id = _text(user_id, "user_id")
        timezone = _text(timezone, "timezone", 100)
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValidationError("timezone: нужен IANA-пояс, например Europe/Moscow.") from None
        with self._connection() as conn:
            row = conn.execute("""INSERT INTO public.user_profiles (user_id, timezone) VALUES (%s, %s)
                ON CONFLICT (user_id) DO UPDATE SET timezone=EXCLUDED.timezone, updated_at=now()
                RETURNING user_id, timezone""", (user_id, timezone)).fetchone()
        return dict(row)

    def get_user_timezone(self, user_id):
        user_id = _text(user_id, "user_id")
        with self._connection() as conn:
            row = conn.execute("SELECT timezone FROM public.user_profiles WHERE user_id=%s", (user_id,)).fetchone()
        return row["timezone"] if row is not None else None

    def resolve_local_datetime(self, user_id, date, time):
        timezone = self.get_user_timezone(user_id)
        if timezone is None:
            raise ValidationError("Часовой пояс пользователя неизвестен. Синхронизируйте его из бота или уточните у пользователя.")
        return local_datetime_to_iso(date, time, timezone)
