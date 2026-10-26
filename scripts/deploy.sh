#!/usr/bin/env bash
# Update an initialized deployment. Secrets and persistent data stay on the VPS.
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
deploy_target="${DEPLOY_TARGET:-user@deploy-host}"
deploy_path="${DEPLOY_PATH:-/opt/job_hunter_bot}"
backup_root="${BACKUP_ROOT:-/var/backups/job_hunter_bot}"

# Reject shell metacharacters before using these values in remote commands.
[[ "$deploy_target" =~ ^[a-zA-Z0-9_.@:-]+$ ]] || { echo 'Invalid DEPLOY_TARGET' >&2; exit 1; }
[[ "$deploy_path" =~ ^/[a-zA-Z0-9_./-]+$ && "$deploy_path" != / ]] || { echo 'Invalid DEPLOY_PATH' >&2; exit 1; }
[[ "$backup_root" =~ ^/[a-zA-Z0-9_./-]+$ && "$backup_root" != / ]] || { echo 'Invalid BACKUP_ROOT' >&2; exit 1; }
ssh_options=(-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=3)

ssh "${ssh_options[@]}" "$deploy_target" "test -f '$deploy_path/.env'" || {
    echo 'Initialize the server .env securely before deploying; it is never copied by this script.' >&2
    exit 1
}
ssh "${ssh_options[@]}" "$deploy_target" "install -d -m 700 '$backup_root'"
ssh "${ssh_options[@]}" "$deploy_target" "test -d '$backup_root'" || {
    echo 'Backup directory is unavailable' >&2
    exit 1
}
rsync --archive --compress \
    --exclude-from="$project_root/scripts/deploy-excludes.txt" \
    -e 'ssh -o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=3' \
    "$project_root/" "$deploy_target:$deploy_path/"

ssh "${ssh_options[@]}" "$deploy_target" "bash -s -- '$deploy_path' '$backup_root'" <<'REMOTE'
set -euo pipefail
umask 077
cd -- "$1"
backup_root="$2"
compose=(docker compose -f docker-compose.production.yml)
"${compose[@]}" config --quiet
"${compose[@]}" exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' </dev/null > "$backup_root/db-backup-$(date -u +%Y%m%dT%H%M%SZ).sql"
find "$backup_root" -maxdepth 1 -type f -name 'db-backup-*.sql' -exec chmod 600 {} +
find "$backup_root" -maxdepth 1 -type f -name 'db-backup-*.sql' -mtime +7 -delete
"${compose[@]}" build api
"${compose[@]}" up -d --wait postgres redis
# Stop writers before migrating; keep database/Redis containers and volumes.
"${compose[@]}" stop telegram_polling celery_beat celery_worker api
"${compose[@]}" run --rm --no-deps -T api poetry run alembic upgrade head </dev/null
"${compose[@]}" run --rm --no-deps -T api poetry run alembic current </dev/null
"${compose[@]}" up -d --wait --wait-timeout 180
"${compose[@]}" ps
REMOTE
