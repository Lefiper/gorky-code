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
        api_password = os.environ.get("API_DB_PASSWORD", "")
        if len(password) < 16 or len(api_password) < 16:
            raise ConfigError("APP_DB_PASSWORD и API_DB_PASSWORD должны содержать не менее 16 символов. Запустите обновлённый start-скрипт.")
        with connect(settings) as conn:
            completed = migrate(conn)
            # Блокировка migrate сохраняется до COMMIT и сериализует создание роли.
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = 'assistant_app'").fetchone():
                conn.execute(sql.SQL("CREATE ROLE assistant_app LOGIN PASSWORD {}").format(sql.Literal(password)))
            conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO assistant_app").format(sql.Identifier(settings.dbname)))
            conn.execute("GRANT USAGE ON SCHEMA public TO assistant_app")
            conn.execute("GRANT SELECT, INSERT ON public.events TO assistant_app")
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = 'assistant_api'").fetchone():
                conn.execute(sql.SQL("CREATE ROLE assistant_api LOGIN PASSWORD {}").format(sql.Literal(api_password)))
            conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO assistant_api").format(sql.Identifier(settings.dbname)))
            conn.execute("GRANT USAGE ON SCHEMA public TO assistant_api")
            conn.execute("GRANT SELECT, INSERT, DELETE ON public.events TO assistant_api")
            conn.execute("GRANT UPDATE (status) ON public.events TO assistant_api")
            conn.execute("GRANT SELECT, INSERT ON public.user_profiles TO assistant_api")
            conn.execute("GRANT UPDATE (timezone, updated_at) ON public.user_profiles TO assistant_api")
        print("Docker-БД готова. assistant_app: MCP; assistant_api: API и профили. Миграции: " + (", ".join(completed) or "уже применены"))
        return 0
    except (ConfigError, MigrationError) as exc:
        print(str(exc), file=sys.stderr)
    except psycopg.Error:
        print("Настройка Docker-БД не завершена. Проверьте параметры и логи PostgreSQL; секреты скрыты.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
