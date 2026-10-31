"""Prevent independent API and MCP SQL implementations from drifting."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from uuid import uuid4

from app.config import Settings
from app.events import EventService


@unittest.skipUnless(os.getenv("ASSISTANT_RUN_DB_TESTS") == "1", "Requires PostgreSQL")
class APIParityTests(unittest.TestCase):
    def test_shared_creation_and_search_semantics(self):
        service = EventService(Settings.load())
        user = "test:parity:" + uuid4().hex
        event = service.create_event(user, "project", "Врач", "2030-01-02T15:00:00+03:00",
                                     description="Осмотр", idempotency_key="parity")["event"]
        # AND fails, OR fallback must return the same event in both implementations.
        expected = service.get_event_by_query(user, "врач несуществующий")
        self.assertEqual([e["id"] for e in expected["items"]], [event["id"]])
        code = '''import json,sys
import os
from app.storage import EventRepository,PgConfig
repo=EventRepository(PgConfig(host=os.environ["PGHOST"],port=int(os.environ["PGPORT"]),
    dbname=os.environ["PGDATABASE"],user=os.environ["PGUSER"],password=os.environ["PGPASSWORD"]));repo.open()
try:
 print(json.dumps(repo.search_events(sys.argv[1],"врач несуществующий")))
finally:
 repo.close()
'''
        result = subprocess.run([sys.executable, "-c", code, user],
            cwd=(Path(__file__).parents[1] / "api" if (Path(__file__).parents[1] / "api").exists() else Path(__file__).parents[2] / "api"), env=os.environ | {
                "PGUSER": "assistant_api", "PGPASSWORD": os.environ["API_DB_PASSWORD"]},
            capture_output=True, text=True, encoding="utf-8", check=True)
        actual = json.loads(result.stdout)
        for item in actual["items"]:
            item.pop("duration_minutes")
        self.assertEqual(actual, expected)
