# Windows-ПК → VPS → «Горький код»

Пошаговый гайд от 30 октября 2026 года. На твоём ПК остаётся Windows: браузер, PowerShell и SSH. Docker, PostgreSQL и Valkey устанавливаются на удалённом Ubuntu-сервере. Docker Desktop на ПК не нужен. После запуска VPS проект работает, даже когда ПК выключен.

Инструкция подготовлена для исправленного gorky-code-fixed.zip. Сервер ещё не куплен, живое развёртывание по этой инструкции не выполнялось. Проверки ниже — обязательные условия приёмки.

## 1. Что проверить до оплаты

1. Получи рабочий **MAX_BOT_TOKEN** и доступ к настройкам соответствующего бота. Сейчас создание ботов/Mini App доступно верифицированным юрлицам, ИП и самозанятым — резидентам РФ. Обычное физлицо пока не может пройти верификацию. Если бот командный, используй предоставленный командой доступ. [Текущие условия MAX](https://dev.max.ru/help/platform_connection).
2. Убедись, что есть credentials именно **GigaChat API**. Подписка на обычный чат не подтверждает доступ API. Для новых клиентов изменились условия покупки пакетов: актуальная инструкция направляет их на cloud.ru. Выдаваемый ключ должен подходить интерфейсу GigaChat/langchain-gigachat этого проекта; ключ другого API-шлюза не становится совместимым автоматически. [Инструкция GigaChat](https://developers.sber.ru/docs/ru/gigachat/individuals-quickstart).
3. Подготовь домен или купи его. Если свой домен уже есть, достаточно поддомена вроде assistant.example.com. Для текстового polling-бота домен не обязателен, для публичного Mini App нужен HTTPS.

Токены и пароли вводятся в личных кабинетах и `.env` на сервере. Присылать их в чат не нужно.

## 2. Какой VPS выбрать

Для небольшого пилота я предлагаю **4 vCPU, 8 ГБ RAM, 80–120 ГБ NVMe, публичный IPv4, x86-64/amd64, Ubuntu 24.04 LTS**. Нужен VPS/VDS с root/sudo, а не виртуальный хостинг для сайтов. Платная панель и Windows Server не требуются.

Это инженерная оценка с запасом, не нагрузочный тест и не обещание числа пользователей. Она рассчитана на внешний GigaChat и внешний ASR. Самостоятельный GigaAM/CUDA и длинное аудио потребуют отдельного замера ресурсов.

| Провайдер | Подходящая конфигурация | Ориентир |
| --- | --- | --- |
| [Fornex](https://ru.fornex.com/virtual-private-servers/on-ubuntu/) | Cloud NVMe 8: 4 CPU, 8 ГБ, 120 ГБ | На просмотренной странице около 3 315 ₽/мес |
| [Timeweb Cloud](https://timeweb.cloud/services/vps-ubuntu) | 4 CPU, 8 ГБ, 80 ГБ; можно выбрать площадку РФ | В индексируемом предложении около 1 800 ₽/мес; фактическую сумму проверь в конфигураторе |
| [Selectel](https://selectel.ru/services/cloud/servers/?section=prices) | Аналогичные CPU/RAM, диск и IPv4 через калькулятор | Итог зависит от конфигурации и дополнительных ресурсов |

Цены проверялись 30.10.2026 и зависят от локации, срока и услуг. Итоговая цена — в заказе. Домен, API GigaChat, ASR и бэкапы могут оплачиваться отдельно.

**Fornex подходит**, если тебе удобны его оплата и выбранная страна. Если нужна российская площадка, сравни с Timeweb Cloud. Я бы взял один месяц, проверил доступ к API и только потом продлевал надолго.

## 3. Подготовить SSH на твоём ПК

Далее пометка **ПК / PowerShell** означает команды Windows. **Сервер / Bash** — команды внутри SSH-сеанса Linux. Не вставляй Linux-команды в обычный PowerShell.

**ПК / PowerShell:**

```powershell
Get-Command ssh, scp, ssh-keygen
```

На твоём ПК эти команды были найдены. Если их нет после переустановки Windows, добавь компонент «Клиент OpenSSH». SSH-сервер на Windows не нужен. [Инструкция Microsoft](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_keymanagement).

Создай отдельный ключ, не перезаписывая существующий:

```powershell
$DeployKey = "$env:USERPROFILE\.ssh\gorky_server"
New-Item -ItemType Directory -Force "$env:USERPROFILE\.ssh" | Out-Null
if (-not (Test-Path $DeployKey)) {
    ssh-keygen -t ed25519 -C "gorky-server" -f $DeployKey
}
Get-Content "$DeployKey.pub"
```

Выбери парольную фразу и сохрани её. В панель хостинга вставляется только строка из **gorky_server.pub**. Файл **gorky_server** — приватный ключ, его не передавай другим.

## 4. Купить сервер в браузере

1. Зарегистрируйся на официальном сайте провайдера, включи двухфакторный вход, если доступен.
2. Выбери VPS/облачный сервер и ресурсы из раздела 2.
3. ОС — **Ubuntu 24.04 LTS**, архитектура **x86-64**, без платной панели.
4. Проверь фактически доступную локацию. Наличие РФ у Fornex не предполагается по старой рекламе — смотри конкретный заказ.
5. Убедись, что включён публичный IPv4. Если он отдельной строкой — добавь его.
6. В поле SSH keys вставь публичный ключ из предыдущего шага, если такое поле есть.
7. Выбери один месяц и проверь полную сумму, способ оплаты, стоимость бэкапов и продления.
8. Оплати и дождись состояния «работает».
9. Сохрани IP, первоначальное имя пользователя, временный пароль при его наличии и доступ к консоли/VNC.
10. В сетевом firewall кабинета разреши TCP **22, 80, 443**. UDP 443 можно разрешить для HTTP/3. Порты БД и MCP наружу не открывай.

## 5. Первый SSH-вход и пользователь deploy

В примерах **203.0.113.10 — вымышленный IP**, замени его своим.

**ПК / PowerShell:**

```powershell
$ServerIP = "203.0.113.10"
$DeployKey = "$env:USERPROFILE\.ssh\gorky_server"
ssh -i $DeployKey "root@$ServerIP"
```

Если провайдер указал пользователя ubuntu, войди как ubuntu и административные команды выполняй с sudo. Ниже первый блок рассчитан на root. При первом подключении сравни отпечаток сервера с консолью провайдера. Если ключ при покупке не установили, первый вход может быть по временному паролю.

**Сервер / Bash, первоначальная root-сессия:**

```bash
apt-get update
apt-get upgrade -y
apt-get install -y sudo ca-certificates curl unzip python3 nano openssl ufw cron
timedatectl set-timezone Europe/Moscow
adduser deploy
usermod -aG sudo deploy
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
nano /home/deploy/.ssh/authorized_keys
```

В nano вставь одну полную строку публичного ключа с ПК. Сохранить: Ctrl+O, Enter; выйти: Ctrl+X.

```bash
chown deploy:deploy /home/deploy/.ssh/authorized_keys
chmod 600 /home/deploy/.ssh/authorized_keys
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw enable
ufw status
```

Если SSH использует нестандартный порт, сначала разреши его вместо 22 и подключайся через `ssh -p НОМЕР`. Оставь исходное окно открытым.

**В отдельном PowerShell на ПК:**

```powershell
$ServerIP = "203.0.113.10"
$DeployKey = "$env:USERPROFILE\.ssh\gorky_server"
ssh -i $DeployKey "deploy@$ServerIP"
```

**В новой серверной сессии deploy:**

```bash
sudo -v
```

Только когда вход по ключу и sudo проверены, отключи root/password SSH:

```bash
sudo tee /etc/ssh/sshd_config.d/00-gorky-hardening.conf >/dev/null <<'EOF'
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF
sudo sshd -t && sudo systemctl reload ssh
```

Проверь ещё один новый вход deploy. Лишь после успеха закрывай первоначальное root-окно. Для восстановления доступа есть консоль провайдера; переустановка VPS с данными — не способ обычной диагностики.

## 6. Docker устанавливается на сервере

Продолжай в SSH как deploy. Используется официальный apt-репозиторий Docker. [Официальная инструкция для Ubuntu](https://docs.docker.com/engine/install/ubuntu/).

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "$VERSION_CODENAME")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker run --rm hello-world
sudo docker compose version
```

Ожидается **Hello from Docker!**. Во всём гайде используется sudo docker, поэтому добавлять deploy в группу docker не требуется.

## 7. Перенести исправленный архив с ПК

Исправления пока не отправлены в GitHub. Нужен **gorky-code-fixed.zip**, не прежний исходный gorky-code.zip.

**ПК / PowerShell:**

```powershell
$ProjectZip = "C:\Users\vladl\Documents\Codex\2026-10-29\https-github-com-lefiper-gorky-code-2\outputs\gorky-code-fixed.zip"
$ServerIP = "203.0.113.10"
$DeployKey = "$env:USERPROFILE\.ssh\gorky_server"
Get-FileHash -Algorithm SHA256 $ProjectZip
scp -i $DeployKey $ProjectZip "deploy@${ServerIP}:~/gorky-code-fixed.zip"
```

**Сервер / Bash:**

```bash
sha256sum ~/gorky-code-fixed.zip
sudo install -d -o deploy -g deploy /opt/gorky-code
unzip ~/gorky-code-fixed.zip -d ~/gorky-release
cp -a ~/gorky-release/gorky-code/. /opt/gorky-code/
cd /opt/gorky-code
ls docker-compose.yml .env.example
python3 scripts/init_env.py
chmod 600 .env
```

Сверь SHA256 с PowerShell, регистр букв не важен. Это команды первого размещения в новые каталоги; обновлять работающую установку поверх без бэкапа не нужно.

Скрипт создал случайные пароли и внутренние ключи. Он не перезаписывает существующий .env. Локальный тестовый .env и базы с ПК не переносятся.

## 8. Домен и DNS

У регистратора домена создай запись **A**, имя **assistant**, значение **IPv4 VPS**. Получится, например, **assistant.example.com**. Замени этот пример своим доменом во всех следующих шагах. Если своего домена нет — сначала зарегистрируй его и получи доступ к DNS. Отдельный домен для поддомена не покупается.

Не указывай случайную AAAA-запись. Если используешь DNS-прокси, первый запуск проще проверять в режиме DNS only.

**ПК / PowerShell:**

```powershell
Resolve-DnsName assistant.example.com -Type A
```

Результат должен совпасть с VPS. Обновление DNS не всегда видно сразу; запись должна изменяться у тех NS-серверов, которые реально обслуживают домен.

## 9. Настроить .env и доверенные сертификаты

**Сервер / Bash:**

```bash
cd /opt/gorky-code
nano .env
```

Замени соответствующие строки, не добавляя дубликаты ключей:

```dotenv
APP_ENV=production
AUTH_DEV_MODE=false
DEFAULT_TIMEZONE=Europe/Moscow
COMPOSE_FILE=docker-compose.yml:compose.server.yml

PUBLIC_DOMAIN=assistant.example.com
VITE_API_BASE=https://assistant.example.com
CORS_ORIGINS=https://assistant.example.com
VITE_BOT_LINK=https://max.ru/ИМЯ_ТВОЕГО_БОТА
VITE_DEV_USER_ID=

MAX_BOT_TOKEN=РЕАЛЬНЫЙ_ТОКЕН_MAX
MAX_API_URL=https://platform-api2.max.ru
MINI_APP_LINK=
WEBHOOK_URL=

GIGACHAT_CREDENTIALS=РЕАЛЬНЫЕ_CREDENTIALS_GIGACHAT_API
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=GigaChat-2-Max
GIGACHAT_VERIFY_SSL_CERTS=true
GIGACHAT_CA_BUNDLE_FILE=/app/certs/ca-bundle.pem
EXTRA_CA_FILE=/app/certs/ca-bundle.pem

ASR_PROVIDER=yandex
YANDEX_API_KEY=
YANDEX_FOLDER_ID=
AUDIO_ALLOWED_HOSTS=
```

Сначала запускаем текст; ASR подключается отдельно в разделе 12. MINI_APP_LINK заполним после регистрации URL в MAX. Сгенерированные пароли БД и внутренние токены оставь различными. Scope и модель должны быть доступны именно твоему аккаунту GigaChat.

COMPOSE_FILE явно объединяет основной compose и серверный файл, который создадим ниже; разделитель `:` здесь предназначен для Linux-сервера. Не запускай Compose до создания обоих файлов.

Для GigaChat используются credentials, не вручную выписанный краткоживущий access_token. Актуальный API — https://api.giga.chat; OAuth может требовать исходящий порт 9443. [Авторизация GigaChat](https://developers.sber.ru/docs/ru/gigachat/api/reference/rest/gigachat-api).

Подготовь CA-цепочку для исходящих соединений GigaChat/MAX. HTTPS твоего сайта — отдельный сертификат, его получит Caddy.

```bash
mkdir -p certs
chmod 755 certs
curl -fsSL https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt -o certs/russian-root.crt
curl -fsSL https://gu-st.ru/content/lending/russian_trusted_sub_ca_pem.crt -o certs/russian-sub.crt
openssl x509 -in certs/russian-root.crt -noout -subject -dates -fingerprint -sha256
openssl x509 -in certs/russian-sub.crt -noout -subject -dates
cat /etc/ssl/certs/ca-certificates.crt certs/russian-root.crt certs/russian-sub.crt > certs/ca-bundle.pem
chmod 644 certs/*.crt certs/ca-bundle.pem
```

Это должны быть PEM-сертификаты, не HTML ошибки. Официальные файлы и инструкция — [документация GigaChat](https://developers.sber.ru/docs/ru/gigachat/certificates). Если скачивание не проходит проверку TLS, не добавляй автоматически -k: получи официальные файлы через доверенное соединение на ПК и перенеси scp. GIGACHAT_VERIFY_SSL_CERTS оставь true.

Создай серверный compose с CA-mount и ограничением размера логов:

```bash
cat > compose.server.yml <<'YAML'
x-bounded-logging: &bounded-logging
  driver: local
  options:
    max-size: "10m"
    max-file: "5"
services:
  postgres:
    logging: *bounded-logging
  valkey:
    logging: *bounded-logging
  mcp:
    logging: *bounded-logging
  agent:
    logging: *bounded-logging
    volumes:
      - ./certs:/app/certs:ro
  api:
    logging: *bounded-logging
  bot:
    logging: *bounded-logging
    volumes:
      - ./certs:/app/certs:ro
  miniapp:
    logging: *bounded-logging
  caddy:
    logging: *bounded-logging
YAML
```

Персональные .env и compose.server.yml храни как настройки этого развёртывания, отдельно от публичного Git. Публичные CA-сертификаты не являются API-ключами.

## 10. Собрать и запустить с HTTPS

**Сервер / Bash:**

```bash
cd /opt/gorky-code
sudo docker compose config --quiet
sudo docker compose --profile https up --build -d
sudo docker compose --profile https ps -a
```

После сборки ожидаются работающие postgres, valkey, mcp, agent, api, bot, miniapp и caddy. Сервисы с healthcheck должны стать healthy. Одноразовый migrate должен завершиться **Exited (0)** — это нормально.

```bash
sudo docker compose exec agent test -r /app/certs/ca-bundle.pem
sudo docker compose exec bot test -r /app/certs/ca-bundle.pem
curl -fsS http://127.0.0.1:8002/health
curl -fsS http://127.0.0.1:8003/health
curl -fsS http://127.0.0.1:8081/health
curl -I https://assistant.example.com
sudo docker compose --profile https logs --tail=100 caddy
```

Для автоматического HTTPS домен должен указывать на VPS, а 80/443 — быть доступны извне. Caddy сохраняет сертификат в постоянном volume; платный SSL отдельно для этого способа не нужен. [Документация Caddy](https://caddyserver.com/docs/automatic-https).

**ПК / PowerShell:**

```powershell
Test-NetConnection assistant.example.com -Port 443
Start-Process "https://assistant.example.com"
```

Страница должна открыться без ошибки сертификата. Отсутствие авторизации вне MAX ещё не означает поломку: initData приходит при открытии приложения через MAX.

Если есть ошибка:

```bash
sudo docker compose --profile https logs --tail=150 migrate postgres mcp agent api bot caddy
```

Не публикуй внутренние порты БД/MCP/агента ради диагностики. Основной compose привязывает их к loopback или внутренней сети. Публичный вход — Caddy на 80/443.

## 11. Проверить настоящую модель, БД и MAX

**Сервер / Bash:**

```bash
sudo docker compose exec mcp python -m scripts.check_tools
sudo docker compose --profile tools run --rm tests
sudo docker compose exec postgres psql -U assistant_owner -d assistant_mvp -c \
  "SELECT version FROM schema_migrations ORDER BY version;"
sudo docker compose exec postgres psql -U assistant_owner -d assistant_mvp -c \
  "SELECT indexname FROM pg_indexes WHERE tablename='events' ORDER BY indexname;"
sudo docker compose exec agent python -c \
  "from app.config import Settings; from app.llm import build_chat_model; print(build_chat_model(Settings.from_env()).invoke('Ответь одним словом: работает').content)"
```

Ожидаются RESULT: OK, успешный unittest, миграции 001–004, обязательные GIN/B-tree индексы и настоящий ответ GigaChat. Последняя команда использует внешнюю квоту API.

Дополнительные сценарии живой модели:

```bash
sudo docker compose exec -T agent python - < agent/scripts/gigachat_scenarios.py
```

Scripts не включены в runtime-образ, поэтому файл передаётся через stdin. Он использует отдельного тестового пользователя. Подтверждение создания ещё нужно проверить в диалоге MAX.

В кабинете MAX, где зарегистрирован бот:

1. Подключи Mini App с URL https://assistant.example.com и требуемым платформой доменом/данными.
2. Пройди необходимую модерацию, получи ссылку открытия.
3. На сервере впиши ссылку в MINI_APP_LINK в .env.
4. Пересоздай бот и агент:

```bash
cd /opt/gorky-code
sudo docker compose up -d bot agent
```

Официальные инструкции: [Mini App](https://dev.max.ru/docs/webapps/introduction), [получение токена](https://dev.max.ru/help/miniapp-main). Токен должен принадлежать именно тому боту, через которого открывается приложение.

Прогони в настоящем MAX:

- /start и /timezone Europe/Moscow;
- «Создай встречу завтра в 15:00» → предложение, ещё без записи;
- «Да» → событие появляется один раз с правильным временем;
- «Что у меня на этой неделе» и «Найди про врача»;
- «Запиши задачу» → уточнение; «Привет» → разговор без создания события;
- изменение/удаление → ссылка на приложение;
- смена пояса в Mini App → следующий запрос учитывает новый пояс.

Работает один polling-бот. Если для токена зарегистрирован webhook, его нужно осознанно переключить/удалить в MAX: одновременный polling не поддерживается. Вторую копию бота с тем же токеном на ПК не запускай.

## 12. Голос без покупки GPU

Первый вариант — внешний Yandex SpeechKit, уже поддержанный HTTP-адаптером. Это ASR, не замена LLM: GigaChat остаётся единственной моделью агента.

1. Подключи платёжный аккаунт/каталог SpeechKit.
2. Создай сервисный аккаунт для распознавания с ролью ai.speechkit-stt.user и API-ключом.
3. В .env задай ASR_PROVIDER=yandex и YANDEX_API_KEY. Для API-ключа сервисного аккаунта YANDEX_FOLDER_ID оставь пустым: каталог берётся из аккаунта. [Аутентификация SpeechKit](https://aistudio.yandex.ru/ru/docs//speechkit/concepts/auth).
4. В AUDIO_ALLOWED_HOSTS впиши фактические CDN-hostname голосовых вложений MAX. Пока хост неизвестен, отправь запись и посмотри:

```bash
sudo docker compose logs --tail=150 bot
```

audio_host_rejected покажет hostname без секретного URL. Добавляй точное имя, без https://, пути и wildcard.

```bash
sudo docker compose up -d bot
```

Протестируй короткую запись. Текущий адаптер использует синхронный API v1 с OggOpus: до 30 секунд, 1 МБ, один канал. Другой формат автоматически не перекодируется. [Ограничения](https://aistudio.yandex.ru/en/docs/speechkit/stt/api/request-api).

Если MAX присылает другой формат, потребуется совместимый адаптер/перекодировка: покупка более мощного VPS это не исправит. GigaAM/CUDA-профиль разбирается отдельно с замером памяти и времени распознавания, а не включается вслепую на выбранном VPS.

## 13. Напоминания и перезагрузка

Создай reminder через Mini App на 2–3 минуты вперёд:

```bash
sudo docker compose restart bot
```

Ожидается одна отправка после наступления времени. Повторный restart после отправки не должен её продублировать.

```bash
sudo docker compose exec postgres psql -U assistant_owner -d assistant_mvp -c \
  "SELECT e.id,e.name,e.status,d.state FROM events e LEFT JOIN reminder_deliveries d ON d.event_id=e.id WHERE e.event_type='reminder' ORDER BY e.created_at DESC LIMIT 20;"
```

После успеха ожидаются done/sent. При неопределённом ответе MAX состояние inflight требует ручной сверки. Строгой гарантии без потерь и дублей на аварийном HTTP-участке в этой версии нет. Не возвращай inflight в sending, пока не проверено отсутствие сообщения.

До появления реальных пользователей проверь reboot VPS:

```bash
sudo reboot
```

SSH оборвётся. После загрузки подключись снова и проверь:

```bash
cd /opt/gorky-code
sudo docker compose --profile https ps -a
curl -fsS http://127.0.0.1:8002/health
curl -fsS http://127.0.0.1:8003/health
curl -I https://assistant.example.com
```

События должны сохраниться. Краткоживущая история и pending Valkey при перезапуске самого Valkey теряются; события и журнал напоминаний находятся в PostgreSQL.

## 14. Ежедневный бэкап и отдельная копия на ПК

Включи доступные бэкапы VPS у провайдера. Дополнительно настрой логический pg_dump: он нужен для проверяемого восстановления базы.

**Сервер / Bash:**

```bash
sudo install -d -m 700 /var/backups/gorky-code
sudo tee /usr/local/sbin/gorky-code-backup >/dev/null <<'SH'
#!/bin/sh
set -eu
cd /opt/gorky-code
umask 077
stamp=$(date +%F-%H%M%S)
backup_file="/var/backups/gorky-code/assistant-$stamp.dump"
sh scripts/backup.sh "$backup_file"
install -d -o deploy -g deploy -m 700 /home/deploy/gorky-backups
install -o deploy -g deploy -m 600 "$backup_file" /home/deploy/gorky-backups/latest.dump
find /var/backups/gorky-code -maxdepth 1 -type f -name 'assistant-*.dump' -mtime +14 -delete
SH
sudo chmod 750 /usr/local/sbin/gorky-code-backup
sudo /usr/local/sbin/gorky-code-backup
sudo tee /etc/cron.d/gorky-code-backup >/dev/null <<'CRON'
15 3 * * * root /usr/local/sbin/gorky-code-backup >> /var/log/gorky-code-backup.log 2>&1
CRON
sudo chmod 644 /etc/cron.d/gorky-code-backup
sudo systemctl enable --now cron
```

Это ежедневный дамп в 03:15 по серверному Europe/Moscow. Файлы assistant-*.dump старше двух недель удаляются из выделенной папки бэкапов; latest.dump доступен deploy для копирования. Дамп на том же VPS не заменяет отдельную копию.

**ПК / PowerShell, регулярно и после важных изменений:**

```powershell
$ServerIP = "203.0.113.10"
$DeployKey = "$env:USERPROFILE\.ssh\gorky_server"
$BackupDirectory = "$env:USERPROFILE\Documents\GorkyBackups"
New-Item -ItemType Directory -Force $BackupDirectory | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
scp -i $DeployKey "deploy@${ServerIP}:~/gorky-backups/latest.dump" "$BackupDirectory\assistant-$Stamp.dump"
scp -i $DeployKey "deploy@${ServerIP}:/opt/gorky-code/.env" "$BackupDirectory\server-$Stamp.env"
```

В этой папке пользовательские данные и секреты: не добавляй её в публичный Git. Храни также код, compose.server.yml и доступы к провайдеру/DNS; .env не восстанавливается из репозитория.

Проверь восстановление в НОВУЮ БД:

```bash
cd /opt/gorky-code
restore_name="assistant_restore_check_$(date +%Y%m%d%H%M%S)"
sudo sh scripts/restore.sh /home/deploy/gorky-backups/latest.dump "$restore_name"
```

Ожидаются число событий и четыре миграции, без ошибок pg_restore. Это не переключает приложение и не заменяет рабочую assistant_mvp. Проверь число событий относительно времени создания дампа.

Свежесть и ошибки бэкапа:

```bash
sudo ls -lh /var/backups/gorky-code
sudo tail -n 50 /var/log/gorky-code-backup.log
```

## 15. Обслуживание и диагностика

После правки .env пересоздай контейнеры:

```bash
cd /opt/gorky-code
sudo docker compose --profile https up -d
```

Для VITE_* нужна пересборка:

```bash
sudo docker compose --profile https up --build -d miniapp
```

Простой restart не обновляет окружение. Перед заменой исходников/миграций сделай pg_dump и снимок VPS, сохрани предыдущий архив кода. Исправления пока не опубликованы на GitHub, поэтому git pull не гарантирует получение подготовленной версии.

```bash
cd /opt/gorky-code
sudo docker compose --profile https ps -a
sudo docker compose logs --tail=100 agent bot api mcp
free -h
df -h
sudo docker stats --no-stream
```

| Симптом | Что проверить |
| --- | --- |
| Сайт недоступен | DNS A/AAAA, IP, firewall кабинета, UFW, логи caddy, порты 80/443 |
| Ошибка сертификата сайта | Домен указывает не туда, неверная AAAA, порт 80/443 закрыт или выпуск ещё не завершён |
| Агент 503 | Реальный запрос GigaChat, credentials/scope/model, CA-mount, MCP/Valkey |
| GigaChat 401/403 | Вид ключа, scope, разрешённая модель и доступ API; новый VPS сам это не исправит |
| Mini App 401 | Открытие вне MAX, токен другого бота, подпись/срок initData |
| Голос не работает | CDN allowlist, формат/длительность, API-ключ/квота ASR |
| Нет сообщений бота | Токен, TLS MAX, существующий webhook, вторая polling-копия |
| Постоянные рестарты | logs сервиса, RAM/диск и код выхода; не удаляй volumes для диагностики |
| Напоминание inflight | Ручная сверка фактической отправки с MAX |
| После смены пароля БД вход сломался | Изменение .env не меняет пароль существующей роли в volume; нужны согласованные изменения |

Остановка с сохранением volumes:

```bash
sudo docker compose --profile https down
```

Не добавляй **-v** — это удаляет volumes с данными. Удаление VPS в панели тоже не является обычной перезагрузкой. Не публикуй .env, initData или полный вывод compose config: в нём могут быть секреты. Для проверки синтаксиса выше используется config --quiet.

## Критерии готовности

- Вход deploy по ключу и sudo работают; root/password SSH отключены только после проверки.
- migrate завершился с 0, сервисы работают, MCP-проверка и контейнерные тесты прошли.
- Настоящий GigaChat отвечает, проверка сертификатов включена.
- MAX получает текст, Mini App открывается через MAX с авторизацией.
- Событие создаётся только после согласия; время и смена пояса верны.
- Короткое голосовое распознаётся выбранным ASR.
- Напоминание не дублируется при обычном рестарте; ограничение inflight известно.
- После reboot сервисы поднимаются, события сохраняются.
- Свежий pg_dump скопирован за пределы VPS, проверка восстановления успешна.
- Оплата сервера и продление домена не забыты, доступ к личным кабинетам сохранён.

Это критерии проверки, не обещание безотказности одного VPS. Ранее 167 локальных тестов прошли с моками внешних сервисов. Реальное размещение, формат аудио и доступы подтверждаются новым прогоном на купленном сервере.
