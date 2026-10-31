import os
import subprocess
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import psycopg
from psycopg import sql

from reminder_worker import dispatch_due


@unittest.skipUnless(os.getenv("ASSISTANT_RUN_DB_TESTS") == "1", "Requires PostgreSQL")
class DurableReminderTests(unittest.TestCase):
    def setUp(self):
        self.database = "reminder_test_" + uuid4().hex
        with psycopg.connect(dbname="postgres", autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 LOCALE_PROVIDER builtin BUILTIN_LOCALE 'C.UTF-8'").format(sql.Identifier(self.database)))
        self.environment = patch.dict(os.environ, {"PGDATABASE": self.database})
        self.environment.start()
        result = subprocess.run([sys.executable, "-m", "app.bootstrap"],
            cwd=Path(__file__).parents[2] / "mcp_server", capture_output=True, text=True)
        if result.returncode:
            self.fail(result.stdout + result.stderr)

    def tearDown(self):
        self.environment.stop()
        with psycopg.connect(dbname="postgres", autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(self.database)))

    def test_sent_reminder_survives_worker_restart_and_competing_scan(self):
        event_id = uuid4()
        name = "reminder:" + uuid4().hex
        with psycopg.connect() as conn:
            conn.execute("""INSERT INTO events(id,user_id,event_type,name,description,event_at,status)
                VALUES(%s,'918273','reminder',%s,'',now()-interval '1 second','pending')""", (event_id, name))
        api = Mock()
        with patch.dict(os.environ, {"PGUSER": "assistant_bot", "PGPASSWORD": os.environ["BOT_DB_PASSWORD"]}):
            dispatch_due(api)
            # New DB connections, no retained process state.
            dispatch_due(api)
        matches = [call for call in api.send.call_args_list if name in call.args[1]]
        self.assertEqual(len(matches), 1)
        with psycopg.connect() as conn:
            self.assertEqual(conn.execute("SELECT status FROM events WHERE id=%s", (event_id,)).fetchone()[0], "done")
            self.assertEqual(conn.execute("SELECT state FROM reminder_deliveries WHERE event_id=%s", (event_id,)).fetchone()[0], "sent")
