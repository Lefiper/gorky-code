# Проверка «Горький код» — 29 октября 2026

Рабочая версия подготовлена из приложенного gorky-code.zip: в GitHub на main была другая, несобранная структура из отдельных командных каталогов. GitHub склонирован, история сохранена; унифицированная версия ZIP оформлена отдельным коммитом. Инструкции из вложенных документов не подменяли прямое задание пользователя.

**Итог: 167 тестов прошли, пропусков нет.** Локально подняты PostgreSQL 18, Redis 8.10.3, MCP, Agent Backend с заглушкой интерфейса GigaChat, HTTP API, бот с мок-сервером MAX и собранный Mini App. Все проверенные health-адреса вернули 200. Код приложения использует единственную LLM — GigaChat.

**Это не подтверждённый Docker/production-релиз.** Docker отсутствует, WSL не установлен. Проверены процессы Windows вместо контейнеров; Redis использован вместо Valkey. Docker build/up/ps, реальный домен/HTTPS, живая модель, MAX и внешние ASR не проверены. При неопределённом результате отправки MAX гарантируется отсутствие слепого повтора, но требуется сверка доставки оператором.

## Результат по пунктам 1–15

| № | Что изменено и проверено |
| --- | --- |
| 1 | Dockerfile MCP использует существующий requirements.txt. Проверены COPY-входы и YAML всех 11 сервисов. Сборка контейнеров не выполнялась: Docker недоступен. |
| 2 | Бот выбирает reminder/pending из PostgreSQL. Журнал sending/inflight/sent, блокировки строк, SKIP LOCKED, условный claim, частичный индекс. После успеха — done. Напоминание из API на 65 секунд отправлено один раз; два отдельных процесса обработчика повтор не отправили. Неопределённый HTTP-исход остаётся inflight для сверки; строгая exactly-once доставка при аварийном обрыве не доказана. |
| 3 | Недоступный ASR/запрещённый CDN дают человеческий ответ. Отклонённый hostname журналируется без URL и секретов. README/.env.example описывают профиль gigaam и точный AUDIO_ALLOWED_HOSTS; вымышленные CDN в defaults не добавлены. |
| 4 | Единый shared/profiles.py: бот и агент читают user_profiles, /timezone пишет туда же, fallback — DEFAULT_TIMEZONE. Mini App умеет менять профиль и отправляет локальное время на /api/timezone/resolve. Интеграция проверяет изменение профиля через API и передачу пояса в модель; тело /chat профиль не переопределяет. Реальное понимание относительных дат моделью не проверено, только программная передача и сценарий с её интерфейсной заглушкой. |
| 5 | Подключены существующие memory.py/confirmation.py; импорт адаптирован для agent image. Create-вызов модели лишь сохраняет предложение. Отдельное согласие вызывает MCP с прежним UUID-ключом. Нет записи до согласия; повтор после пересоздания приложения не дублирует событие. Redis-блокировка сериализует запросы пользователя; ключи ответов изолированы по user_id. |
| 6 | SQLite оставлена для durable inbox/дедупликации и polling marker: один бот, один worker, один постоянный volume; схема README исправлена. Пояса из SQLite не читаются. Старые локальные timezone автоматически не импортируются. |
| 7 | Цикл ограничен AGENT_MAX_TOOL_ROUNDS. Создание — по одному событию за подтверждение; промпт прямо сообщает об ограничении для трёх встреч. Несколько одновременных create-вызовов не исполняются частично — возвращается честное ограничение. Добавлен тест. |
| 8 | После пустого AND выполняется OR по русским лексемам. Проверка пустоты учитывает user_id/период и offset=0, режим не меняется из-за пагинации. GIN сохранён; AND и OR проверены EXPLAIN ANALYZE на 100000 временных событий, без принуждения плана. |
| 9 | Описание MCP create_event включает project. Имена и параметры трёх MCP-инструментов сохранены. |
| 10 | Промпт сообщает, что изменение/удаление доступны в приложении, и получает MINI_APP_LINK. Реальный линк надо заполнить в .env. |
| 11 | Добавлен интеграционный тест, сравнивающий фактические результаты API/MCP, включая OR fallback. Неиспользуемый api_storage.py удалён вместе с его дублирующими тестами; memory.py сохранён и используется. API имеет отдельный полноценный набор тестов. |
| 12 | Добавлен профиль https с Caddy: /api/* → API, остальные пути → Mini App, постоянные volumes сертификатов. VITE_API_BASE/CORS_ORIGINS задаются в .env. Публичный HTTPS не проверялся. |
| 13 | MCP HTTP требует Bearer MCP_AUTH_TOKEN; агент и check_tools передают токен. В compose отсутствует публикация MCP-порта. HTTP без токена дал 401; авторизованные tools работают. |
| 14 | Добавлены backup/restore для Compose (sh) и локального PostgreSQL (ps1). pg_dump → новая БД → pg_restore проверены: 65 событий до и после, четыре миграции, индексы восстановлены. Рабочая БД не очищалась. |
| 15 | В Git нет .ruff_cache, miniapp/dist, __pycache__, pyc; .gitignore исключает их и .env. Переписаны README, STATUS, INDEXES; удалены устаревшие инструкции и старые отчёты. В Git оставлен текущий синтетический EXPLAIN-отчёт. |

Дополнительно исправлены: неверный маршрут /api/v1/me в smoke-скрипте; отсутствовавший PUT в CORS (обнаружено реальным Chromium); статус new → pending для новых reminder; счётчик pending в Mini App; серверное преобразование времени вместо пояса устройства; загрузчик Vite config для ограничения файлового доступа Windows.

## Команды и фактический вывод

Использован отдельный venv в work/venv. Из-за сброса соединений PyPI зависимости устанавливались через зеркало; pip check завершился без конфликтов. Рабочий .env создан на основе .env.example со случайными отдельными паролями и токенами, внешние credentials — placeholder. .env не включён в Git и выдаваемые архивы.

| Команда / проверка | Вывод |
| --- | --- |
| docker version | Команда docker не найдена. Docker compose build/up/ps и контейнерный tests не запускались. |
| python -m app.bootstrap из mcp_server | Применены 001_create_events.sql, 002_event_indexes.sql, 003_mini_app_fields_and_profiles.sql, 004_reminder_deliveries.sql. |
| psql: schema_migrations, pg_indexes, pg_roles | 4 миграции, обязательные GIN/B-tree индексы и частичный индекс reminder; assistant_app/assistant_api/assistant_agent/assistant_bot без SUPERUSER/CREATEDB. |
| python -m scripts.check_tools | tools: create_event, get_event, get_event_by_query; create_event: True; get/get_by_query нашли одну запись; RESULT: OK. |
| agent: python -m pytest -q | 34 passed; 0 skipped. Настоящие PostgreSQL/Redis/MCP, GigaChat — scripted interface. |
| api: python -m pytest -q | 73 passed; 0 skipped. Включены PostgreSQL-интеграции и CORS PUT regression. |
| bot: python -m pytest -q | 24 passed; 0 skipped. Текст, ASR/voice/source, durable inbox, повтор доставки, отдельная БД напоминаний. |
| mcp_server: python -m unittest discover -s tests -v | Ran 36 tests; OK; 0 skipped. Включены роли, миграции, HTTP/stdio MCP, Redis TTL/confirmation, parity API/MCP. |
| python -m scripts.mock_scenarios из agent | Все POST /chat: 200. Создание завтра в 15 → предложение → да → запись; неделя; поиск врача; уточнение; болтовня; повтор ключа без дубля. |
| python -m scripts.smoke_test --base-url http://127.0.0.1:8002 | health/me 200; create 201; list/get/search/patch 200; delete 204; OK. Использовался подписанный initData из make_init_data.py. |
| HTTP дополнительно | /api/timezone GET/PUT/resolve: 200; чужое событие GET/PATCH/DELETE: 404; все health: 200; MCP без Bearer: 401. |
| npm ci | added 65 packages; audited 66 packages; 0 vulnerabilities. Использован локальный npm-cache в work. |
| npm run build | Vite: 35 modules transformed; production assets собраны без ошибок. |
| Playwright + headless Chromium | Список из живого API, смена Europe/Moscow → Asia/Yekaterinburg → Europe/Moscow, создание reminder формой — успешно; pageerror отсутствуют. Скриншот miniapp-events.png. |
| Напоминание через API на 65 секунд | Мок MAX получил одну отправку. Повторные сканы не дублируют. Дополнительно два отдельных процесса: одна отправка, PostgreSQL status=done. |
| pg_dump + createdb + pg_restore | 65/65 событий, 4 миграции, индексы совпали в отдельной assistant_restore_check. |
| python -m scripts.benchmark_indexes --rows 100000 | period 0.559 → 0.060 ms; typed_period 0.480 → 0.037 ms; AND 4.393 → 0.148 ms; OR 6.905 → 0.162 ms. Синтетика, не SLA. |
| git grep по исходникам и зависимостям | Названий запрещённых LLM-SDK не найдено. Установленная зависимость модели — langchain-gigachat. |
| python -m pip check; compileall | No broken requirements found; compileall OK. |
| YAML / Dockerfile inputs | 11 сервисов, зависимости и статические COPY-пути валидны; это не доказательство Docker-сборки. |

Полные логи и JSON-проверки приложены в каталоге verification рядом с отчётом. Логи содержат вымышленные тестовые события; реальные credentials и initData туда не выводились.

## Ограничения живой проверки

- GigaChat: нет реальных credentials. Проверен интерфейс bind_tools/ainvoke через scripted GigaChat; качество интерпретации языка, инструменты и относительные даты настоящей моделью не подтверждены. gigachat_scenarios.py с реальным ключом не запускался.
- MAX: нет рабочего токена. Отправка и polling проверены на локальном HTTP-моке и в тестах, не в мессенджере. Документированный POST /messages не предоставляет параметра идемпотентности; вывод о необходимости сверки неопределённых отправок — инженерное следствие этого ограничения: https://dev.max.ru/docs-api/methods/POST/messages.
- ASR: реальных внешних вызовов и загрузки GigaAM не было. Адаптеры/voice/source проверены моками. CDN-хосты MAX заранее неизвестны и оставлены пустыми.
- Docker / Valkey / публичный Caddy TLS: не запущены в этой среде. Локальная проверка шла на Windows PostgreSQL 18 и Redis 8.10.3 вместо PostgreSQL 17/Valkey 8 из compose. Windows Redis загружен из redis-windows/redis-windows, SHA256 сверена с релизом: https://github.com/redis-windows/redis-windows/releases/tag/8.10.3.
- Сбой сразу после начала отправки напоминания: inflight требует ручной сверки. Автоматической гарантии доставки без потерь и дублей на этом участке нет. Этот пункт нельзя считать полностью закрытым требованием строгой exactly-once доставки.

## Что заполнить в .env

Запустите python scripts/init_env.py в распакованном репозитории. Семь внутренних паролей/токенов генерируются автоматически; не переносите .env в Git.

Впишите реальные GIGACHAT_CREDENTIALS, MAX_BOT_TOKEN, MINI_APP_LINK; проверьте GIGACHAT_SCOPE/MODEL и доверенные сертификаты. Для голоса — ASR_PROVIDER, его URL/ключи и точные AUDIO_ALLOWED_HOSTS; для GigaAM включите профиль gigaam. Для публикации — PUBLIC_DOMAIN, VITE_API_BASE=https://ваш-домен, CORS_ORIGINS=https://ваш-домен, VITE_BOT_LINK. AUTH_DEV_MODE=false. После смены VITE_* требуется rebuild Mini App.

После доступа к Docker обязательны docker compose build, docker compose up -d, docker compose ps и docker compose --profile tools run --rm tests, затем живые проверки GigaChat/MAX/ASR. Эти проверки здесь не выдаются за выполненные.

## Коммиты

- e02dd4d — интеграция унифицированного ZIP поверх истории GitHub.
- a592a99 — профили, программное подтверждение, durable reminders.
- 558de12 — согласованность поиска API/MCP, Mini App и timezone/CORS.
- 19d2943 — авторизация MCP, Caddy, исправление Dockerfile, бэкапы.
- 4ba239f — воспроизводимые HTTP-сценарии с интерфейсной заглушкой GigaChat.
- c1f66c5 — EXPLAIN для OR-поиска и удаление старых отчётов.
- Финальный коммит документации содержит этот STATUS и текущие результаты.

Коммиты сохранены локально; push не выполнялся. Git bundle содержит историю, ZIP — текущие отслеживаемые исходники без .env, кэшей, node_modules и dist.
