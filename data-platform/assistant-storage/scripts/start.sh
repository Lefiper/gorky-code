#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ ! -f .env.docker ]; then
    umask 077
    owner_password=$(od -v -An -N32 -tx1 /dev/urandom | tr -d ' \n')
    app_password=$(od -v -An -N32 -tx1 /dev/urandom | tr -d ' \n')
    printf 'STACK_DB_PASSWORD=%s\nSTACK_APP_PASSWORD=%s\nSTACK_POSTGRES_PORT=55432\nSTACK_REDIS_PORT=6380\nSTACK_MCP_PORT=8001\n' "$owner_password" "$app_password" > .env.docker
    echo 'Created .env.docker with random local passwords (not displayed).'
fi
docker compose --env-file .env.docker -f compose.full.yaml up -d --build --wait
echo 'Stack is ready. MCP: http://127.0.0.1:8001/mcp (or your configured port).'
