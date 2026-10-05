# VPS deployment report

Date: 2026-10-05 (America/Montevideo). Source baseline: bfe8fcd.
Server: 179.236.245.161. Directory: /opt/job_hunter_bot.
OS: Ubuntu 26.04.1 LTS; 2 CPUs and approximately 8 GiB RAM.
Docker Engine: 29.8.2. Docker Compose: v5.6.0.

## Runtime outcome

| Service | Status | Verification |
| --- | --- | --- |
| PostgreSQL | Running, healthy | PostgreSQL 16; persistent volume; real migrations and 87 retained jobs |
| Redis | Running, healthy | Redis 7 AOF; broker connectivity and marker retained after restart/reboot |
| Celery worker | Running, healthy | Registered tasks, addressed ping and real successful WWR task |
| Celery Beat | Running | Persistent schedule, startup log and automatic reboot recovery |
| Telegram polling | Running | Repeated getUpdates HTTP 200; /status reply confirmed by the user |
| FastAPI | Running, healthy | Internal GET /health returns {"status":"ok"} |

The four Python services use the same job-hunter-bot:production image. Their
processes run as UID 10001. The image contains no .env and no dev pytest package.
It uses Python 3.12 slim, locked production dependencies and system timezone data.
All six services use restart: unless-stopped; Docker is enabled at boot.

## Initial environment and data

No deployment directory, containers or Docker volumes existed before this run.
Docker, Compose, git, curl and rsync were already installed. The package index
was updated; no host PostgreSQL or Redis package was installed.

Source was transferred via SSH/rsync, excluding secrets, Git metadata, virtualenv,
caches and persistent data directories. No rsync deletion was used. After a
separate check confirmed server .env was absent, the user's explicitly authorized
first-deploy copy was made securely with exclusive creation and mode 600. Its
contents were never printed and it was not embedded in the image. The update
script excludes .env and refuses to initialize it implicitly.

The initial secret-copy attempt was rejected by automatic review, which applied
the update-script exclusion to first deploy. A read-only probe and the user's
section 5 instruction established authorization; the reviewed retry succeeded.
There is no outstanding approval block.

Production Compose sets MODE=PROD, DB_HOST=postgres, DB_PORT=5432,
REDIS_HOST=redis and REDIS_PORT=6379. Existing scheduler/digest defaults remain
active unless customized through the environment. Local source .env is unchanged.

Volumes: job-hunter-bot_postgres_data, job-hunter-bot_redis_data and
job-hunter-bot_celery_beat_data. No volume was removed.

## Functional verification

Existing migrations were applied before application services started.
Alembic current revision: **49f75b591334 (head)**. No new migration, downgrade or
historical-data cleanup was performed.

A single /status request was routed through the existing CommandHandler and
accepted by Telegram for the configured owner's private chat. The user then
confirmed receiving the response after being asked to test /status from Telegram.
Bot: @remotejobhunterbot. No forced digest or manual mass notification was queued.

One WWR task was published through the existing Celery task and completed on the
worker: received 89, new 87, duplicates 2, failed 0. No collector/filter/scoring
logic was changed. Normal scheduled production tasks remain enabled.

Worker, Beat and polling were restarted. The deployment/update script was also
exercised: rsync, build, dependency health, stop writers, existing migrations and
restart. Original database rows, Redis marker and server environment hash were
preserved. Migration commands have stdin redirected from /dev/null so Docker
cannot consume the remaining remote deployment script.

After these checks, the explicitly requested VPS reboot was performed. SSH
recovered, the boot ID changed, and all six existing containers started
**without running docker compose up after reboot**. Database records, Redis marker
and environment integrity were checked again; API health and worker health passed.

Final persistence evidence:

```json
{"jobs_count": 87, "original_jobs_retained": true, "redis_marker_retained": true, "environment_unchanged": true, "revision": "49f75b591334", "boot_changed": true}
```

## Deployment files

- Dockerfile: shared production application image, non-root process, no dev group.
- .dockerignore: excludes secrets and development/runtime data from build context.
- docker-compose.production.yml: six services, durable volumes, restart policy,
  dependency healthchecks, capped logs and no published host ports.
- scripts/deploy.sh: safe source update, one shared image build, migrations and
  readiness checks; no environment copy, volume deletion or downgrade.
- scripts/deploy-excludes.txt: source-transfer exclusions.
- README.md: production setup and update instructions; local Compose unchanged.
- docs/vps-deployment-report.md and docs/vps-deployment-logs.txt: this report and
  sanitized post-reboot diagnostics.

Future update, from the local project:

```bash
./scripts/deploy.sh
```

The script defaults to root@179.236.245.161:/opt/job_hunter_bot; overrides are
DEPLOY_TARGET and DEPLOY_PATH. It stops only application processes while migrating,
keeps database/Redis running, and leaves application services stopped for inspection
if migration fails. Removed source files are not deleted automatically. Backups
and a separate security/onboarding stage remain operational work, not this deploy.

## Final docker compose ps

```text
NAME                                IMAGE                       COMMAND                  SERVICE            CREATED          STATUS                   PORTS
job-hunter-bot-api-1                job-hunter-bot:production   "uvicorn src.main:ap…"   api                5 minutes ago    Up 3 minutes (healthy)
job-hunter-bot-celery_beat-1        job-hunter-bot:production   "celery -A src.tasks…"   celery_beat        5 minutes ago    Up 3 minutes
job-hunter-bot-celery_worker-1      job-hunter-bot:production   "celery -A src.tasks…"   celery_worker      5 minutes ago    Up 3 minutes (healthy)
job-hunter-bot-postgres-1           postgres:16                 "docker-entrypoint.s…"   postgres           21 minutes ago   Up 3 minutes (healthy)   5432/tcp
job-hunter-bot-redis-1              redis:7                     "docker-entrypoint.s…"   redis              21 minutes ago   Up 3 minutes (healthy)   6379/tcp
job-hunter-bot-telegram_polling-1   job-hunter-bot:production   "python -m src.scrip…"   telegram_polling   5 minutes ago    Up 3 minutes
```

5432/tcp and 6379/tcp here denote internal container ports; no host port is
published. The API is also internal. The only public listener is SSH on 22/tcp
(IPv4/IPv6); DNS and time-service listeners are loopback only. Firewall, SSH port
and root-login settings were not changed.

Final host listeners:

```text
Netid State  Recv-Q Send-Q Local Address:Port Peer Address:PortProcess
udp   UNCONN 0      0         127.0.0.54:53        0.0.0.0:*    users:(("systemd-resolve",pid=473,fd=18))
udp   UNCONN 0      0      127.0.0.53%lo:53        0.0.0.0:*    users:(("systemd-resolve",pid=473,fd=16))
udp   UNCONN 0      0          127.0.0.1:323       0.0.0.0:*    users:(("chronyd",pid=889,fd=4))
udp   UNCONN 0      0              [::1]:323          [::]:*    users:(("chronyd",pid=889,fd=5))
tcp   LISTEN 0      4096      127.0.0.54:53        0.0.0.0:*    users:(("systemd-resolve",pid=473,fd=19))
tcp   LISTEN 0      4096   127.0.0.53%lo:53        0.0.0.0:*    users:(("systemd-resolve",pid=473,fd=17))
tcp   LISTEN 0      4096         0.0.0.0:22        0.0.0.0:*    users:(("sshd",pid=863,fd=3),("systemd",pid=1,fd=101))
tcp   LISTEN 0      4096            [::]:22           [::]:*    users:(("sshd",pid=863,fd=4),("systemd",pid=1,fd=102))
```

## Safe logs

Full sanitized worker/Beat/polling tails are in vps-deployment-logs.txt. Credentials,
owner ID and token-containing Telegram URLs are redacted. Log timestamps use UTC.
Representative signals after reboot:

```text
telegram_polling-1  | INFO:httpx:HTTP Request: POST https://api.telegram.org/bot<redacted>/getUpdates "HTTP/1.1 200 OK"
telegram_polling-1  | INFO:httpx:HTTP Request: POST https://api.telegram.org/bot<redacted>/getUpdates "HTTP/1.1 200 OK"
telegram_polling-1  | INFO:httpx:HTTP Request: POST https://api.telegram.org/bot<redacted>/getUpdates "HTTP/1.1 200 OK"
telegram_polling-1  | INFO:httpx:HTTP Request: POST https://api.telegram.org/bot<redacted>/getUpdates "HTTP/1.1 200 OK"
telegram_polling-1  | INFO:httpx:HTTP Request: POST https://api.telegram.org/bot<redacted>/getUpdates "HTTP/1.1 200 OK"
telegram_polling-1  | INFO:httpx:HTTP Request: POST https://api.telegram.org/bot<redacted>/getUpdates "HTTP/1.1 200 OK"
celery_worker-1     | [2026-10-05 17:57:50,541: INFO/MainProcess] Connected to redis://redis:6379/0
celery_worker-1     | [2026-10-05 17:57:51,573: INFO/MainProcess] worker@57e58e5c8974 ready.
celery_worker-1     | [2026-10-05 17:59:57,573: INFO/MainProcess] Connected to redis://redis:6379/0
celery_worker-1     | [2026-10-05 17:59:58,613: INFO/MainProcess] worker@57e58e5c8974 ready.
celery_beat-1       | [2026-10-05 17:57:49,878: INFO/MainProcess] beat: Starting...
celery_beat-1       | [2026-10-05 17:59:57,355: INFO/MainProcess] beat: Starting...
```

## Checks and Git

Deployment-specific checks passed: Docker build with locked main dependencies,
Compose config validation, bash syntax, git diff whitespace, migration execution,
API/worker health, real collection, Telegram status, data/environment persistence
and reboot recovery. Existing Python business code was unchanged, so the already
passing unit/integration suite was not rerun for container/documentation changes.
No commit or push was made. Python runtime services remain running on the VPS.

Git snapshot follows; tracked diff stats omit the new deployment files, which
are listed by git status.

```text
$ git diff --stat
 README.md | 57 +++++++++++++++++++++++++++++++++++++++++++++++++++++++++
 1 file changed, 57 insertions(+)
```

```text
$ git status --short --branch
## main...origin/main
 M README.md
?? .dockerignore
?? Dockerfile
?? docker-compose.production.yml
?? docs/vps-deployment-logs.txt
?? docs/vps-deployment-report.md
?? scripts/
```
