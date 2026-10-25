-- Расширяем модель без переименования полей и без изменения существующих записей.
ALTER TABLE public.events DROP CONSTRAINT events_event_type_check;
ALTER TABLE public.events ADD CONSTRAINT events_event_type_check
    CHECK (event_type IN ('task', 'reminder', 'meeting', 'project'));

ALTER TABLE public.events DROP CONSTRAINT events_status_check;
ALTER TABLE public.events ADD CONSTRAINT events_status_check
    CHECK (status IN ('pending', 'new', 'progress', 'done', 'blocked', 'cancelled'));

ALTER TABLE public.events ADD COLUMN duration_minutes integer
    CHECK (duration_minutes > 0);

-- Без default: неизвестный пояс нельзя молча подменить московским.
CREATE TABLE public.user_profiles (
    user_id text PRIMARY KEY CHECK (length(btrim(user_id)) > 0),
    timezone text NOT NULL CHECK (length(timezone) BETWEEN 1 AND 100),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Проверяем и прямые SQL-записи, а не только Python-вызовы.
CREATE FUNCTION public.validate_profile_timezone() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_timezone_names WHERE name = NEW.timezone) THEN
        RAISE EXCEPTION 'Unknown timezone' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER user_profiles_validate_timezone
    BEFORE INSERT OR UPDATE OF timezone ON public.user_profiles
    FOR EACH ROW EXECUTE FUNCTION public.validate_profile_timezone();
