# «Горький код»: запуск и проверка на Arch Linux

Гайд для исправленной версии из gorky-code-fixed.zip или gorky-code.bundle, приложенных к отчёту. В GitHub исправления не отправлены: обычный git clone с GitHub пока может получить старую структуру.

Команды ниже выполняются в Bash. Полный стек запускается в Docker; устанавливать PostgreSQL, Valkey и Node.js на хост отдельно не нужно. Этот гайд составлен по текущим файлам проекта и официальной документации; на отдельной машине Arch Linux команды ещё не выполнялись.

## 1. Установить Docker

Обновите систему и установите пакеты из официальных репозиториев:

```bash
sudo pacman -Syu docker docker-compose docker-buildx git python curl unzip nano
sudo systemctl enable --now docker.service
sudo docker run --rm hello-world
```

Ожидается сообщение Hello from Docker!. Docker Engine и Buildx описаны в [ArchWiki](https://wiki.archlinux.org/title/Docker); Compose и Buildx доступны как пакеты [docker-compose](https://archlinux.org/packages/extra/x86_64/docker-compose/) и [docker-buildx](https://archlinux.org/packages/extra/x86_64/docker-buildx/).

Чтобы дальше выполнять docker без sudo:

```bash
sudo usermod -aG docker "$USER"
```

Полностью выйдите из пользовательского/SSH-сеанса и войдите заново. Затем:

```bash
docker info
docker compose version
docker buildx version
```

Членство в группе docker даёт права уровня root — это свойство Docker, описанное в [официальной инструкции](https://docs.docker.com/engine/install/linux-postinstall/). Если не хотите добавлять пользователя в группу, используйте sudo перед командами docker в этом гайде; скрипты бэкапа и восстановления запускайте как sudo sh scripts/backup.sh ... и sudo sh scripts/restore.sh ... .

## 2. Распаковать исправленный проект

Скачайте gorky-code-fixed.zip. В примере файл находится в ~/Downloads; при необходимости замените путь. Выберите каталог, где ещё нет старой папки gorky-code:

```bash
mkdir -p ~/projects
unzip ~/Downloads/gorky-code-fixed.zip -d ~/projects
cd ~/projects/gorky-code
ls docker-compose.yml .env.example scripts/init_env.py
```

Вместо ZIP можно восстановить репозиторий с историей из bundle — используйте этот вариант отдельно, в ещё не существующий каталог:

```bash
git clone ~/Downloads/gorky-code.bundle ~/projects/gorky-code
cd ~/projects/gorky-code
git log -7 --oneline
```

Все дальнейшие команды выполняются из корня проекта.

## 3. Создать .env

```bash
python scripts/init_env.py
chmod 600 .env
nano .env
```

Скрипт создаст отдельные случайные пароли БД и внутренние токены. Если .env уже существует, он остановится без перезаписи. Не публикуйте этот файл.

Для живой работы заполните:

```dotenv
GIGACHAT_CREDENTIALS=реальные_данные_GigaChat
MAX_BOT_TOKEN=реальный_токен_MAX
MINI_APP_LINK=реальная_ссылка_зарегистрированного_Mini_App
DEFAULT_TIMEZONE=Europe/Moscow
```

Уточните GIGACHAT_SCOPE для своего аккаунта. Сгенерированные POSTGRES_PASSWORD, APP_DB_PASSWORD, API_DB_PASSWORD, AGENT_DB_PASSWORD, BOT_DB_PASSWORD, AGENT_API_KEY и MCP_AUTH_TOKEN оставьте разными.

Для первого локального запуска:

```dotenv
VITE_API_BASE=http://localhost:8002
CORS_ORIGINS=http://localhost:8080
AUTH_DEV_MODE=false
```

Не оставляйте placeholder в credentials, если проверяете настоящие внешние вызовы. С заглушками можно проверять инфраструктуру, но бот не сможет общаться с MAX/GigaChat.

При проблемах доверия сертификату GigaChat задайте GIGACHAT_CA_BUNDLE_FILE. Это путь внутри контейнера: PEM нужно дополнительно примонтировать в agent read-only, например через compose.override.yml. Не отключайте проверку TLS для постоянного запуска.

## 4. Собрать и поднять стек

```bash
docker compose config --quiet
docker compose build
docker compose up -d
docker compose ps -a
```

Ожидается:

- postgres, valkey, mcp, agent, api, bot, miniapp — running, где задан healthcheck — healthy;
- migrate — Exited (0): это нормальное завершение одноразового применения миграций;
- asr и caddy отсутствуют, пока не включены их профили.

Проверки с хоста:

```bash
curl -fsS http://localhost:8002/health
curl -fsS http://localhost:8003/health
curl -fsS http://localhost:8081/health
```

Откройте http://localhost:8080 и http://localhost:8002/docs. Вне MAX Mini App не получает initData автоматически; ошибка авторизации при открытии обычной вкладкой ожидаема. Подписанные запросы проверяются в следующем разделе. С телефона localhost указывает на сам телефон — для настоящего MAX Mini App нужен публичный HTTPS-домен.

Логи при ошибке:

```bash
docker compose logs --tail=150 migrate postgres valkey mcp agent api bot
```

Не публикуйте вывод docker compose config без --quiet: он может содержать подставленные секреты.

## 5. Проверить БД, MCP и API

```bash
docker compose exec postgres psql -U assistant_owner -d assistant_mvp -c   "SELECT version FROM schema_migrations ORDER BY version;"

docker compose exec postgres psql -U assistant_owner -d assistant_mvp -c   "SELECT indexname FROM pg_indexes WHERE tablename='events' ORDER BY indexname;"

docker compose exec postgres psql -U assistant_owner -d assistant_mvp -c   "SELECT rolname, rolsuper, rolcreatedb FROM pg_roles WHERE rolname IN ('assistant_app','assistant_api','assistant_agent','assistant_bot') ORDER BY rolname;"

docker compose exec mcp python -m scripts.check_tools
docker compose --profile tools run --rm tests
```

Должны быть миграции 001–004, индексы events_search_gin_idx, events_user_time_idx, events_user_type_time_idx и events_pending_reminders_idx. У четырёх прикладных ролей rolsuper/rolcreatedb должны быть false. MCP-проверка заканчивается RESULT: OK; unittest — OK без пропусков. Тесты оставляют вымышленные события; часть проверок требует PostgreSQL и Valkey работающими.

MCP не публикует порт на хост. Поэтому проверка запускается через compose exec и использует MCP_AUTH_TOKEN из окружения контейнера.

Подписанные HTTP-запросы без установки Python-зависимостей на хост:

```bash
INIT_DATA="$(python api/scripts/make_init_data.py --user-id 123)"

curl -fsS -H "X-Max-InitData: $INIT_DATA" http://localhost:8002/api/me
curl -fsS -H "X-Max-InitData: $INIT_DATA" http://localhost:8002/api/timezone

curl -fsS -X PUT http://localhost:8002/api/timezone   -H "X-Max-InitData: $INIT_DATA"   -H 'Content-Type: application/json'   -d '{"timezone":"Asia/Yekaterinburg"}'

curl -fsS -X POST http://localhost:8002/api/timezone/resolve   -H "X-Max-InitData: $INIT_DATA"   -H 'Content-Type: application/json'   -d '{"date":"2030-01-02","time":"15:00"}'

curl -fsS -G http://localhost:8002/api/tasks   -H "X-Max-InitData: $INIT_DATA"   --data-urlencode 'date=2030-01-02'

unset INIT_DATA
```

Для resolve ожидается 2030-01-02T10:00:00Z. Скрипт берёт токен из корневого .env; не выводите initData в общие логи. Если истёк срок подписи, сгенерируйте её заново. В примере тестируется пользователь 123, а не ваш настоящий MAX-профиль.

## 6. Проверить настоящий GigaChat и MAX

Проверка соединения с единственной моделью проекта:

```bash
docker compose exec agent python -c   "from app.config import Settings; from app.llm import build_chat_model; print(build_chat_model(Settings.from_env()).invoke('Ответь одним словом: работает').content)"
```

Сценарный скрипт не включён в runtime-образ, поэтому передайте его через stdin:

```bash
docker compose exec -T agent python - < agent/scripts/gigachat_scenarios.py
```

Он использует настоящую модель и создаёт отдельного тестового пользователя. Само предложение события ещё не является сохранением: подтверждение дополнительно проверьте в диалоге MAX.

Напишите боту:

1. /timezone Europe/Moscow.
2. «Создай встречу завтра в 15:00». До согласия события в Mini App быть не должно.
3. «Да». Событие должно появиться один раз с правильным временем.
4. «Что у меня на этой неделе» и «Найди про врача».
5. «Запиши задачу» — ожидается уточнение.
6. «Привет» — обычный ответ без создания события.
7. «Создай три встречи» — агент должен объяснить создание по одной с отдельным подтверждением.

Если бот не получает сообщения, проверьте токен и наличие webhook-подписки: polling-режим не работает одновременно с зарегистрированным webhook. Причина должна быть в docker compose logs bot.

## 7. Включить голос

Для встроенного GigaAM укажите в .env:

```dotenv
ASR_PROVIDER=gigaam
GIGAAM_URL=http://asr:8001/v1/audio/transcriptions
AUDIO_ALLOWED_HOSTS=точный.cdn-хост.из.MAX
```

Последняя строка — шаблон, не готовое значение. Нужны точные hostname из URL настоящих голосовых вложений, через запятую, без схемы и пути. Если hostname ещё неизвестен, отправьте голосовое и посмотрите:

```bash
docker compose logs --tail=150 bot
```

Запись audio_host_rejected содержит hostname без секретного URL. После заполнения:

```bash
docker compose --profile gigaam up --build -d
docker compose --profile gigaam logs -f asr bot
```

Первый запуск загружает модель; дождитесь готовности asr. Его Dockerfile использует CUDA-образ: сам профиль не настраивает проброс GPU. GPU-ускорение требует отдельно подготовленного NVIDIA runtime; оно этим гайдом не проверено. Для другого ASR выберите поддержанный HTTP-адаптер и заполните его URL/ключи в .env.

После изменения .env используйте compose up -d для пересоздания нужных контейнеров: простой restart не обновляет их окружение. При недоступном ASR бот должен предложить написать текстом.

## 8. Проверить напоминание и перезапуск

Создайте reminder через Mini App на две минуты вперёд. Затем:

```bash
docker compose restart bot
docker compose logs -f bot
```

Оно должно прийти один раз. После отправки снова выполните restart bot — повторного сообщения быть не должно.

Состояния доставки:

```bash
docker compose exec postgres psql -U assistant_owner -d assistant_mvp -c   "SELECT e.id,e.name,e.status,d.state FROM events e LEFT JOIN reminder_deliveries d ON d.event_id=e.id WHERE e.event_type='reminder' ORDER BY e.created_at DESC LIMIT 20;"
```

После успеха ожидаются status=done и state=sent. Если запрос к MAX завершился неопределённо, state=inflight требует ручной сверки: автоматически повторять такую отправку нельзя без риска дубля. Этот аварийный участок не имеет доказанной гарантии доставки без потерь и дублей.

## 9. Публичный домен и HTTPS

Создайте DNS-запись домена на сервер и обеспечьте входящий доступ к TCP 80/443. Если сервер дома — потребуется корректный проброс портов и доступный извне адрес. Заполните:

```dotenv
PUBLIC_DOMAIN=assistant.example.org
VITE_API_BASE=https://assistant.example.org
CORS_ORIGINS=https://assistant.example.org
AUTH_DEV_MODE=false
VITE_BOT_LINK=ссылка_на_вашего_бота
MINI_APP_LINK=ссылка_зарегистрированного_Mini_App
```

Выполните:

```bash
docker compose --profile https up --build -d
docker compose --profile https logs --tail=150 caddy
curl -I https://assistant.example.org
```

Caddy должен получить действительный сертификат. Откройте приложение через зарегистрированную ссылку MAX; проверьте загрузку событий, смену пояса и создание напоминания. После изменения VITE_* пересобирайте miniapp: эти значения встраиваются в JavaScript.

Если одновременно используете встроенный ASR:

```bash
docker compose --profile https --profile gigaam up --build -d
```

## 10. Бэкап и обычное обслуживание

```bash
mkdir -p backups
sh scripts/backup.sh "backups/assistant-$(date +%F-%H%M%S).dump"
```

Проверка восстановления конкретного дампа в новую БД — подставьте существующее имя файла:

```bash
sh scripts/restore.sh backups/assistant-YYYY-MM-DD-HHMMSS.dump assistant_restore_check
```

Если такая БД уже существует, скрипт остановится. Он не перезаписывает рабочую assistant_mvp. Успешный restore выводит число событий и миграции; сравните их со снимком исходной БД на момент бэкапа. Храните дампы и защищённую копию .env отдельно от репозитория.

```bash
# Состояние
docker compose ps -a

# Логи
docker compose logs -f --tail=100 agent bot

# Пересоздать сервис после изменения .env
docker compose up -d agent bot

# Остановить стек с сохранением данных
docker compose down
```

Не добавляйте -v к down, если хотите сохранить события и состояние бота. В текущей конфигурации Valkey не пишет контекст на диск: перезапуск самого Valkey удаляет историю и pending; перезапуск только бота этого не делает.

## Если запуск не получился

| Симптом | Что проверить |
| --- | --- |
| Cannot connect to the Docker daemon | systemctl status docker.service; journalctl -u docker.service -b --no-pager |
| Permission denied для docker.sock | Полностью перелогиниться после добавления в docker или использовать sudo |
| Не запускается Docker при VPN | ArchWiki отмечает возможное пересечение сетей Docker/VPN; проверьте маршруты и подсети |
| Port is already allocated | ss -lntp; поменяйте соответствующий порт в .env и согласуйте VITE_API_BASE/CORS_ORIGINS |
| migrate завершился с ошибкой | docker compose logs migrate postgres; наличие всех паролей в .env |
| Агент возвращает 503 | Логи agent/mcp, доступность Valkey, credentials GigaChat и доверенные сертификаты |
| UI показывает 401 вне MAX | Нет подписанного initData; откройте через MAX или проверьте curl с подписью |
| После правки .env ничего не изменилось | compose up -d пересоздаёт контейнер; restart оставляет старое окружение |
| Голос не распознаётся | AUDIO_ALLOWED_HOSTS, выбранный ASR, профиль gigaam, логи bot/asr |
| Изменили пароль PostgreSQL, а вход не работает | На существующем volume изменение .env само по себе не меняет пароль роли; требуется согласованное изменение роли и окружения |

Для разбора сохраните вывод docker compose ps -a и логи конкретного падающего сервиса. Секреты, .env, initData и полный вывод compose config в сообщение не прикладывайте.
