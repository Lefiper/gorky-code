-- Применяется целиком в транзакции через python -m app.db init.
-- Без IF NOT EXISTS: несовместимую существующую таблицу нельзя молча принять.
CREATE TABLE public.events (
    id uuid PRIMARY KEY,
    user_id text NOT NULL CHECK (length(btrim(user_id)) > 0),
    event_type text NOT NULL CHECK (event_type IN ('task', 'reminder', 'meeting')),
    name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 200),
    description text NOT NULL DEFAULT '' CHECK (length(description) <= 10000),
    event_at timestamptz NOT NULL CHECK (isfinite(event_at)),
    created_at timestamptz NOT NULL DEFAULT now(),
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'done', 'cancelled')),
    idempotency_key text CHECK (length(btrim(idempotency_key)) BETWEEN 1 AND 200),
    CONSTRAINT events_user_idempotency_unique UNIQUE (user_id, idempotency_key)
);

-- NULL-ключи разрешают независимые операции с одинаковыми данными.
-- Индексы для чтения и полнотекстового поиска добавим после проверки запросов.
