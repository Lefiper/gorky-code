CREATE TABLE public.reminder_deliveries (
    event_id uuid PRIMARY KEY REFERENCES public.events(id) ON DELETE CASCADE,
    state text NOT NULL CHECK(state IN ('sending','inflight','sent')),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX events_pending_reminders_idx ON public.events(event_at,id)
    WHERE event_type='reminder' AND status='pending';
