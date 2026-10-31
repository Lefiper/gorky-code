# Индексы PostgreSQL

Миграции 001–003 сохранены; 004 добавляет журнал доставки напоминаний и частичный индекс событий reminder/pending.

- events_search_gin_idx — GIN по to_tsvector('russian', name || ' ' || description).
- events_user_time_idx — user_id, event_at, id.
- events_user_type_time_idx — user_id, event_type, event_at, id.
- events_pending_reminders_idx — event_at, id для reminder/pending.

Поиск сначала использует plainto_tsquery (AND). Если в пользовательском периоде нет ни одного результата (проверка с offset=0), выполняется OR через нормализованные русские лексемы. Обе ветви используют то же GIN-выражение. Пагинация не переключает режим поиска на последующих страницах.

scripts/benchmark_indexes.py запускается из mcp_server и проверяет планы на временной таблице с 100000 событий без принуждения планировщика. Фактический результат текущей проверки — в STATUS.md и приложенном отчёте. Это синтетические замеры, не SLA.
