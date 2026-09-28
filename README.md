# Job Hunter Bot

FastAPI foundation, Remote OK collection and a Telegram daily job digest.
PostgreSQL and Redis run in Docker; Python processes run locally through Poetry.

All application messages, source comments, documentation and tests are written in English.

## Development

Install dependencies with `poetry install`. On a fresh checkout copy
`.env.example` to `.env`; preserve an existing file and keep secrets out of Git.
PostgreSQL uses `DB_HOST/PORT/USER/PASS/NAME`. If port 5432 is occupied, use
`DB_PORT=5433`. Changing environment credentials does not change an initialized
database volume.

```bash
docker compose up -d postgres redis
docker compose ps
docker compose exec redis redis-cli ping
poetry run alembic upgrade head
poetry run alembic current
```

Terminal 1:

```bash
poetry run celery -A src.tasks.celery_app:celery_app worker -l INFO
```

Terminal 2 (one Beat instance):

```bash
poetry run celery -A src.tasks.celery_app:celery_app beat -l INFO
```

Terminal 3 (one polling instance per bot):

```bash
poetry run python -m src.scripts.telegram_polling
```

Optional API:

```bash
poetry run uvicorn src.main:app --reload
```

`GET /health` returns `{"status": "ok"}`. Polling stays outside Celery.
Configure `TELEGRAM_BOT_TOKEN` and the owner's private `TELEGRAM_CHAT_ID`.
The user must have started the bot. Blank credentials disable delivery.
Chat ID is used only to bootstrap the owner; digest sends use each active
`UserORM.telegram_id`. Existing inactive users remain inactive.

Redis 7 is bound to loopback, uses an AOF volume and provides the broker, result
backend and collector locks. PostgreSQL 16 also binds to loopback and retains
data in its named volume. Python services are not containerized.
Stop local worker/Beat/polling with Ctrl+C; `docker compose stop` stops databases
without deleting their volumes. Beat's local schedule files are Git-ignored.

## Settings

| Setting | Default |
| --- | --- |
| REDIS_HOST | localhost |
| REDIS_PORT | 6379 |
| REDIS_DB | 0 |
| computed REDIS_URL | redis://localhost:6379/0 |
| SCHEDULER_TIMEZONE | America/Montevideo |
| TRIAL_DAYS | 7 |
| FREE_DIGEST_TIME | 09:00 |
| FREE_MIN_SCORE | 70 |
| FREE_MAX_JOBS_PER_DIGEST | 10 |

Digest time is parsed as a local Python `time`; timezone offsets are rejected.
The scheduler timezone must be an IANA name. Celery uses UTC.
The old `MIN_NOTIFICATION_SCORE` and `MAX_NOTIFICATIONS_PER_RUN` settings remain
accepted for compatibility but no longer control collection or digest delivery.

## Collection

`RemoteOKCollector -> JobDTO -> NormalizationService -> JobSaveService -> PostgreSQL`.
No filtering, scoring or Telegram delivery runs in collection.

`JobPipeline(save_service).run(jobs)` returns
`CollectionResult(received, new, duplicates, failed)`.
`CollectionService(sessions, redis, timezone).collect_remoteok(expected_next_run=None)`
adds the source lock, HTTP collection and persistent scheduling.
Invalid normalized jobs increment `failed`; database errors abort the run.
HTTP errors, rate limits and invalid source responses raise `CollectionError`
instead of appearing as successful empty responses.

Manual collection, even without Telegram credentials:

```bash
poetry run python -m src.scripts.collect_remoteok
```

Or enqueue a worker task:

```bash
poetry run python -c 'from src.tasks.jobs import collect_remoteok; print(collect_remoteok.delay().id)'
```

Only Remote OK is registered. Its policy has three local windows:
**02:00–04:00, 10:00–12:00, 18:00–20:00**, in `SCHEDULER_TIMEZONE`.
On first dispatch, the missing state is initialized in the nearest window
(including the remainder of the current window). After a successful run, stdlib
`random.randrange` chooses a second inside the next window, excluding its end.
The UTC timestamp is saved once as `collector_states.next_run_at`.
Ordinary dispatcher ticks and restarts reuse that value; imports never run HTTP.

A dispatcher polls the database every 15 minutes. Thus actual collection can
start up to about 15 minutes after the selected timestamp, plus queue delay.
A retry after failure/partial collection is scheduled one hour later; retries
can occur outside regular windows. There is no automatic immediate retry loop.

The per-source Redis lock uses a token-checked Lua release and a 660-second TTL.
Collection work has a 510-second async deadline and the whole service call
has a 600-second deadline (including manual runs); Celery has 540/600-second
soft/hard limits. A duplicate running collector skips. Queued scheduled tasks
carry the expected timestamp and skip once the stored schedule has moved.
Manual collection intentionally bypasses the due-time check but respects the lock.
After a killed worker the lease expires and a later dispatcher can try again.

`collector_states` stores source (unique), last start/success/finish, next run,
status, sanitized error type, and creation/update timestamps.

Persistence preserves the existing source/external ID unique constraint and
company/title fingerprint deduplication. Fingerprint matching is a heuristic;
only source identity has a database uniqueness guarantee. JobSaveService owns a
transaction per job, committing new rows and rolling back duplicates/errors.
DTOs stay independent of ORM models; timestamps must be aware and are stored in
UTC. Raw SQL updates must explicitly update `updated_at`.

## Daily delivery

Beat tasks:

| Task | Interval / trigger |
| --- | --- |
| scheduler.dispatch_collectors | 15 minutes |
| scheduler.dispatch_digests | 5 minutes |
| jobs.collect_remoteok | Due collector or manual task |
| notifications.send_daily_digest | Due user or manual task |

Tasks are thin `asyncio.run` wrappers. Every invocation creates and disposes its
own async database engine and Redis client; pooled connections never cross event
loops. Both Celery serializers are JSON. Worker prefetch is one.

`DailyDigestService(sessions, client, entitlements).send(user_id, expected_date=None)`
is the reusable delivery API. The dispatcher reads active users and enabled
preferences, resolves entitlements, converts UTC now with `ZoneInfo`, and checks
whether local digest time has passed. Delivery normally occurs within the next
5–10 minutes, depending on worker load. Missed times can catch up later the same
local day. A queued task for a different local date skips.

Candidates are jobs for which **no notification record for this user exists**,
irrespective of creation time. Thus older jobs and jobs omitted by yesterday's
limit remain eligible. Every candidate passes the existing `FilterService`
and `ScoringService`. Results sort by score descending, then job ID for ties;
effective threshold and maximum count determine the selection. Scoring weights
are unchanged. `default_user_filters(timezone)` supplies the existing Python,
remote, Worldwide/LATAM/South America/Uruguay profile and excludes US-only work.
Filter persistence is deferred; this profile is shared across users.

Before any Telegram request, the service commits a `digest_runs` reservation
with **UNIQUE(user_id, local_date)**. Concurrent or repeated tasks cannot reserve
the same date. Empty selection records `empty` and sends no message.
A nonempty run sends a short summary (up to five top titles), then existing job
cards with feedback buttons, through `NotificationService`. Progress and summary
message ID are recorded. Final status is `sent`, `partial` or `failed`.
An interrupted run can remain `pending`; every status prevents another attempt
that day. Dates follow the user's timezone, including DST and UTC date rollover.

The existing **UNIQUE(user_id, job_id)** notification reservation is committed
before each individual message. Existing `sent`, `pending` and `failed` records
are never sent automatically again. Telegram timeout and DB failure after an
HTTP send are ambiguous, so this MVP prioritizes avoiding duplicates over
guaranteed delivery. Summary/individual sends and database writes cannot share
one atomic transaction. A failed summary or crash can leave today's digest
incomplete; unattempted jobs stay candidates for a later day. No retry engine or
daily reservation deletion is performed automatically.

## Preferences, trial and subscriptions

Migration `54383f510932` follows `664c622669e5` and adds:

- `collector_states`: persistent source schedule and run history fields.
- `user_notification_settings`: unique user FK, IANA timezone, local digest time,
  score threshold, enabled flag, maximum jobs, creation/update timestamps.
- `user_subscriptions`: unique user FK, trial/active/expired status,
  trial start/end, subscription start/end, creation/update timestamps.
- `digest_runs`: unique user/local date, status, start/finish, summary message ID,
  selected/sent/failed/skipped counts and last error.

Polling startup and digest dispatch bootstrap missing preferences/subscriptions,
including the existing owner. Defaults use America/Montevideo, 09:00, score 70,
10 jobs and a seven-day trial. Inserts use ON CONFLICT DO NOTHING and never reset
stored preferences or renew an expired trial.

`EntitlementService.effective(preferences, subscription, now)` centralizes rules:

- Trial with `now < trial_ends_at`: stored custom time and threshold apply.
- Active with no end, or `now < subscription_ends_at`: same premium capabilities.
- Otherwise: `FREE_DIGEST_TIME` and `FREE_MIN_SCORE` apply without overwriting
  stored custom values. Timezone and saved job limit remain available to everyone.

For example, a trial user storing 11:30 / score 42 receives those effective
values. After trial expiry, the same record resolves to 09:00 / score 70.
An active subscription restores 11:30 / 42. A free Madrid user receives 09:00
Europe/Madrid, and a free Uruguay user 09:00 America/Montevideo.
There are no payment integrations or Telegram preference commands yet.

## Manual digest check

Inspect registered tasks:

```bash
poetry run celery -A src.tasks.celery_app:celery_app inspect registered
```

Bootstrap/check the dispatcher (this can enqueue today's real delivery):

```bash
poetry run python -c 'from src.tasks.scheduler import dispatch_digests; print(dispatch_digests.delay().id)'
```

For development, edit the owner's row in PostgreSQL, setting an active trial,
a local `digest_time` a few minutes ahead, and a small `max_jobs_per_digest`.
Use the existing user ID and preserve original values for restoration:

```bash
docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

Inspect `user_notification_settings`, `user_subscriptions`, `digest_runs`
and `notifications`. After delivery repeat the dispatcher: today's run must
not produce a second summary. Empty selection also consumes today's attempt.
Do not delete real daily reservations to repeat a test. Use fake repositories
in unit tests for repeated scenarios. Temporarily expire trial to inspect
effective defaults, then restore it; no need to wait seven days.

## Telegram commands

Commands are handled in private chats. Public `/start` and `/help` do not register
arbitrary users. Startup reuses `OwnerService.get_or_create` for the configured
owner and initializes missing delivery settings through the existing bootstrap.
Data commands require an existing active user. Groups and mismatched sender/chat
IDs receive `This command is not available.` without exposing account data.

| Command | Behavior |
| --- | --- |
| /start | Show the introduction |
| /help | List all seven commands |
| /status | Read collector state, total jobs, effective digest settings and the user's latest digest attempt from PostgreSQL |
| /saved | Show up to ten most recently saved jobs, without descriptions |
| /filters | Show the current shared filter profile and effective digest time/minimum score |
| /collect | Owner only: enqueue Remote OK collection |
| /digest | Owner only: enqueue today's digest immediately |

`CommandHandler(...).handle(message)` in `src/bot/commands.py` handles commands.
It receives repositories, TelegramClient, a dispatcher, EntitlementService,
the configured owner Telegram ID, the bot username and an injectable clock.
`route_update(update, commands=..., callbacks=...)` keeps command handling
separate from existing callback parsing. Plain messages and edited messages
are ignored. Commands support a matching `@BotUsername` suffix and ignore commands
addressed to other bots. The username is obtained once at startup using
[getMe](https://core.telegram.org/bots/api#getme).
[getUpdates](https://core.telegram.org/bots/api#getupdates) now requests both
`message` and `callback_query` updates. Existing offset and callback behavior remains.

`BotQueryRepository` performs read-only status/settings queries.
`FeedbackRepository.get_saved_jobs_for_user(user_id, limit=10)` selects only
that user's `saved` feedback, newest update first. Saved-job output is split
into messages within Telegram's size limit.
Unknown commands reply: `Unknown command. Use /help to see available commands.`

Admin permission checks compare the verified message sender against
`TELEGRAM_CHAT_ID` and also require an active persisted user. No numeric owner
ID is hardcoded. Without an owner ID, admin commands are disabled.
`CeleryCommandDispatcher` publishes using `asyncio.to_thread`:

```python
collect_remoteok.delay()
send_daily_digest.delay(user.id, run_now=True)
```

Handlers wait only for publication, never for task completion. Successful
publication replies `Collection started.` or `Digest started.`; publication
errors produce `Failed to start collection.` or `Failed to start digest.`.
These acknowledgements do not imply the worker has completed the job.
Replies use plain text. Logs record command categories and sanitized error types,
not raw command arguments or Telegram secrets. A reply timeout is logged without
replaying a task that may already have been queued.

Manual `run_now=True` bypasses only the local scheduled-time check. It preserves
active/enabled-user checks, effective filters and threshold, individual delivery
reservations and the one-attempt-per-local-day constraint. Therefore `/digest`
can acknowledge dispatch without sending cards if today was already attempted,
delivery is disabled, or no matching jobs remain. `/status` displays the latest
attempt status, including `empty`, `partial`, `failed` or `pending`.

To check manually, start worker, Beat and polling using the commands above, then
send `/start`, `/help`, `/status`, `/saved` and `/filters` in the owner's
private chat. With the worker running, try `/collect` and `/digest`.
Use a different account to confirm admin commands are denied.
Unit tests use fake clients and dispatchers, never real Telegram or Celery workers.

BotFather command menu (configure manually; the application does not change it):

```text
start - About the bot
help - Show available commands
status - Bot and collector status
saved - Saved jobs
filters - Current job filters
collect - Run collection now
digest - Send digest now
```

## Feedback

Job cards keep `Save` and `Not suitable` buttons, handled by the independent
polling process. Callback data is `save:<job_id>` or `reject:<job_id>`.
The handler checks the Telegram sender against an active persisted user, stores
`saved`/`rejected` feedback and answers the callback. Unknown users are not
registered automatically. Repeated presses update one unique user/job row.
Feedback does not modify notification status or scoring weights.

Polling confirms Telegram offsets on the next request and handles restarts
idempotently. It uses a fresh database session per callback and a 30-second
long-poll timeout. Network errors retry after three seconds. Do not run multiple
pollers for the same token or combine polling with an active webhook.

## Checks

```bash
poetry run ruff check .
poetry run black --check .
poetry run pytest
poetry run alembic check
```

Unit tests use fake repositories/clients and standard-library mocks, requiring
no PostgreSQL, Redis or real Telegram requests. They cover scheduling windows,
persisted jitter, timezones, daily uniqueness, subscription boundaries, filtering,
ranking, caps, delivery failures, locks, callbacks and task registration.
Migrations, broker/worker execution and live Telegram delivery are separate
manual checks.
