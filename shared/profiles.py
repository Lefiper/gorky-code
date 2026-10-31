"""PostgreSQL is the only source of user timezones; never cache in SQLite."""
import os
from zoneinfo import ZoneInfo

import psycopg


def get_timezone(user_id, default=None):
    fallback = default or os.getenv("DEFAULT_TIMEZONE", "Europe/Moscow")
    with psycopg.connect() as conn:
        row = conn.execute("SELECT timezone FROM public.user_profiles WHERE user_id=%s",
                           (str(user_id),)).fetchone()
    value = row[0] if row else fallback
    ZoneInfo(value)
    return value


def set_timezone(user_id, value):
    ZoneInfo(value)
    with psycopg.connect() as conn:
        conn.execute("""INSERT INTO public.user_profiles(user_id, timezone) VALUES (%s,%s)
            ON CONFLICT(user_id) DO UPDATE SET timezone=excluded.timezone, updated_at=now()""",
                     (str(user_id), value))
