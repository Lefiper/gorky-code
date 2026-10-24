"""Однократная настройка Docker-БД: миграции и отдельная роль MCP без DELETE/DDL."""

import os
import sys

import psycopg
from psycopg import sql

from app.config import ConfigError, Settings
from app.db.connection import connect
from app.db.migrations import MigrationError, migrate


def main():
    try:
        settings = Settings.load()
        password = os.environ.get("APP_DB_PASSWORD", "")
        if len(password) < 16:
            raise ConfigError("APP_DB_PASSWORD должен содержать не менее 16 символов.")
        with connect(settings) as conn:
            completed = migrate(conn)
            # Блокировка migrate сохраняется до COMMIT и сериализует создание роли.
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = 'assistant_app'").fetchone():
                conn.execute(sql.SQL("CREATE ROLE assistant_app LOGIN PASSWORD {}").format(sql.Literal(password)))
            conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO assistant_app").format(sql.Identifier(settings.dbname)))
            conn.execute("GRANT USAGE ON SCHEMA public TO assistant_app")
            conn.execute("GRANT SELECT, INSERT ON public.events TO assistant_app")
        print("Docker-БД готова. Роль assistant_app: SELECT/INSERT событий. Миграции: " + (", ".join(completed) or "уже применены"))
        return 0
    except (ConfigError, MigrationError) as exc:
        print(str(exc), file=sys.stderr)
    except psycopg.Error:
        print("Настройка Docker-БД не завершена. Проверьте параметры и логи PostgreSQL; секреты скрыты.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
