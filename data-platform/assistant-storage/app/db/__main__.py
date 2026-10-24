"""Запуск: python -m app.db check или python -m app.db init."""

import argparse

import psycopg

from app.config import ConfigError, PROJECT_ROOT, Settings
from app.db.connection import connect
from app.db.migrations import MigrationError, migrate


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка БД и начальная схема")
    parser.add_argument("command", choices=("check", "init", "migrate"))
    parser.add_argument("--adopt-existing", action="store_true", help="Принять прежнюю events после точной проверки схемы")
    args = parser.parse_args()
    try:
        settings = Settings.load()
        # Контекст соединения делает COMMIT при успехе, ROLLBACK при ошибке
        # и закрывает соединение. Сообщение об успехе — после выхода из with.
        with connect(settings) as conn:
            if args.command == "migrate":
                completed = migrate(conn, adopt_existing=args.adopt_existing)
            elif args.command == "init":
                sql = (PROJECT_ROOT / "sql" / "001_create_events.sql").read_text(encoding="utf-8")
                conn.execute(sql)
            else:
                version = conn.execute("SHOW server_version").fetchone()["server_version"]
                exists = conn.execute("SELECT to_regclass('public.events') IS NOT NULL AS present").fetchone()["present"]
        if args.command == "migrate":
            print("Миграции: " + (", ".join(completed) if completed else "всё уже применено") + ". Транзакция завершена.")
        elif args.command == "init":
            print("Начальная схема создана; транзакция зафиксирована.")
        else:
            print(f"Соединение установлено. PostgreSQL {version}. Таблица events: {'есть' if exists else 'ещё не создана'}.")
        return 0
    except ConfigError as exc:
        print(f"Настройка: {exc}")
    except MigrationError as exc:
        print(f"Миграция отменена: {exc}")
    except psycopg.errors.DuplicateTable:
        print("Таблица уже существует. Схема не изменена; повторная инициализация не нужна.")
    except psycopg.OperationalError:
        print("Не удалось подключиться или завершить операцию. Проверьте службу PostgreSQL, параметры .env и права роли. Секреты не выводятся.")
    except psycopg.Error:
        print("PostgreSQL отклонил операцию; транзакция отменена. Проверьте права и существующую схему. Секреты не выводятся.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
