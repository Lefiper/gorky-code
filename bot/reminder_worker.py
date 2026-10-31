"""Durable reminder dispatch with PostgreSQL row locks and a stable delivery key.

An uncertain remote result is held for manual reconciliation, never blindly retried.
Exactly-once delivery across HTTP and SQL requires receiver-side idempotency.
"""
import logging

import psycopg
from psycopg.rows import dict_row

LOG = logging.getLogger("max_bot")


def dispatch_due(api):
    with psycopg.connect(row_factory=dict_row) as conn:
        rows = conn.execute("""SELECT id,user_id,name,description FROM public.events
            WHERE event_type='reminder' AND status='pending' AND event_at<=now()
            AND NOT EXISTS (SELECT 1 FROM public.reminder_deliveries d
                            WHERE d.event_id=events.id AND d.state IN ('inflight','sent'))
            ORDER BY event_at,id FOR UPDATE SKIP LOCKED LIMIT 20""").fetchall()
        for row in rows:
            # Commit the durable claim before making an irreversible external call.
            conn.execute("INSERT INTO public.reminder_deliveries(event_id,state) VALUES (%s,'sending') ON CONFLICT DO NOTHING",
                         (row['id'],))
        conn.commit()
    for row in rows:
        with psycopg.connect() as conn:
            claimed = conn.execute("""UPDATE public.reminder_deliveries SET state='inflight'
                WHERE event_id=%s AND state='sending'
                AND EXISTS (SELECT 1 FROM public.events e WHERE e.id=event_id AND e.status='pending') RETURNING event_id""", (row['id'],)).fetchone()
        if not claimed:
            continue
        try:
            api.send(int(row['user_id']), "Напоминание: " + row['name'])
        except Exception as exc:
            LOG.warning("reminder_delivery_uncertain event_id=%s type=%s", row['id'], type(exc).__name__)
            # Keep inflight on ambiguous failure; an operator can reconcile with MAX.
            continue
        with psycopg.connect() as conn:
            conn.execute("UPDATE public.events SET status='done' WHERE id=%s", (row['id'],))
            conn.execute("UPDATE public.reminder_deliveries SET state='sent' WHERE event_id=%s", (row['id'],))
