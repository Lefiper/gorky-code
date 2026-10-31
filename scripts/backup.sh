#!/bin/sh
set -eu
file=${1:?Usage: sh scripts/backup.sh backup.dump}
umask 077
docker compose exec -T postgres pg_dump -U assistant_owner -d assistant_mvp --format=custom --no-owner --no-acl > "$file"
docker compose exec -T postgres pg_restore --list < "$file" > /dev/null
