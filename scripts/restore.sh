#!/bin/sh
set -eu
file=${1:?Usage: sh scripts/restore.sh backup.dump NEW_database}
target=${2:?Specify a NEW database name}
case "$target" in ''|*[!a-zA-Z0-9_]*) echo 'Invalid database name' >&2; exit 1;; esac
docker compose exec -T postgres createdb -U assistant_owner "$target"
docker compose exec -T postgres pg_restore -U assistant_owner --exit-on-error --single-transaction --no-owner --no-acl --dbname "$target" < "$file"
docker compose exec -T postgres psql -U assistant_owner -d "$target" -v ON_ERROR_STOP=1 -c 'SELECT count(*) FROM events; SELECT version FROM schema_migrations ORDER BY version;'
