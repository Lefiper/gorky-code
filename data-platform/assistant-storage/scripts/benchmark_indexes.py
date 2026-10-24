"""EXPLAIN ANALYZE на временной таблице, без изменения настоящих событий."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics

from app.config import PROJECT_ROOT, Settings
from app.db.connection import connect


def measure(conn, query, args):
    runs = []
    for _ in range(3):
        row = conn.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query, args).fetchone()
        plan = row["QUERY PLAN"][0]
        runs.append(plan["Execution Time"])
    return {"median_execution_ms": statistics.median(runs), "execution_ms": runs, "plan": plan}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="docs/reports/index_plans.json")
    parser.add_argument("--rows", type=int, default=100000)
    args = parser.parse_args()
    if not 10000 <= args.rows <= 500000:
        parser.error("rows: 10000–500000")
    report = {"kind": "synthetic temporary-table benchmark; not production measurements",
              "created_at": datetime.now(timezone.utc).isoformat(), "rows": args.rows,
              "users": 100, "repetitions": 3, "forced_plans": False}
    with connect(Settings.load()) as conn:
        conn.execute("SET LOCAL statement_timeout = '120s'")
        schema = (PROJECT_ROOT / "sql/001_create_events.sql").read_text(encoding="utf-8")
        schema = schema.replace("CREATE TABLE public.events (", "CREATE TEMP TABLE bench_events (", 1)
        schema = schema.replace("\n);", "\n) ON COMMIT DROP;", 1)
        conn.execute(schema)
        conn.execute("""INSERT INTO bench_events (id, user_id, event_type, name, description, event_at)
            SELECT gen_random_uuid(), 'bench:user:' || (i %% 100)::text,
              CASE i %% 3 WHEN 0 THEN 'task' WHEN 1 THEN 'meeting' ELSE 'reminder' END,
              CASE WHEN i %% 997 = 0 THEN 'Презентация проекта' ELSE 'Рабочая задача ' || i END,
              CASE WHEN i %% 991 = 0 THEN 'Материалы для презентации команды' ELSE 'Плановая работа' END,
              timestamptz '2030-01-01T00:00:00Z' + (i / 100) * interval '1 hour'
            FROM generate_series(1, %s) AS i""", (args.rows,))
        conn.execute("ANALYZE bench_events")
        projection = "id, user_id, event_type, name, description, event_at, created_at, status"
        period = "SELECT " + projection + " FROM bench_events WHERE user_id=%s AND event_at >= %s AND event_at < %s"
        queries = {
            "period": (period + " ORDER BY event_at, id LIMIT 101", ("bench:user:42", "2030-01-10T00:00:00Z", "2030-01-11T00:00:00Z")),
            "typed_period": (period + " AND event_type=%s ORDER BY event_at, id LIMIT 101", ("bench:user:42", "2030-01-10T00:00:00Z", "2030-01-11T00:00:00Z", "meeting")),
            "russian_search": ("SELECT " + projection + " FROM bench_events WHERE user_id=%s AND to_tsvector('russian', name || ' ' || description) @@ plainto_tsquery('russian', %s) ORDER BY event_at, id LIMIT 101", ("bench:user:42", "презентации")),
        }
        report["server_version"] = conn.execute("SHOW server_version").fetchone()["server_version"]
        report["before"] = {name: measure(conn, query, params) for name, (query, params) in queries.items()}
        migration = (PROJECT_ROOT / "sql/002_event_indexes.sql").read_text(encoding="utf-8")
        conn.execute(migration.replace("public.events", "bench_events"))
        conn.execute("ANALYZE bench_events")
        report["after"] = {name: measure(conn, query, params) for name, (query, params) in queries.items()}
        report["index_sizes"] = conn.execute("""SELECT indexrelname AS name, pg_relation_size(indexrelid) AS bytes
            FROM pg_stat_all_indexes WHERE relid = 'pg_temp.bench_events'::regclass ORDER BY indexrelname""").fetchall()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for name in queries:
        print(f"{name}: median {report['before'][name]['median_execution_ms']:.3f} → {report['after'][name]['median_execution_ms']:.3f} ms (synthetic)")
    print("Report:", output)


if __name__ == "__main__":
    main()
