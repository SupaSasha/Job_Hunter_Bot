# Project guide

Detailed setup, configuration and operational reference. For a quick start, see
[the README](../README.md). Run all commands from the project root.

FastAPI foundation, eight job sources (Remote OK, We Work Remotely, Get on Board,
Himalayas, Jobicy, The Muse, Hacker News and Jooble), and a Telegram daily job digest.
PostgreSQL and Redis run in Docker; Python processes run locally through Poetry.

Project code, comments, documentation and tests use English. The Telegram
interface supports English and Spanish.

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

`Registered collector -> JobDTO -> NormalizationService -> JobSaveService (DeduplicationService) -> PostgreSQL`.
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
poetry run python -m src.scripts.collect_himalayas
poetry run python -m src.scripts.collect_jobicy
poetry run python -m src.scripts.collect_the_muse
poetry run python -m src.scripts.collect_hacker_news
poetry run python -m src.scripts.collect_jooble
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
| himalayas | 06:00–07:00, 14:00–15:00, 22:00–23:00 | jobs.collect_himalayas | collector:himalayas:lock |
| jobicy | 03:00–04:00, 11:00–12:00, 19:00–20:00 | jobs.collect_jobicy | collector:jobicy:lock |
| the_muse | 07:00–08:00, 19:00–20:00 | jobs.collect_the_muse | collector:the_muse:lock |
| hacker_news | 13:00–14:00 | jobs.collect_hacker_news | collector:hacker_news:lock |
| jooble | 09:00–10:00, 21:00–22:00 | jobs.collect_jooble | collector:jooble:lock |

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
company/title fingerprint deduplication within a 30-day collected-at window.
Missing companies never deduplicate by title alone. Source/external ID identity
has no age limit. Fingerprint matching is a heuristic;
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

Only explicit skill/category tags populate the legacy `technologies` field; no
description NLP is used. The source taxonomy is mostly technical, so tags can be
sparse for nontechnical listings; this does not filter those jobs. Explicit country lists take
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

See [the WWR stage report](weworkremotely-stage-report.md) for live counts,
deduplication examples, test results and Git state.

## Get on Board

Get on Board provides an [official public API without authentication](https://www.getonbrd.com/user-manual/get-on-board-s-api).
The collector reads the documented public search endpoint
`https://www.getonbrd.com/api/v0/search/jobs?remote=true`, without a keyword,
country or category restriction. The [OpenAPI reference](https://www.getonbrd.com/api-doc.html)
documents remote search, pagination and expanded relationships.

GetOnBoardCollector(timeout=20, max_pages=2, per_page=50).collect() returns
list[JobDTO]. parse_job(raw, collected_at=...) and parse_page(payload) separate
mapping from HTTP. The default scope is the first two remote search pages, at most
100 records before repeated-ID deduplication. This does not guarantee every
recent job: the API has no documented chronological ordering/cursor contract. No date cutoff is assumed. Configuration
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
daily digest; collection sends no messages. /collect publishes eight independent
tasks, /status displays all eight states, and job cards use the shared source
name helper to display Get on Board. See [the stage report](getonboard-stage-report.md)
for real collection counts, LATAM observations and verification results.

## Himalayas

The official JSON feed uses bounded cursor pagination: up to 20 jobs per page,
`HIMALAYAS_MAX_PAGES=3` by default (maximum 5). An optional `HIMALAYAS_API_KEY`
uses an Authorization header for higher limits; anonymous collection also works.
The source refreshes on a daily cache, so scheduled checks may return duplicates.
Himalayas attribution and the source application URL are kept in job cards.

Migration `a814d5c0732e` adds Himalayas to each saved source selection without
re-enabling previously disabled sources. New profiles use the active policy
registry. See [the implementation and data audit](himalayas-stage-report.md)
for API/schema observations, timezone limitations, live counts and examples.

## Jobicy

The [official public API](https://jobicy.com/jobs-rss-feed) needs no API key.
Collection uses up to two cursor pages of 50 jobs (`JOBICY_MAX_PAGES=2`, maximum
5 pages). The feed covers the last seven days with a three-hour publication
delay. Automated syncs must be at least one hour apart; a persisted guard also
applies to manual collection and respects longer Retry-After delays.

Explicit locations, employment, seniority and numeric salary fields are retained.
Industry categories are not technologies. The current API supplies no structured
skills or timezone requirements, so those fields remain unknown.

Migration `b927c64ed108` appends Jobicy to saved source selections without
re-enabling disabled older sources or resetting other preferences. New profiles
include all active sources. See the [implementation and live audit](jobicy-stage-report.md).

## The Muse

The [official API](https://www.themuse.com/developers/api/v2) permits anonymous
testing. Register an app and set `THE_MUSE_API_KEY` for ongoing use; the provider
requires registration beyond testing. With MODE=PROD, a missing key fails before
any network request. The key uses the documented `api_key`
query parameter, which is redacted in HTTP logs. Server `.env` is never replaced
by deployment; configure the key there securely before production use.

Collection queries the broad `Flexible / Remote` location across all categories,
up to three pages of 20 jobs (`THE_MUSE_MAX_PAGES=3`, maximum 5). The API ranks
results by multiple factors; `descending=true` does not guarantee newest-first
publication order. Only the explicit source location marker sets remote=True.
Cities do not establish eligibility regions or timezones. The current bool DTO
represents both non-remote and unknown as False. Structured salary, employment,
technical skills and timezone fields are unavailable in the observed response.

Migration `c638e7a2910f` appends The Muse to saved source selections and updates
defaults while preserving other preferences. See the [implementation and live
audit](the-muse-stage-report.md) for data completeness and remote limitations.

## Hacker News — Who is hiring?

The [public Algolia HN API](https://hn.algolia.com/api) needs no key. Collection
discovers the exact current UTC month title from whoishiring, falling back only
to the previous month. One item request supplies the chosen thread's direct
children. Embedded replies are ignored, with no recursive network requests.
There is no global HN crawl or hardcoded story ID.

Each accepted comment produces one job. The deterministic parser uses clear
company/header/role markers and the existing technology vocabulary, HTML helper,
normalizer and timezone parser. Multiple roles remain one entry; unknown fields
stay unknown. Bare Remote does not imply worldwide. The bool DTO represents
both non-remote and unknown as False. Dollar symbols alone do not establish USD,
and salary periods are retained only when explicit.

Migration `d749a8b3e205` adds Hacker News to saved source selections/defaults,
preserving other preferences and disabled older sources. The schedule is once
daily, with existing jitter. See the [implementation and live audit](hacker-news-stage-report.md)
for parser limitations, completeness and actual collection results.

## Jooble

The [official REST API](https://help.jooble.org/en/support/solutions/articles/60001448238-rest-api-documentation)
uses POST with a key in the URL path. Configure `JOOBLE_API_KEY`,
`JOOBLE_API_DOMAIN` and `JOOBLE_SEARCH_LOCATION` explicitly. A key from jooble.org
covers the US only; uk.jooble.org and other markets require their own keys.
The selected initial market is the US: local configuration and `.env.example`
use `JOOBLE_API_DOMAIN=jooble.org` and `JOOBLE_SEARCH_LOCATION=United States`.
Settings require explicit configuration; there is no multi-market key manager.

The collector rotates through engineering, design, product, sales, marketing,
customer support, finance, operations, human resources and data. Redis INCR
persists a market-specific rotation index under the existing collector lock.
Manual /collect and scheduled tasks use the same policy. The current request
ceiling is preserved: `JOOBLE_MAX_PAGES_PER_QUERY` (1–3) also bounds the total
requests per cycle. With the default of 1, each cycle queries the next profession;
with a budget of 2 or 3, up to two professions share the same total request cap.
The third request, if allowed and needed, paginates the first profession. No
unstarted query consumes a rotation slot when the job cap is reached. Set
`JOOBLE_MAX_JOBS_PER_RUN` (1–200) to bound returned jobs. Repeated IDs are removed before persistence. Free API access has a
**500-request lifetime quota per key**; scheduled defaults consume at most two
requests/day, excluding manual runs and error retries. Provider-specific
additional limits must be confirmed for the key. The selected market and location
still limit coverage; API behavior for a broad keyword may vary by market.

The API has no documented remote filter or structured skills/timezone/seniority
fields. Only exact obvious remote location labels set remote=True. Cities and
countries do not establish eligibility regions. Salary strings use the shared
conservative parser without currency/period guesses; naive update timestamps
remain unknown rather than using server/market timezone. Missing configuration
fails before HTTP with CollectorConfigurationError and does not block other sources.

Migration `e85ab9c12460` adds Jooble to source selections/defaults without resetting
other preferences or re-enabling disabled older sources. See the
[implementation and validation report](jooble-stage-report.md) for authentication,
market requirements, US live collection results and test coverage.

## USAJOBS

USAJOBS is an optional U.S. federal source, disabled in user filters by default.
Enable it manually through `/filters` → Sources. Existing selections and new-user
defaults retain the eight previous sources. Reset returns USAJOBS to off.
Available sources and default selections are separate; no schema/default change
or Alembic migration is required.

Request a key at the [official portal](https://developer.usajobs.gov/apirequest/),
then set `USAJOBS_API_KEY` and `USAJOBS_EMAIL` (the email used for registration).
Search uses `GET https://data.usajobs.gov/api/Search` with Host, User-Agent (email)
and Authorization-Key headers. Missing credentials fail before HTTP and show
configuration required in `/status`. Key/email values and bodies are not logged.

The search omits JobCategoryCode and uses RemoteIndicator=True, DatePosted=30,
newest opening dates first and Fields=Full, so it is not limited to the IT series.
Results remain restricted to U.S. federal jobs and remote eligibility. Defaults fetch at most two pages of
50 results and return at most 100 unique control numbers per run. Configure
`USAJOBS_MAX_PAGES_PER_QUERY` (1–5) and `USAJOBS_MAX_JOBS_PER_RUN` (1–500).
Pagination is bounded and stops on short/exhausted/repeated pages. API requests
are spaced one second apart; 429 honors shared Retry-After handling.

Telework eligibility alone never means fully remote. An explicit remote flag or
the official location label Anywhere in the U.S. (remote job) confirms remote;
that location label also establishes a U.S. restriction. Exact unconditional
citizenship requirements can set us_only. Agency location, public hiring paths
and security clearances do not automatically establish eligibility. Other
requirements remain in the bounded description. Existing exclusion/region
filters still apply if a user opts in. No source scoring or digest rule is added.

Salary retains structured USD amounts and PA/PH periods without conversion.
Unknown periods stay unknown; fractional amounts cannot fit the existing integer
DTO and are not rounded. Schedule codes 1/2 map to full_time/part_time. Federal
grades, appointment tenure and multiple schedules do not invent seniority or
contract employment. Structured technologies/timezone restrictions stay unknown.
Offset-aware publication dates become UTC; undocumented naive publication
timestamps remain unknown. Calendar closing dates expire after the full closing
day in America/New_York, including DST; aware closing instants retain their offset.

The shared scheduler selects one run in 15:00–16:00 America/Montevideo each day.
Task `jobs.collect_usajobs` uses `collector:usajobs:lock`, CollectionService,
normalization, PostgreSQL dedup and existing run/state statistics. Owner `/collect`
dispatches it with the other eight collectors. Manual collection:

```bash
poetry run python -m src.scripts.collect_usajobs
```

See the [implementation and validation report](usajobs-stage-report.md) for
source contracts, limitations, fixtures, live-run availability and checks.

## Daily delivery

Beat tasks:

| Task | Interval / trigger |
| --- | --- |
| scheduler.dispatch_collectors | 15 minutes |
| scheduler.dispatch_digests | 5 minutes |
| jobs.collect_remoteok | Due Remote OK collector or manual task |
| jobs.collect_weworkremotely | Due WWR collector or manual task |
| jobs.collect_getonboard | Due Get on Board collector or manual task |
| jobs.collect_himalayas | Due Himalayas collector or manual task |
| jobs.collect_jobicy | Due Jobicy collector or manual task, subject to the hourly sync guard |
| jobs.collect_the_muse | Due The Muse collector or manual task |
| jobs.collect_hacker_news | Due Hacker News collector or manual task |
| jobs.collect_jooble | Due configured Jooble collector or manual task |
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

Candidates fall within `DIGEST_JOB_MAX_AGE_DAYS` (default 7) by `collected_at`,
exclude future timestamps, and have either no notification or a `retryable`
notification whose cooldown has elapsed. SQL selects at most
`DIGEST_CANDIDATE_LIMIT` (default 1000), newest first with job ID as a tie-breaker.
Jobs omitted by a previous limit remain eligible only within this age window.
Every candidate passes the existing `FilterService` and `ScoringService`; all
score signals are relative to the recipient's filters and notification timezone.
Profession, source, named skill and region have no global weights. Results sort
by score descending, then job ID for ties; effective threshold and maximum count
determine the selection. Each digest loads that user's persisted `UserFilterDTO`
through `UserFilterService.get_filters(user_id)`. Missing rows are bootstrapped
once; existing filters are never replaced by a shared profile. No owner-specific
profile is applied to a missing row.

Before any Telegram request, the service commits a `digest_runs` reservation
with a partial **UNIQUE(user_id, local_date) WHERE status <> 'abandoned' AND NOT manual**
index for scheduled runs. Scheduled tasks cannot reserve the same date while a
non-abandoned scheduled run exists. Manual requests have separate history and
can run repeatedly after a previous run finishes. Reservations lock the user
row to prevent overlapping scheduled/manual runs; a partial unique index also
prevents simultaneous pending manual runs. Empty scheduled selection records
`empty` and sends no message; empty manual selection sends a localized reply.
A nonempty run sends a short summary (up to five top titles), then existing job
cards with feedback buttons, through `NotificationService`. Progress and summary
message ID are recorded. Final status is `sent`, `partial` or `failed`.
An interrupted `pending` run becomes `abandoned` after
`DIGEST_PENDING_TIMEOUT_MINUTES` (default 30, minimum 11). Recovery preserves
the old row and permits a new reservation; completed scheduled attempts still
block automatic delivery on that date. Digest service execution is bounded to
600 seconds. Dates follow the
user's timezone, including DST and UTC date rollover.

The existing **UNIQUE(user_id, job_id)** notification reservation is committed
before each individual message. Connection failures before sending and explicit
Telegram rejections, including 429, become `retryable`. Telegram `retry_after`
is stored as `retry_after_until`; an atomic claim allows only one concurrent
retry. Read/write timeouts and other ambiguous outcomes become `unknown`.
Existing `sent`, `unknown`, `pending` and legacy `failed` records are never sent
automatically again. Historical `failed` rows retain their original status
because their delivery certainty cannot be reconstructed.

A database failure after sending leaves the committed `pending` reservation.
This MVP prioritizes avoiding duplicate cards over guaranteed delivery in that
case. A failed summary can leave today's digest incomplete; unattempted jobs
and retryable cards remain candidates for a later eligible digest within the
age window. There is no immediate retry queue or automatic retry of completed
digest runs. Recovering a stale digest does not clear ambiguous notification
reservations; summaries can repeat after recovery.

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
including the existing owner. Missing rows are discovered with two SELECTs;
initialized users cause no repeated INSERT or commit. Defaults use
`SCHEDULER_TIMEZONE`, 09:00, score 70, 10 jobs and a seven-day trial. Bulk inserts
use ON CONFLICT DO NOTHING and never reset stored preferences or renew an
expired trial. Existing users retain their separately stored notification timezone.

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

Commands are handled in private chats. `/start` creates a minimal user profile
and offers a language picker for new users. `/help` does not register accounts.
Registration reuses owner/user bootstrap and missing-only delivery defaults,
without overwriting settings or renewing an existing trial. Startup still reuses
`OwnerService.get_or_create` for the configured owner.
Data commands require an existing active user. Groups and mismatched sender/chat
IDs receive `This command is not available.` without exposing account data.

| Command | Behavior |
| --- | --- |
| /start | New users: choose a language; existing users: show a localized introduction |
| /help | List public commands; show a separate admin section to the owner |
| /status | Read collector state, total jobs, effective digest settings and the user's latest digest attempt from PostgreSQL |
| /saved | Show up to ten most recently saved jobs, without descriptions |
| /filters | Configure persisted job search filters with inline menus and text input |
| /cancel | Cancel pending filter input |
| /settings | Choose English/Español; view notification settings and edit timezone, digest time and score |
| /collect | Owner only: enqueue all eight registered job collectors |
| /digest | Owner only: check today's state and queue an eligible digest |
| /stats [24h\|7d\|30d] | Owner only: read historical pipeline statistics; default 7d |

`CommandHandler(...).handle(message)` in `src/bot/commands.py` handles commands.
It receives repositories, TelegramClient, a dispatcher, EntitlementService,
the configured owner Telegram ID, the bot username and an injectable clock.
`route_update(update, commands=..., callbacks=..., settings=..., filters=...)`
keeps commands, notification settings, job filters and feedback separate. Plain
text is handled only when that user has pending filter input; edited messages
are ignored. Slash commands always take precedence over pending input. Commands support a matching `@BotUsername` suffix and ignore commands
addressed to other bots. The username is obtained once at startup using
[getMe](https://core.telegram.org/bots/api#getme).
[getUpdates](https://core.telegram.org/bots/api#getupdates) now requests both
`message` and `callback_query` updates. Both use the persistent polling checkpoint.

`BotQueryRepository` performs read-only status/settings queries. /status lists
all eight registered collectors and their persisted last success, next run and status.
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
publication replies `Collection started.` or `Digest queued.`; publication
errors produce `Failed to start collection.` or `Failed to start digest.`.
These acknowledgements do not imply the worker has completed the job.
Replies use plain text. Logs record command categories and sanitized error types,
not raw command arguments or Telegram secrets. A reply timeout is logged without
replaying a task that may already have been queued.

Manual `run_now=True` bypasses the local scheduled-time check and the automatic
one-attempt-per-day limit. It preserves active/enabled-user checks, effective
filters and threshold, and individual notification reservations. `/digest`
always queues a manual request after authorization. Completed, empty, failed
or partial runs do not block another manual request that day. The worker sends
only new eligible jobs; existing sent/ambiguous notifications remain excluded.
If none match, it replies `No new jobs match your filters.` in the saved
language. During an active reservation, it replies `Digest is already in
progress.` and sends no duplicate cards. Stale pending runs remain recoverable.
Manual runs do not consume the automatic day's attempt. `/status` shows the
latest attempt. Migration `f72c4ea83910` adds the manual-run flag and updates
reservation indexes, preserving existing run history. See
[the manual digest report](manual-digest-report.md).

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
filters - Job search filters
settings - Notification settings
cancel - Cancel current input
```

## Telegram settings

/settings is available to every registered active user in their private chat.
The menu shows saved interface language, effective timezone, daily digest time, minimum match score, and
Trial/Premium/Free plan. An active trial also shows its end date in the user's
local timezone. Only the owner sees /collect, /digest and /stats in the admin section
of /help; these commands are excluded from the public BotFather menu.

- Timezones: global presets across the Americas, Europe, Asia, Africa and Oceania,
  plus UTC and Other / Custom timezone. Custom IANA input is validated by ZoneInfo,
  for example Europe/Berlin, Asia/Tokyo or America/Mexico_City. Available on every plan.
  Telegram language/location is never used to infer timezone; the application
  timezone is a temporary fallback until a user changes it.
- Local digest times: 07:00, 08:00, 09:00, 10:00, 12:00, 18:00, 20:00.
- Minimum scores: 50, 60, 70, 75, 80, 85, 90 percent.

Custom time and score require an active Trial or Premium entitlement. Free
menus show locks and the actual FREE_DIGEST_TIME / FREE_MIN_SCORE configuration.
Stored custom values survive expiration and become effective again when Premium
is activated. Entitlements are checked again when a selection is saved.
/settings and /status use the same effective notification settings policy.
/filters manages job search preferences independently and is available on every plan.

Navigation edits the existing message. Child Back buttons reopen settings;
the root Back button opens public help. Callback data uses settings:timezone,
settings:time, settings:score, settings:back, settings:close, tz:<IANA name>,
time:<HHMM>, and score:<integer>. All offered values fit Telegram's 64-byte limit.
Every settings callback with a valid query ID is acknowledged, including invalid
selections and denied requests. Existing save/reject callbacks keep their own
handler. Custom timezone text uses the shared expiring pending-input store;
/cancel or navigating away clears it. Invalid input keeps the prompt for retry.

NotificationSettingsService exposes get(user_id), update_timezone(user_id, value),
update_digest_time(user_id, value), and update_min_score(user_id, value).
It validates IANA zones with ZoneInfo, naive time values at minute precision, and
strict integer scores in 0..100. The service commits or rolls back writes;
NotificationSettingsRepository performs user-scoped partial updates without
committing. Existing SQL TIME fields and tables are reused; no migration is needed.

For a development check, open /settings, choose a timezone, set a trial time and
score, and compare /settings and /status. Temporarily expire the trial in the dev
DB to verify locked custom fields and effective Free defaults, then restore the
original subscription and preferences. Do not change production subscriptions.
See [the settings stage report](telegram-settings-report.md) for examples
and validation results.

## Telegram interface language

English (`en`) and Español (`es`) are persisted in `users.language`, with
English as the default for existing users. Migration `e93b6472a105` adds the
NOT NULL field, a constant English server default and an allowed-language
constraint; it follows `c41a9e327b60`. Apply Alembic before running the updated
application. The initialized production update command remains
`./scripts/deploy.sh`; it excludes `.env` and keeps database/Redis volumes.
This language stage does not automatically deploy, commit or push.

New /start users receive a bilingual language picker. Telegram language_code
starting with `es` initializes Spanish only on creation; every other code
initializes English. Existing profiles always use the saved choice, even when
Telegram's locale differs. /settings → Language/Idioma offers both languages
for Free, Trial and Premium. Selecting one persists it, acknowledges the
callback, and immediately redraws settings in that language. Commands and
callback data remain unchanged, including `settings:language:en` and
`settings:language:es`. The original owner-only /digest, /collect and /stats
permissions remain in force.

`src/i18n` contains a Language enum, English/Spanish dictionaries, the public
`t(key, language, **params)` translator, display label helpers and a presentation
adapter for existing scoring explanations. The catalogs contain 235 keys each;
tests enforce key and interpolation-parameter parity. Missing Spanish keys fall
back to English. Missing English keys raise TranslationError rather than being
shown to users. No external translation service or new dependency is used.

Commands, filters, notification settings, pending input prompts/errors,
subscription labels, status, saved jobs, digest summaries, job card labels and
feedback buttons/replies use the saved locale. Technical /stats output may
remain English for the owner; its command replies/errors are localized.
Vacancy titles, companies, descriptions, currencies, technologies, URLs,
source brands and canonical filter values are not translated. Language changes
neither selection nor scoring, scheduling, salary rules, trials or reservations.
An empty manual digest reports no new matching jobs in the user's language;
empty scheduled digests keep their existing no-message behavior.

BotFather descriptions are configured manually, with unchanged command names.
The following requested menus include /digest; keep that entry owner-scoped or
omit it from the global public menu because /digest remains owner-only.

English:

```text
start - About the bot
help - Show available commands
status - Bot status
saved - Saved jobs
filters - Job search filters
settings - Settings
digest - Get a job digest now
cancel - Cancel current input
```

Español:

```text
start - Información del bot
help - Ver comandos disponibles
status - Estado del bot
saved - Vacantes guardadas
filters - Filtros de búsqueda
settings - Configuración
digest - Obtener vacantes ahora
cancel - Cancelar la entrada actual
```

See [the interface language report](telegram-language-report.md) for both
languages' UI examples, persistence/restart checks and full validation. The
[original string inventory](telegram-string-inventory.md) was captured
before implementation.

## Persisted job filters

`user_filters` stores one row per user with `UNIQUE(user_id)`, a foreign key to
`users.id`, PostgreSQL string arrays, nullable minimum salary/currency, remote
and US-only flags, and timezone tolerance. Notification timezone remains in
`user_notification_settings`; the DTO mapper reads it on every request and
uses `allowed_regions` as the only region preference. Legacy DTO region flags
have been removed; they were never stored as ORM columns. Scoring remains recipient-relative; the
scheduler timezone default is operational context, not a global bonus.

New users get empty skill/keyword/blacklist/employment/experience lists,
region preference [worldwide] (an existing empty list still means any region),
the eight default sources (USAJOBS
is opt-in), Remote only enabled, Exclude US-only disabled, tolerance ±2h, and no salary/currency restriction. No
owner-specific profession or region profile is bootstrapped. This lazy bootstrap
runs only for missing rows; reset deliberately restores neutral defaults. Existing user
bootstrap/onboarding is unchanged: first /filters or digest creates filters for
an active persisted user. /start now creates a minimal profile with the selected
initial language and missing-only notification/trial defaults.

`UserFilterRepository` exposes `get_by_user_id` and `add`, flushing without
committing. `UserFilterService` owns validation, bootstrap, mapping and
commit/rollback. It locks the parent user for bootstrap and read-modify-write
operations to prevent duplicate creation and lost concurrent list changes.
Services must use sessions without unrelated pending writes.

/filters opens Keywords, Required/Preferred/Excluded skills, Regions, Employment,
Experience, Salary, Sources, Blacklist, Timezone tolerance and confirmed Reset.
Callbacks use only `filters:`. Navigation and updates edit the existing message.
Lists support Add/Remove/Clear with comma-separated input, lowercase storage,
ordered deduplication and shared technology aliases. Adding exclusions removes
matching required/preferred technologies; adding an excluded technology back
to required/preferred requires first removing its exclusion. Keywords match
any supplied word; required technologies must all match. Blacklisted companies
use exact case-insensitive comparison. Lists accept at most 50 entries of
100 characters each.

Region options include Worldwide, Americas, North America, Latin America,
South America, Europe, EU, EMEA, APAC, Asia, Africa and Oceania, with Remote only
and Exclude US-only toggles. Specific countries opens an Add/Remove/Clear editor;
country names and ISO codes such as `Uruguay, Spain, Canada` or `UY, ES, CA` are
validated against bundled ISO data. Countries share the existing allowed_regions
array. Region matching uses CLDR membership; Uruguay has no privileged rule. No selected region means there is no region restriction; worldwide jobs
are compatible with any selected region. Empty employment/experience selections
mean Any.
Salary accepts only a nonnegative whole number within PostgreSQL INTEGER range;
USD/EUR/GBP/CAD/AUD/BRL/MXN/UYU presets, Other (any three-letter ASCII code),
and Any currency are available, without conversion. Clear removes
the amount and keeps the selected currency. Unknown salary/region/employment/
experience metadata retains the existing filter behavior. At least one of
the nine available sources must remain enabled. USAJOBS starts disabled. Tolerance
ranges from ±0h to ±4h; timezone itself stays in /settings. All job filters are
available on Free/Trial/Premium; custom digest time and score retain their
existing entitlement rules.

Pending input is a small JSON Redis record under
`telegram:user:<telegram_id>:pending_input`, with action, operation and the
menu message ID, expiring after 600 seconds. It covers keywords, three tech
lists, minimum salary, blacklisted words and blacklisted companies. /cancel,
opening /filters, or navigating a filter menu clears it. Invalid input leaves
it active until corrected or expired. Commands take priority and are never
stored as filter input. No FSM framework or new dependencies are introduced.

Migration `c41a9e327b60` adds only `user_filters`, with no data migration or
changes to existing tables. Upgrade before running the updated application:

```bash
poetry run alembic upgrade head
```

For the initialized VPS deployment, run the existing script from the local
project directory after reviewing the change:

```bash
./scripts/deploy.sh
```

It builds the production image, stops application writers, upgrades Alembic
using the `api` service, and restarts services. It excludes `.env` and preserves
PostgreSQL/Redis/Beat volumes. This filter stage does not automatically deploy,
commit, push, or contact real Telegram. See the
[persistent filters report](user-filters-report.md) for APIs, callbacks,
test evidence and the saved example profile.

## Feedback

Job cards keep `Save` and `Not suitable` buttons, handled by the independent
polling process. Callback data is `save:<job_id>` or `reject:<job_id>`.
The handler checks the Telegram sender against an active persisted user, stores
`saved`/`rejected` feedback and answers the callback. Unknown users are not
registered automatically. Repeated presses update one unique user/job row.
Feedback does not modify notification status or scoring weights.

Polling loads `telegram:polling:offset` from Redis at startup and saves the next
offset with its handling timestamp in one atomic JSON write after processing.
Checkpoints expire after five days without a handled update, both after restart
and in a running poller. Expiry is checked before getUpdates so a stale high
offset cannot acknowledge newly randomized, lower update IDs after a week of
inactivity. Five days allows for Telegram's 24-hour update retention plus a
margin before that reset. Empty polls and Redis write retries do not refresh
the handling timestamp. Expired checkpoints request unconfirmed updates without
an offset; live checkpoints still prevent replay of confirmed commands.

Legacy integer checkpoints are migrated once without changing their confirmed
offset. Their original age is unknown, so the expiry clock starts on migration;
a legacy checkpoint that was already stale cannot be detected retrospectively.
The migration logs this limitation. Do not run the previous polling version
against the new JSON checkpoint format.

Three consecutive handler failures skip
a logged poison update, allowing later updates to proceed. Redis load/save
failures pause polling and retry; a save failure does not rerun the handled
command in the same process. Confirmed `/collect`, `/digest` and callback
updates are not replayed after restart. A crash between an external side effect
and checkpoint persistence can still replay an unconfirmed command: Redis and
Telegram/Celery do not share a transaction. Redis persistence must be enabled
and its checkpoint retained across restarts.

Polling uses a fresh database session per callback and a 30-second long-poll
timeout. Network errors retry after three seconds (or Telegram's longer
`retry_after`). Do not run multiple pollers for the same token or combine
polling with an active webhook.

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
PostgreSQL integration tests run separately with `TEST_DATABASE_URL` pointing
to a dedicated database using the `postgresql+asyncpg://` scheme:

```bash
poetry run pytest tests/integration
```

The fixture creates a unique schema, runs actual Alembic migrations, and drops
only that schema on completion. Without the variable these tests are skipped.
Automated GitHub Actions CI is intentionally disabled. Tests and lint checks
are run locally. Live broker/worker and Telegram delivery remain separate
manual checks.

Review fixes and migration `49f75b591334` are described in
[the hardening report](hardening-review-report.md). Run `poetry run alembic upgrade head` before starting the updated services. No historical data rewrite
or automatic retention cleanup is performed.


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
- Notification success rate: sent / (sent + failed + retryable), excluding
  pending and unknown. Status counts describe the current state of each unique
  user/job row, not the number of HTTP attempts. Legacy failed rows may include
  ambiguous historical outcomes.
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
is introduced. See [the implementation and data audit](statistics-stage-report.md).

## MVP boundaries and retention

This is an owner-oriented MVP. Interface language, delivery preferences, job
filters and notification history are persisted per user. `/start` provides
minimal registration and language selection; collector control, manual digests
and technical statistics remain owner-only.

Remote OK reads at most 8 MiB of response data, treats naive dates as UTC, and
reports parsed Retry-After cooldowns without an immediate retry loop. Technology
aliases are shared across normalization/filtering/scoring; C, C++ and C# remain
distinct. Experience scoring strips HTML and decodes entities before matching
explicit experience requirements, including possessive years' / years’ and
hands-on wording. Company/product age still does not count as work experience.
User timezone offsets include fractional hours and current-date DST.

No data is deleted automatically. See the hardening report for proposed jobs
and collector-run retention, and criteria for introducing per-user evaluation
caching. Linux deployments and Ubuntu CI use system timezone data; add `tzdata`
when adopting Windows or a slim runtime image without that system database.

## VPS deployment

The development compose file remains unchanged. Production uses
`docker-compose.production.yml` and a Python 3.12 slim application image shared
by FastAPI, the Celery worker, Beat and Telegram polling. Application processes
run as UID 10001; dependencies are installed from the lockfile without the dev
group. The image never includes `.env`. System timezone data is installed.

The deployment directory is `/opt/job_hunter_bot`. Initialize `.env` securely
once and set its permissions to 600; never replace an existing server file during
an update. Configure database credentials, the Telegram token and owner chat ID.
Production Compose supplies `MODE=PROD`, `DB_HOST=postgres`, `DB_PORT=5432`,
`REDIS_HOST=redis`, and `REDIS_PORT=6379`, overriding local host/port values.
Scheduler and digest settings use the existing defaults unless set in `.env`.

All six services use `restart: unless-stopped`, and Docker must be enabled at
boot. PostgreSQL 16, Redis 7 AOF and Beat's schedule use separate named volumes.
PostgreSQL/Redis have healthchecks; application services wait for both. The API
has an HTTP healthcheck and the worker uses an addressed Celery ping. The API
is internal only, and this Compose file publishes no host ports. SSH is the
only public endpoint needed for this deployment. Docker log rotation is capped
at three 10 MiB files per service.

First deployment, after transferring source files without `.env` or development
caches and initializing the environment separately:

```bash
cd /opt/job_hunter_bot
docker compose -f docker-compose.production.yml config --quiet
docker compose -f docker-compose.production.yml build api
docker compose -f docker-compose.production.yml up -d --wait postgres redis
docker compose -f docker-compose.production.yml run --rm --no-deps api poetry run alembic upgrade head
docker compose -f docker-compose.production.yml run --rm --no-deps api poetry run alembic current
docker compose -f docker-compose.production.yml up -d --wait --wait-timeout 180
docker compose -f docker-compose.production.yml ps
```

Future updates from the local checkout:

```bash
./scripts/deploy.sh
# Optional overrides:
DEPLOY_TARGET=root@179.236.245.161 DEPLOY_PATH=/opt/job_hunter_bot ./scripts/deploy.sh
```

The script checks that server `.env` exists, transfers source via SSH/rsync,
builds the image, keeps PostgreSQL/Redis up, stops application writers before
applying existing migrations, and starts the services. It never copies `.env`,
uses rsync without deletion, and never removes volumes or downgrades the database.
If a migration fails, application services remain stopped for inspection; their
data remains intact. Removed source files are not automatically deleted on the
server and require a deliberate cleanup if a later version removes modules.

Run only one Beat instance and one poller for the token. Stop local bot processes
before activating the VPS. Do not use `docker compose down -v`. Back up PostgreSQL
and the server `.env` securely before future schema/deployment changes.

See [the universal matching report](universal-matching-report.md) for the collector
audit, request budgets, compatibility details, five-profile validation and checks.
