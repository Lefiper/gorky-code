CREATE TABLE public.event_operations (
    user_id text NOT NULL,
    idempotency_key text NOT NULL,
    action text NOT NULL CHECK (action IN ('delete','reschedule')),
    event_id uuid NOT NULL,
    payload jsonb NOT NULL,
    result jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, idempotency_key)
);
