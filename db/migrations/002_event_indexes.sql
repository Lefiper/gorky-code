-- Равенство user_id, диапазон времени, стабильная сортировка (event_at, id).
CREATE INDEX events_user_time_idx ON public.events (user_id, event_at, id);

-- Для запросов с дополнительным равенством event_type перед диапазоном времени.
CREATE INDEX events_user_type_time_idx ON public.events (user_id, event_type, event_at, id);

-- Выражение совпадает с запросом в app/events.py, включая конфигурацию russian.
CREATE INDEX events_search_gin_idx ON public.events
    USING GIN (to_tsvector('russian', name || ' ' || description));
