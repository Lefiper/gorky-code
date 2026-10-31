"""Транзакционные миграции с контрольными суммами и защитой от параллельного запуска."""

import hashlib

from app.config import MIGRATIONS_DIR


class MigrationError(RuntimeError):
    pass


def _shape(conn, relation):
    columns = conn.execute("""
        SELECT a.attname, format_type(a.atttypid, a.atttypmod) AS type,
               a.attnotnull, COALESCE(pg_get_expr(d.adbin, d.adrelid), '') AS default_expr
        FROM pg_attribute a LEFT JOIN pg_attrdef d
          ON d.adrelid = a.attrelid AND d.adnum = a.attnum
        WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped
        ORDER BY a.attnum
    """, (relation,)).fetchall()
    constraints = conn.execute("""
        SELECT contype, pg_get_constraintdef(oid) AS definition
        FROM pg_constraint WHERE conrelid = %s::regclass
        ORDER BY contype, pg_get_constraintdef(oid)
    """, (relation,)).fetchall()
    return columns, constraints


def migrate(conn, adopt_existing=False):
    """Вызывается внутри транзакции; при любом сбое вся текущая пачка откатывается."""
    conn.execute("SELECT pg_advisory_xact_lock(721194003)")
    conn.execute("""CREATE TABLE IF NOT EXISTS public.schema_migrations (
        version text PRIMARY KEY, checksum text NOT NULL,
        applied_at timestamptz NOT NULL DEFAULT now()
    )""")
    applied = {row["version"]: row["checksum"] for row in conn.execute(
        "SELECT version, checksum FROM public.schema_migrations"
    ).fetchall()}
    files = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))
    if set(applied) - {path.name for path in files}:
        raise MigrationError("В БД есть неизвестные миграции; запуск остановлен.")
    completed = []
    for path in files:
        raw = path.read_bytes()
        # Один checksum и для Windows CRLF, и для Linux LF.
        source = raw.decode("utf-8-sig").replace("\r\n", "\n")
        checksum = hashlib.sha256(source.encode("utf-8")).hexdigest()
        if path.name in applied:
            if applied[path.name] != checksum:
                raise MigrationError("Применённая миграция изменена: " + path.name)
            continue
        exists = conn.execute("SELECT to_regclass('public.events') IS NOT NULL AS present").fetchone()["present"]
        if path.name == "001_create_events.sql" and exists:
            if not adopt_existing:
                raise MigrationError("Таблица events уже существует без истории миграций. Для нашей прежней схемы используйте migrate --adopt-existing.")
            reference = source.replace("CREATE TABLE public.events (", "CREATE TEMP TABLE migration_expected_events (", 1)
            reference = reference.replace("\n);", "\n) ON COMMIT DROP;", 1)
            conn.execute(reference)
            if _shape(conn, "public.events") != _shape(conn, "pg_temp.migration_expected_events"):
                raise MigrationError("Существующая events отличается от исходной схемы. Автоматическое принятие отменено.")
        else:
            conn.execute(source)
        conn.execute("INSERT INTO public.schema_migrations (version, checksum) VALUES (%s, %s)", (path.name, checksum))
        completed.append(path.name)
    return completed
