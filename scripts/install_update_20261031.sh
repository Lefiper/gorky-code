#!/usr/bin/env bash
# User-run VPS update. No tests, no secret replacement, no volume deletion.
set -Eeuo pipefail
umask 077
target=/opt/gorky-code
stage="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
stamp=$(date +%Y%m%d-%H%M%S)
backup="/root/gorky-backup-$stamp"
mkdir -p "$backup"
exec > >(tee -a "$backup/update.log") 2>&1
trap 'echo "UPDATE STOPPED at line $LINENO. Backup and log: $backup"' ERR
cd "$target"
test -f .env
test -f "$stage/UPDATE_FILES.txt"
echo "[1/7] Saving current source, database and running image IDs"
tar --exclude='./.git' --exclude='./node_modules' --exclude='*/node_modules' --exclude='*/__pycache__' --exclude='*/.pytest_cache' -czf "$backup/project.tar.gz" .
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$backup/postgres.dump"
for service in mcp agent bot; do
  container=$(docker compose ps -q "$service")
  test -n "$container"
  image=$(docker inspect --format '{{.Image}}' "$container")
  docker image tag "$image" "gorky-$service:before-$stamp"
done
cat > "$backup/rollback.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd /opt/gorky-code
docker compose stop bot agent mcp
tar -xzf '$backup/project.tar.gz' -C /opt/gorky-code
docker image tag 'gorky-mcp:before-$stamp' gorky-mcp:local
docker image tag 'gorky-agent:before-$stamp' gorky-agent:local
docker image tag 'gorky-bot:before-$stamp' gorky-bot:local
docker compose up -d --no-deps --force-recreate mcp agent bot
echo 'Code and images restored. Database and running persistent Valkey were kept.'
EOF
chmod 700 "$backup/rollback.sh"

echo "[2/7] Copying the reviewed source delta; keeping live env, certs, HTTPS and webhook"
export UPDATE_STAGE="$stage" UPDATE_TARGET="$target"
python3 - <<'PY'
from pathlib import Path
import os, shutil
source=Path(os.environ['UPDATE_STAGE']).resolve()
target=Path(os.environ['UPDATE_TARGET']).resolve()
for name in (source/'UPDATE_FILES.txt').read_text().splitlines():
    rel=Path(name)
    if rel.is_absolute() or '..' in rel.parts or str(rel) in {'.env','deploy/Caddyfile','docker-compose.yml','compose.webhook.yml','compose.hackathon.yml'}:
        raise SystemExit('Forbidden update path: '+name)
    if any(part.startswith('.env') and part != '.env.example' for part in rel.parts):
        raise SystemExit('Secret file in update manifest')
    dest=target/rel
    if dest.is_symlink() or not dest.resolve().is_relative_to(target):
        raise SystemExit('Unexpected target path: '+name)
    dest.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(source/rel,dest)
    dest.chmod(0o644)
env=target/'.env'
text=env.read_text()
values={}
for line in text.splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
        key,value=line.split('=',1);values[key.strip()]=value.strip().strip("'\"")
files=values.get('COMPOSE_FILE','docker-compose.yml').split(':')
if 'compose.persistence.yml' not in files: files.append('compose.persistence.yml')
updates={'AGENT_HISTORY_LIMIT':'40','AGENT_HISTORY_TTL_SECONDS':'86400',
         'REDIS_HISTORY_LIMIT':'40','REDIS_TTL_SECONDS':'86400',
         'AGENT_IDEMPOTENCY_TTL_SECONDS':'86400','COMPOSE_FILE':':'.join(files)}
lines=[line for line in text.splitlines() if line.split('=',1)[0].strip() not in updates]
lines.extend(f"{key}='{value}'" for key,value in updates.items())
env.write_text('\n'.join(lines)+'\n');env.chmod(0o600)
PY

echo "[3/7] Building MCP, agent and bot (tests are not run)"
docker compose --parallel 1 build mcp agent bot
echo "[4/7] Pausing chat and preserving live Valkey data before adding its volume"
docker compose stop bot agent
docker compose exec -T valkey valkey-cli CONFIG SET appendonly yes
ready=0
for n in $(seq 1 60); do
  info=$(docker compose exec -T valkey valkey-cli INFO persistence | tr -d '\r')
  if printf '%s\n' "$info" | grep -q '^aof_rewrite_in_progress:0$' && printf '%s\n' "$info" | grep -q '^aof_rewrite_scheduled:0$' && printf '%s\n' "$info" | grep -q '^aof_last_bgrewrite_status:ok$'; then ready=1; break; fi
  sleep 1
done
test "$ready" = 1
docker compose stop valkey
mkdir -p "$backup/valkey-data"
container=$(docker compose ps -aq valkey)
docker cp "$container:/data/." "$backup/valkey-data/"
docker volume create gorky-code_valkey_data > /dev/null
docker run --rm --user 0 --entrypoint sh \
  -v gorky-code_valkey_data:/data -v "$backup/valkey-data:/seed:ro" \
  valkey/valkey:8-alpine -c 'if [ -z "$(ls -A /data)" ]; then cp -a /seed/. /data/; chown -R valkey:valkey /data; fi'
docker compose up -d --no-deps valkey
echo "[5/7] Applying migration 005 and minimal PostgreSQL grants"
docker compose run --rm --no-deps migrate
echo "[6/7] Starting updated MCP, agent and webhook bot"
docker compose up -d --no-deps --force-recreate mcp agent bot
echo "[7/7] Installation complete; no automated tests were run"
docker compose --profile https ps -a
echo "Backup: $backup"
echo "Rollback command: bash $backup/rollback.sh"
echo 'Send a NEW message to the bot. Old cached replies remain unchanged.'
