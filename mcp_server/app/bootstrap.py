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
            conn.execute("GRANT SELECT, INSERT, DELETE ON public.events TO assistant_app")
            conn.execute("GRANT UPDATE(event_at,status) ON public.events TO assistant_app")
            conn.execute("GRANT SELECT, INSERT ON public.event_operations TO assistant_app")
            conn.execute("GRANT SELECT, DELETE, UPDATE(state) ON public.reminder_deliveries TO assistant_app")
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = 'assistant_api'").fetchone():
                conn.execute(sql.SQL("CREATE ROLE assistant_api LOGIN PASSWORD {}").format(sql.Literal(api_password)))
            conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO assistant_api").format(sql.Identifier(settings.dbname)))
            conn.execute("GRANT USAGE ON SCHEMA public TO assistant_api")
            conn.execute("GRANT SELECT, INSERT, DELETE ON public.events TO assistant_api")
            conn.execute("GRANT UPDATE (status) ON public.events TO assistant_api")
            conn.execute("GRANT SELECT, INSERT ON public.user_profiles TO assistant_api")
            conn.execute("GRANT UPDATE (timezone, updated_at) ON public.user_profiles TO assistant_api")
            for role, env_name, writable in (("assistant_agent", "AGENT_DB_PASSWORD", False),
                                              ("assistant_bot", "BOT_DB_PASSWORD", True)):
                secret = os.environ.get(env_name, "")
                if len(secret) < 16:
                    raise ConfigError(env_name + ": minimum 16 characters")
                if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
                    conn.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(sql.Identifier(role), sql.Literal(secret)))
                conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(settings.dbname), sql.Identifier(role)))
                conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role)))
                conn.execute(sql.SQL("GRANT SELECT ON public.user_profiles TO {}").format(sql.Identifier(role)))
                if writable:
                    conn.execute("GRANT INSERT, UPDATE(timezone,updated_at) ON public.user_profiles TO assistant_bot")
                    conn.execute("GRANT SELECT ON public.events TO assistant_bot")
                    conn.execute("GRANT UPDATE(status) ON public.events TO assistant_bot")
                    conn.execute("GRANT SELECT,INSERT,UPDATE(state) ON public.reminder_deliveries TO assistant_bot")
        print("Docker-БД готова. assistant_app: MCP; assistant_api: API и профили. Миграции: " + (", ".join(completed) or "уже применены"))
        return 0
    except (ConfigError, MigrationError) as exc:
        print(str(exc), file=sys.stderr)
    except psycopg.Error:
        print("Настройка Docker-БД не завершена. Проверьте параметры и логи PostgreSQL; секреты скрыты.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
