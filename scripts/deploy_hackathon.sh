#!/usr/bin/env bash
# First installation on the user's Ubuntu VPS. No local ASR/GPU image is built.
set -Eeuo pipefail
umask 077
export DEBIAN_FRONTEND=noninteractive
project=/opt/gorky-code
archive=/root/gorky-code-fixed.zip
log=/var/log/gorky-deploy.log
if [[ ${EUID} -ne 0 ]]; then
    echo 'Run as root: bash /root/deploy-vps.sh' >&2
    exit 1
fi
exec > >(tee -a "$log") 2>&1
trap 'echo "Installation stopped at line ${LINENO}. Existing volumes were kept. Log: /var/log/gorky-deploy.log" >&2' ERR
echo '=== Gorky Code: Ubuntu VPS setup ==='
. /etc/os-release
if [[ ${ID:-} != ubuntu ]]; then
    echo 'This installer is intended for Ubuntu.' >&2
    exit 1
fi
if [[ ! -f "$project/docker-compose.yml" && ! -f "$archive" ]]; then
    echo 'Upload /root/gorky-code-fixed.zip first.' >&2
    exit 1
fi
free -h
df -h /
available_kb=$(df --output=avail / | tail -1 | tr -d ' ')
if (( available_kb < 10 * 1024 * 1024 )); then
    echo 'Less than 10 GiB free. Increase disk space before installing.' >&2
    exit 1
fi
apt-get update
apt-get install -y ca-certificates curl unzip python3 openssl

# Swap is a safety margin for builds, not a substitute for enough RAM.
if [[ -z $(swapon --show --noheadings) && ! -e /swapfile-gorky ]]; then
    fallocate -l 2G /swapfile-gorky
    chmod 600 /swapfile-gorky
    mkswap /swapfile-gorky
    swapon /swapfile-gorky
    if ! grep -q '^/swapfile-gorky ' /etc/fstab; then
        printf '%s\n' '/swapfile-gorky none swap sw 0 0' >> /etc/fstab
    fi
fi

if ! command -v docker >/dev/null; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    codename=${UBUNTU_CODENAME:-$VERSION_CODENAME}
    architecture=$(dpkg --print-architecture)
    cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $codename
Components: stable
Architectures: $architecture
Signed-By: /etc/apt/keyrings/docker.asc
EOF
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker
docker compose version

if [[ ! -f "$project/docker-compose.yml" ]]; then
    install -d -m 0755 "$project"
    unzip -n "$archive" -d /opt
fi
cd "$project"
if [[ ! -f .env ]]; then
    python3 scripts/init_env.py
fi
chmod 600 .env

if [[ -f .gorky-vps-first-run-complete ]]; then
    echo 'This first-install script already completed. No settings were overwritten.'
    docker compose ps -a
    exit 0
fi
# Refuse to replace an unrelated deployment override silently.
if [[ -f compose.hackathon.yml ]] && ! grep -q '# gorky-hackathon-managed' compose.hackathon.yml; then
    echo 'Existing compose.hackathon.yml is not managed by this installer.' >&2
    exit 1
fi
if [[ -f compose.override.yml || -f compose.override.yaml || -f docker-compose.override.yml || -f docker-compose.override.yaml ]]; then
    echo 'Existing compose override detected. Review the deployment manually before proceeding.' >&2
    exit 1
fi

echo 'Enter real credentials in this terminal. Input is hidden and not written to the log.'
read -r -s -p 'MAX_BOT_TOKEN: ' max_token </dev/tty
printf '\n'
read -r -s -p 'GIGACHAT_CREDENTIALS: ' giga_credentials </dev/tty
printf '\n'
read -r -p 'GigaChat scope [GIGACHAT_API_PERS]: ' giga_scope </dev/tty
giga_scope=${giga_scope:-GIGACHAT_API_PERS}
read -r -p 'GigaChat model [GigaChat-2-Max]: ' giga_model </dev/tty
giga_model=${giga_model:-GigaChat-2-Max}
if [[ -z "$max_token" || -z "$giga_credentials" || "$max_token" == placeholder || "$giga_credentials" == placeholder ]]; then
    echo 'Real MAX and GigaChat credentials are required. Nothing was sent to external services.' >&2
    exit 1
fi
case "$giga_scope" in GIGACHAT_API_PERS|GIGACHAT_API_B2B|GIGACHAT_API_CORP) ;; *) echo 'Unknown GigaChat scope.' >&2; exit 1;; esac
MAX_BOT_TOKEN="$max_token" GIGACHAT_CREDENTIALS="$giga_credentials" GIGACHAT_SCOPE="$giga_scope" GIGACHAT_MODEL="$giga_model" python3 - <<'PY'
from pathlib import Path
import os
p = Path('.env')
updates = {key: os.environ[key] for key in ('MAX_BOT_TOKEN','GIGACHAT_CREDENTIALS','GIGACHAT_SCOPE','GIGACHAT_MODEL')}
updates.update({
    'APP_ENV':'production','AUTH_DEV_MODE':'false','AGENT_MODE':'http',
    'COMPOSE_FILE':'docker-compose.yml:compose.hackathon.yml',
    'VITE_API_BASE':'/','CORS_ORIGINS':'http://localhost:8080','VITE_DEV_USER_ID':'',
    'GIGACHAT_VERIFY_SSL_CERTS':'true','GIGACHAT_CA_BUNDLE_FILE':'/app/certs/ca-bundle.pem',
    'EXTRA_CA_FILE':'/app/certs/ca-bundle.pem','WEBHOOK_URL':'','ASR_PROVIDER':'yandex',
})
def quote(value):
    if '\n' in value or '\r' in value or '\x00' in value:
        raise SystemExit('A credential contains a newline or NUL. Paste a single-line credential.')
    return "'" + value.replace('\\','\\\\').replace("'","\\'") + "'"
seen=set(); lines=[]
for line in p.read_text(encoding='utf-8').splitlines():
    key, sep, _ = line.partition('=')
    if sep and key in updates:
        if key not in seen:
            lines.append(key+'='+quote(updates[key]));seen.add(key)
    else:
        lines.append(line)
lines.extend(key+'='+quote(value) for key,value in updates.items() if key not in seen)
tmp=p.with_name('.env.deploy-tmp');tmp.write_text('\n'.join(lines)+'\n',encoding='utf-8');tmp.chmod(0o600);tmp.replace(p)
PY
unset max_token giga_credentials

mkdir -p certs
chmod 755 certs
curl -fsSL --retry 2 https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt -o certs/russian-root.crt
curl -fsSL --retry 2 https://gu-st.ru/content/lending/russian_trusted_sub_ca_pem.crt -o certs/russian-sub.crt
openssl x509 -in certs/russian-root.crt -noout -subject -dates
openssl x509 -in certs/russian-sub.crt -noout -subject -dates
cat /etc/ssl/certs/ca-certificates.crt certs/russian-root.crt certs/russian-sub.crt > certs/ca-bundle.pem
chmod 644 certs/*.crt certs/ca-bundle.pem

cat > deploy/hackathon-nginx.conf <<'NGINX'
server {
    listen 8080;
    root /usr/share/nginx/html;
    index index.html;
    location /api/ {
        proxy_pass http://api:8002;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }
    location / { try_files $uri /index.html; }
}
NGINX
cat > compose.hackathon.yml <<'YAML'
# gorky-hackathon-managed
x-log: &bounded-log
  driver: local
  options: {max-size: "10m", max-file: "3"}
services:
  postgres:
    logging: *bounded-log
  valkey:
    logging: *bounded-log
  mcp:
    logging: *bounded-log
  agent:
    logging: *bounded-log
    volumes: ["./certs:/app/certs:ro"]
  api:
    logging: *bounded-log
  bot:
    logging: *bounded-log
    volumes: ["./certs:/app/certs:ro"]
  miniapp:
    logging: *bounded-log
    volumes: ["./deploy/hackathon-nginx.conf:/etc/nginx/conf.d/default.conf:ro"]
YAML

docker compose config --quiet
echo 'Building sequentially. Do not close this SSH session during the build.'
docker compose --parallel 1 build mcp agent api bot miniapp
docker compose up -d --no-build

echo 'Waiting for local health endpoints (up to five minutes)...'
ready=0
for attempt in $(seq 1 60); do
    if curl -fsS --max-time 4 http://127.0.0.1:8002/health >/dev/null 2>&1 &&
       curl -fsS --max-time 4 http://127.0.0.1:8003/health >/dev/null 2>&1 &&
       curl -fsS --max-time 4 http://127.0.0.1:8081/health >/dev/null 2>&1; then
        ready=1
        break
    fi
    sleep 5
done
if [[ $ready -ne 1 ]]; then
    docker compose ps -a
    echo 'Health checks did not become ready. Check: docker compose logs --tail=80 migrate mcp agent api bot' >&2
    exit 1
fi
docker compose exec -T mcp python -m scripts.check_tools
docker compose --profile tools run --rm tests

echo 'Checking a real GigaChat request...'
model_ok=0
if docker compose exec -T agent python - <<'PY'
import sys
from app.config import Settings
from app.llm import build_chat_model
try:
    answer=build_chat_model(Settings.from_env()).invoke('Ответь одним словом: работает')
    print('GigaChat:', answer.content)
except Exception as exc:
    print('Live GigaChat check failed:',type(exc).__name__)
    sys.exit(1)
PY
then
    model_ok=1
fi
docker compose ps -a
free -h
df -h /
echo 'Text bot infrastructure is installed. Test /start and a message in MAX.'
echo 'Voice is not configured yet. Mini App is loopback-only until HTTPS/domain setup.'
echo 'Config: /opt/gorky-code/.env (do not send it in chat)'
echo 'Log: /var/log/gorky-deploy.log'
if [[ $model_ok -ne 1 ]]; then
    echo 'GigaChat did not pass its live check. Containers were kept for diagnosis.' >&2
    exit 2
fi
touch .gorky-vps-first-run-complete
echo '=== SETUP CHECKS PASSED; now verify actual replies in MAX ==='
