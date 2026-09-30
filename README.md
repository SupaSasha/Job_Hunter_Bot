# Job Hunter Bot

FastAPI foundation, Remote OK, We Work Remotely and Get on Board collection, and a Telegram daily job digest.
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

`RemoteOKCollector / WeWorkRemotelyCollector / GetOnBoardCollector -> JobDTO -> NormalizationService -> JobSaveService (DeduplicationService) -> PostgreSQL`.
No filtering, scoring or Telegram delivery runs in collection.

`JobPipeline(save_service).run(jobs)` returns
`CollectionResult(received, new, duplicates, failed, cross_source_duplicates)`.
`CollectionService(sessions, redis, timezone).collect(source, expected_next_run=None)`
adds the source lock, HTTP collection and persistent scheduling.
The existing collect_remoteok method remains a compatibility wrapper.
Invalid normalized jobs increment `failed`; database errors abort the run.
HTTP errors, rate limits and invalid source responses raise `CollectionError`
instead of appearing as successful empty responses.

Manual collection, even without Telegram credentials:

```bash
poetry run python -m src.scripts.collect_remoteok
poetry run python -m src.scripts.collect_weworkremotely
poetry run python -m src.scripts.collect_getonboard
```

Or enqueue a worker task:

```bash
poetry run python -c 'from src.tasks.jobs import collect_remoteok; print(collect_remoteok.delay().id)'
```

Registered sources use separate local windows in SCHEDULER_TIMEZONE
(default America/Montevideo):

| Source | Windows | Celery task | Redis lock |
| --- | --- | --- | --- |
| remoteok | 02:00–04:00, 10:00–12:00, 18:00–20:00 | jobs.collect_remoteok | collector:remoteok:lock |
| weworkremotely | 04:00–06:00, 16:00–18:00 | jobs.collect_weworkremotely | collector:weworkremotely:lock |
| getonboard | 06:00–08:00, 20:00–22:00 | jobs.collect_getonboard | collector:getonboard:lock |

The small collector, policy and task registries contain only implemented sources.
On first dispatch, the missing state is initialized in the nearest window
(including the remainder of the current window). After a successful run, stdlib
`random.randrange` chooses a second inside the next window, excluding its end.
The UTC timestamp is saved once as `collector_states.next_run_at`.
Ordinary dispatcher ticks and restarts reuse that value; imports never run HTTP.

A dispatcher polls the database every 15 minutes. Thus actual collection can
start up to about 15 minutes after the selected timestamp, plus queue delay.
A retry after failure/partial collection is scheduled one hour later; retries
can occur outside regular windows. WWR and Get on Board HTTP 429 Retry-After can extend this delay.
There is no automatic immediate retry loop.

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

## We Work Remotely

WWR explicitly publishes a [public RSS feed](https://weworkremotely.com/remote-job-rss-feed)
for reuse with links back to its job pages. Its [API documentation](https://weworkremotely.com/api)
describes token authentication; the RSS feed needs no account or credentials.
The collector uses https://weworkremotely.com/remote-jobs.rss via httpx, with the
existing User-Agent, a timeout, a bounded response and no immediate retries.
There is no HTML page scraping or browser automation. Parsing uses stdlib
ElementTree and HTMLParser; no new dependency is required.

Public API:

- WeWorkRemotelyCollector(timeout=...).collect() -> list[JobDTO]
- parse_feed(content: bytes) -> list[JobDTO]
- parse_job_item(item: Element, collected_at=...) -> JobDTO

The source key is weworkremotely. The feed GUID supplies external_id; currently
it is the stable WWR job permalink. Missing GUID falls back to that permalink.
URLs keep the original WWR job destination and remove tracking queries/fragments.
The title is split at the feed's company/title separator. HTML descriptions are
converted to text; scripts, styles and image markup are omitted. Publication
and collection dates are UTC-aware. Missing salary, experience and timezone
fields remain None. WWR's remote-only feed supplies remote=True.

Only explicit technical skills/categories populate technologies; no description
NLP is used. Nontechnical categories are excluded. Explicit country lists take
precedence over generic Anywhere in the World labels. Headquarters/state fields
are not treated as work eligibility. Unknown regions remain empty. The existing
normalizer, fingerprint, filters and scoring are unchanged.

Standalone source check (no database writes):

```bash
poetry run python -m src.collectors.weworkremotely
```

The persistence command above runs the same CollectionService, JobPipeline and
JobSaveService used by Remote OK. It updates only WWR's collector state and sends
no Telegram messages. Jobs are available to the existing daily digest subject to
its unchanged filters, thresholds and delivery reservations.

See [the WWR stage report](docs/weworkremotely-stage-report.md) for live counts,
deduplication examples, test results and Git state.

## Get on Board

Get on Board provides an [official public API without authentication](https://www.getonbrd.com/user-manual/get-on-board-s-api).
The collector reads the documented programming category endpoint:
https://www.getonbrd.com/api/v0/categories/programming/jobs.
The [OpenAPI reference](https://www.getonbrd.com/api-doc.html) documents public
category resources, pagination and expanded relationships.

GetOnBoardCollector(timeout=20, max_pages=2, per_page=50).collect() returns
list[JobDTO]. parse_job(raw, collected_at=...) and parse_page(payload) separate
mapping from HTTP. The default scope is the first two Programming pages, at most
100 records before repeated-ID deduplication. This does not cover every category
or guarantee all recently posted jobs: the API has no documented chronological
ordering/cursor contract for this endpoint. No date cutoff is assumed. Configuration
is bounded to 1..5 pages and 1..120 records/page; pages are requested sequentially,
with a one-second pause between them. Empty, last, short (without metadata), and
repeated pages stop traversal. A later-page HTTP failure fails the whole fetch.

Expanded company, tags, modality, seniority, location_regions, location_tenants
and location_cities avoid individual job detail requests. Source id becomes
external_id; links.public_url remains the application destination. Description
sections use the shared HTML-to-text helper also used by WWR. No new dependency
or browser automation is involved.

Remote status requires an explicit true flag; hybrid, on-site and temporarily
remote modalities remain nonremote for this delivery profile. Remote is not a
region. Expanded regions/countries supply eligibility, and unrestricted
fully_remote records without restrictions map to Worldwide. Company headquarters
are not used. NormalizationService retains responsibility for canonical region,
technology and timezone values; its general Semi Senior aliases now map to middle.
There are no source-specific filtering or scoring rules.

Numeric min_salary/max_salary are preserved without currency conversion. Currency
and period remain unknown unless explicitly supplied; the checked public response
omits both. remote_zone is preserved as timezone_text when present; timezone is
never guessed from a country or prose. Published epoch timestamps and collection
timestamps are UTC-aware. Unknown optional fields stay None or empty.

Standalone source check, without DB writes:

```bash
poetry run python -m src.collectors.getonboard
```

The persistence script above uses the existing CollectionService, source lock,
CollectorState and JobPipeline. Jobs enter the shared jobs table and existing
daily digest; collection sends no messages. /collect publishes three independent
tasks, /status displays all three states, and job cards use the shared source
name helper to display Get on Board. See [the stage report](docs/getonboard-stage-report.md)
for real collection counts, LATAM observations and verification results.

## Daily delivery

Beat tasks:

| Task | Interval / trigger |
| --- | --- |
| scheduler.dispatch_collectors | 15 minutes |
| scheduler.dispatch_digests | 5 minutes |
| jobs.collect_remoteok | Due Remote OK collector or manual task |
| jobs.collect_weworkremotely | Due WWR collector or manual task |
| jobs.collect_getonboard | Due Get on Board collector or manual task |
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
Preferences can be changed through /settings. There are no payment integrations.

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
| /help | List public commands; show a separate admin section to the owner |
| /status | Read collector state, total jobs, effective digest settings and the user's latest digest attempt from PostgreSQL |
| /saved | Show up to ten most recently saved jobs, without descriptions |
| /filters | Show the current shared filter profile and effective digest time/minimum score |
| /settings | View effective settings and edit timezone, digest time and score |
| /collect | Owner only: enqueue Remote OK, We Work Remotely and Get on Board collection |
| /digest | Owner only: enqueue today's digest immediately |
| /stats [24h\|7d\|30d] | Owner only: read historical pipeline statistics; default 7d |

`CommandHandler(...).handle(message)` in `src/bot/commands.py` handles commands.
It receives repositories, TelegramClient, a dispatcher, EntitlementService,
the configured owner Telegram ID, the bot username and an injectable clock.
`route_update(update, commands=..., callbacks=..., settings=...)` keeps command handling
separate from existing callback parsing. Plain messages and edited messages
are ignored. Commands support a matching `@BotUsername` suffix and ignore commands
addressed to other bots. The username is obtained once at startup using
[getMe](https://core.telegram.org/bots/api#getme).
[getUpdates](https://core.telegram.org/bots/api#getupdates) now requests both
`message` and `callback_query` updates. Existing offset and callback behavior remains.

`BotQueryRepository` performs read-only status/settings queries. /status lists
all three registered collectors and their persisted last success, next run and status.
Missing state is shown as Never / Not scheduled, without making up timestamps.
`FeedbackRepository.get_saved_jobs_for_user(user_id, limit=10)` selects only
that user's `saved` feedback, newest update first. Saved-job output is split
into messages within Telegram's size limit.
Unknown commands reply: `Unknown command. Use /help to see available commands.`

Admin permission checks compare the verified message sender against
`TELEGRAM_CHAT_ID` and also require an active persisted user. No numeric owner
ID is hardcoded. Without an owner ID, admin commands are disabled.
`CeleryCommandDispatcher` publishes using `asyncio.to_thread`:

```python
for task in COLLECTOR_TASKS.values():
    task.delay()
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
settings - Notification settings
```

## Telegram settings

/settings is available to every registered active user in their private chat.
The menu shows effective timezone, daily digest time, minimum match score, and
Trial/Premium/Free plan. An active trial also shows its end date in the user's
local timezone. Only the owner sees /collect, /digest and /stats in the admin section
of /help; these commands are excluded from the public BotFather menu.

- Timezones: America/Montevideo, America/Sao_Paulo,
  America/Argentina/Buenos_Aires, America/New_York, America/Los_Angeles,
  Europe/London, Europe/Madrid, UTC. Available on every plan.
- Local digest times: 07:00, 08:00, 09:00, 10:00, 12:00, 18:00, 20:00.
- Minimum scores: 50, 60, 70, 75, 80, 85, 90 percent.

Custom time and score require an active Trial or Premium entitlement. Free
menus show locks and the actual FREE_DIGEST_TIME / FREE_MIN_SCORE configuration.
Stored custom values survive expiration and become effective again when Premium
is activated. Entitlements are checked again when a selection is saved.
/settings, /filters and /status use the same effective settings policy.

Navigation edits the existing message. Child Back buttons reopen settings;
the root Back button opens public help. Callback data uses settings:timezone,
settings:time, settings:score, settings:back, settings:close, tz:<IANA name>,
time:<HHMM>, and score:<integer>. All offered values fit Telegram's 64-byte limit.
Every settings callback with a valid query ID is acknowledged, including invalid
selections and denied requests. Existing save/reject callbacks keep their own
handler. Free text is not accepted for settings.

NotificationSettingsService exposes get(user_id), update_timezone(user_id, value),
update_digest_time(user_id, value), and update_min_score(user_id, value).
It validates IANA zones with ZoneInfo, naive time values at minute precision, and
strict integer scores in 0..100. The service commits or rolls back writes;
NotificationSettingsRepository performs user-scoped partial updates without
committing. Existing SQL TIME fields and tables are reused; no migration is needed.

For a development check, open /settings, choose a timezone, set a trial time and
score, and compare /filters and /status. Temporarily expire the trial in the dev
DB to verify locked custom fields and effective Free defaults, then restore the
original subscription and preferences. Do not change production subscriptions.
See [the settings stage report](docs/telegram-settings-report.md) for examples
and validation results.

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


## Pipeline statistics

Use `/stats`, `/stats 24h`, `/stats 7d` or `/stats 30d` in the configured owner's
private chat. The owner must be an active registered user. Other users receive
`This command is not available.` The command reads PostgreSQL and does not
start tasks. `/status` continues to show current scheduling state.

`CollectorRunORM` records each registered collector invocation before acquiring
its Redis lock, then persists counters, finish time, monotonic duration and a
sanitized error type. Terminal statuses are success, failed and skipped;
running is the initial state and also makes hard-killed runs visible. Skipped
locks and stale schedules do not count as failures. Partial job counts survive
an exception after earlier jobs were committed. Received counts include all
collector DTOs, not individual entries discarded internally by existing parsers.
Cross-source duplicates are fingerprint matches whose stored source differs
from the incoming source; source/external-ID matches are ordinary duplicates.

`DigestRunORM` is now defined in `src/models/digest_run.py` and remains importable
from scheduling. The existing table, unique daily reservation, delivery columns
and retry behavior are preserved. ORM aliases selected_count/sent_count/failed_count
refer to the existing selected/sent/failed columns. Additional columns store
candidates, filter rejections, accepted jobs, six score buckets and below-threshold
jobs. Selection still evaluates each job once. Accepted jobs enter score buckets
before threshold and digest-cap selection. Metrics are persisted before the summary;
delivery progress is persisted after each attempt. Failed card attempts include
unexpected processing errors; a summary error is a failed run with zero attempted
cards. Notifications remain the independent record of confirmed delivery outcomes.

Historical rows keep `metrics_recorded=false`. Runs that never finish selection
also remain unmeasured. Their selection counters are excluded from aggregates;
existing delivery counts remain available. When all runs are unmeasured, selection
and score output is N/A. No historical filter results are fabricated.

Public API:

```python
StatisticsRepository(session).get_collector_stats(since, until=None)
StatisticsRepository(session).get_digest_stats(since, until=None)
StatisticsRepository(session).get_feedback_stats(since, until=None)
StatisticsRepository(session).get_notification_stats(since, until=None)
StatisticsRepository(session).get_user_stats()
StatisticsRepository(session).get_data_quality(since, until=None, by_source=False)
StatisticsService(repository, entitlements).get_stats(period="7d") -> BotStats
```

The read-only repository performs SQL aggregation. User totals are SQL counts;
subscription snapshots are classified by the existing EntitlementService with
the same clock. Trial/Premium/Free are mutually exclusive across all users;
active users are counted independently. Telegram receives typed statistics,
not ORM rows. All period queries use `[since, until)` in UTC: collector/digest
started_at, job created_at, notification created_at, and feedback updated_at.
Feedback counts are the latest saved/rejected state updated in the period,
not a history of clicks. Users are a current snapshot. Repeated digest candidates
are counted once per user/run, not as distinct jobs over the whole period.

Rates are fractions in schemas and percentages in Telegram:

- Duplicate rate: duplicates / received; cross-source duplicates are a subset.
- Filter rejection rate: rejected / candidates in measured digests.
- Notification success rate: sent / (sent + failed), excluding pending.
- Save/reject rates: feedback / sent notifications. These compare period totals,
  not matched delivery cohorts; feedback on older cards can make rates exceed 100%.
- New jobs per run: new jobs / (successful + failed runs), excluding skipped/running.
- Zero denominators produce None in schemas and N/A in Telegram.

Data completeness covers jobs inserted during the period, overall and by source:
salary requires at least one positive numeric bound (0–0 is unknown), region
requires nonempty remote_regions, timezone requires nonblank timezone_text or
an explicit numeric offset (zero is valid), and technologies requires a nonempty
technologies array. These measure populated fields, not their accuracy or job
eligibility. Free-form location is not interpreted as remote eligibility.
No rejection-reason event log, analytics service or automatic scheduler tuning
is introduced. See [the implementation and data audit](docs/statistics-stage-report.md).
