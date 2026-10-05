#!/usr/bin/env bash
# Update an initialized deployment. Secrets and persistent data stay on the VPS.
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
deploy_target="${DEPLOY_TARGET:-root@179.236.245.161}"
deploy_path="${DEPLOY_PATH:-/opt/job_hunter_bot}"

# Reject shell metacharacters before using these values in remote commands.
[[ "$deploy_target" =~ ^[a-zA-Z0-9_.@:-]+$ ]] || { echo 'Invalid DEPLOY_TARGET' >&2; exit 1; }
[[ "$deploy_path" =~ ^/[a-zA-Z0-9_./-]+$ && "$deploy_path" != / ]] || { echo 'Invalid DEPLOY_PATH' >&2; exit 1; }
ssh_options=(-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=3)

ssh "${ssh_options[@]}" "$deploy_target" "test -f '$deploy_path/.env'" || {
    echo 'Initialize the server .env securely before deploying; it is never copied by this script.' >&2
    exit 1
}
rsync --archive --compress \
    --exclude-from="$project_root/scripts/deploy-excludes.txt" \
    -e 'ssh -o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=3' \
    "$project_root/" "$deploy_target:$deploy_path/"

ssh "${ssh_options[@]}" "$deploy_target" "bash -s -- '$deploy_path'" <<'REMOTE'
set -euo pipefail
cd -- "$1"
compose=(docker compose -f docker-compose.production.yml)
"${compose[@]}" config --quiet
"${compose[@]}" build api
"${compose[@]}" up -d --wait postgres redis
# Stop writers before migrating; keep database/Redis containers and volumes.
"${compose[@]}" stop telegram_polling celery_beat celery_worker api
"${compose[@]}" run --rm --no-deps -T api poetry run alembic upgrade head </dev/null
"${compose[@]}" run --rm --no-deps -T api poetry run alembic current </dev/null
"${compose[@]}" up -d --wait --wait-timeout 180
"${compose[@]}" ps
REMOTE
