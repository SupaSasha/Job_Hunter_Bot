# Job Hunter Bot

Minimal FastAPI project foundation for a Telegram job search bot.

## Local persistence

Install dependencies with `poetry install`. Copy `.env.example` to `.env` on a
fresh checkout, preserving any existing settings. PostgreSQL credentials are
read from `DB_USER`, `DB_PASS`, and `DB_NAME`; the Compose service maps these to
`POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB`.
The example password is for local development only.

```bash
docker compose up -d postgres --wait
docker compose ps
poetry run alembic upgrade head
poetry run alembic current
poetry run python -m src.scripts.collect_remoteok
```

Run the collection command again to verify that known jobs are reported as
`duplicates`. The summary contains `received`, `new`, `duplicates`,
`filter_rejected`, `below_score`, `sent`, and `failed`, plus `notification_skipped`
and `limit_reached`. An empty source response logs a warning because it does not
verify persistence.
If port 5432 is occupied, set `DB_PORT=5433` (or another free port) in `.env`.
The database port inside the container remains 5432. Data lives in the named
`job-hunter-bot_postgres_data` volume. Changing credentials in `.env` does not
change credentials in an already initialized PostgreSQL volume.

The application still runs locally:

```bash
poetry run uvicorn src.main:app --reload
```

`GET /health` returns `{"status": "ok"}` without a database query.

## Persistence contract

The script runs `RemoteOKCollector -> NormalizationService -> JobSaveService ->
PostgreSQL -> FilterService -> ScoringService -> NotificationService -> Telegram`.
Only newly saved jobs reach filtering and scoring. Persistence remains independent
of the owner's filters and score threshold.
`JobDTO` stays independent of the ORM. `job_to_orm` copies DTO fields and converts
aware timestamps to UTC; naive timestamps are rejected.

- `JobRepository(session)` exposes async `get_by_source_external_id(source,
  external_id)`, `get_by_fingerprint(fingerprint)`, and `add(job)`. It flushes
  inserts but never commits. Fingerprint lookup returns the first row by ID.
- `DeduplicationService(repository).check(job)` checks source/external ID first,
  then fingerprint. Its result includes `is_duplicate`, `reason`,
  `existing_job_id`, and the fingerprint when calculated.
- `DeduplicationService.calculate_fingerprint(job)` hashes a UTF-8 JSON pair of
  canonical company and title with SHA-256. Canonicalization lowercases, removes
  dots/commas/apostrophes, converts simple punctuation and underscores to spaces,
  converts `&` to `and`, and collapses whitespace. `+` and `#` remain meaningful.
  Company suffixes and seniority words stay intact. A missing company becomes an
  empty string. Displayed DTO fields are unchanged.
- `JobSaveService(session).save_if_new(job)` returns `JobSaveResult` with
  `status` (`saved` or `duplicate`), `job_id`, and optional `reason`.
  It owns one transaction per call: commit on insert, rollback on a duplicate or
  error. Use a dedicated session without unrelated pending work, and a separate
  session per concurrent task. A conflict on `uq_jobs_source_external_id` is
  rolled back and resolved to the existing row; other integrity errors propagate.

The `jobs` table has a primary key, `UNIQUE(source, external_id)`, and a
non-unique `ix_jobs_fingerprint` index. Fingerprint matching is an MVP heuristic:
identical company/title pairs (especially missing companies) can suppress
separate openings. Concurrent inserts with different source IDs and identical
fingerprints can both succeed; only source identity has a database uniqueness
guarantee. No fuzzy matching or distributed locking is used.

`remote_regions` and `technologies` use PostgreSQL string arrays. All timestamps
use `TIMESTAMP WITH TIME ZONE`. `created_at` and `updated_at` default to database
`now()`; SQLAlchemy updates `updated_at` on updates through the mapped table.
Raw SQL updates must set `updated_at` explicitly. Publication, collection, and
persistence timestamps retain separate meanings. There is no vacancy score.

## Checks

```bash
poetry run ruff check .
poetry run black --check .
poetry run pytest
poetry run alembic check
```

Unit tests use standard-library mocks and do not require PostgreSQL. Migration
application, repeated collection, and a manual concurrent insert exercise the
real database; there is no separate integration database stack at this stage.

## Owner and Telegram notifications

No additional dependencies are required. Configure these optional settings in
`.env` (never commit the bot token):

```dotenv
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
MIN_NOTIFICATION_SCORE=70
MAX_NOTIFICATIONS_PER_RUN=5
```

Blank Telegram settings are treated as unset. Without credentials, the script
prints `Telegram manual test skipped: credentials are not configured` and still
saves new jobs. `MIN_NOTIFICATION_SCORE` must be 0–100; the attempt limit must be
nonnegative (`0` disables sending). For the first real check, limit attempts to one:

```bash
MAX_NOTIFICATIONS_PER_RUN=1 poetry run python -m src.scripts.collect_remoteok
```

The owner is bootstrapped from `TELEGRAM_CHAT_ID` using `OwnerService.get_or_create`.
An existing inactive owner stays inactive and receives no messages. Owner filters
remain a `UserFilterDTO` created in `owner_filters()` in the script: Python is
required, remote work is required, Worldwide/LATAM/South America/Uruguay are
allowed, US-only jobs are excluded, and the timezone is America/Montevideo.

`TelegramClient(token)` is an async context manager that reuses one httpx client.
`send_message(chat_id, text, reply_markup=None)` returns the Telegram message ID;
`aclose()` closes the client. Errors are exposed as sanitized `TelegramAPIError`
exceptions; HTTP request logs redact the bot URL token. No parse mode is used.
`format_job_message(job, score)` produces plain text capped at 4096 UTF-16 units.
`build_job_keyboard(job_id, url)` adds an HTTP(S) URL button and short callbacks
`save:<job_id>` and `reject:<job_id>` (at most 64 bytes). Run the callback polling process below to activate the two feedback buttons.

`NotificationService(session, client).notify(user=..., job_id=..., job=..., score=...)`
returns `NotificationResult(sent, skipped, reason, telegram_message_id)`.
Repositories flush/update only; services own transactions. Use a session without
unrelated pending work. The pipeline bootstraps the owner in a separate session
so per-job rollback does not expire the owner.

The service first checks `(user_id, job_id)`, then inserts and **commits** a
`pending` reservation before HTTP. Only the caller that creates the reservation
sends. Successful sends are marked `sent` with `telegram_message_id` and UTC
`sent_at`; Telegram failures are marked `failed`. Existing `sent`, `pending`, and
`failed` records are skipped with `already_sent`, `already_pending`, and
`previous_failed`, respectively. Only the expected uniqueness conflict is treated
as a duplicate; unrelated database errors propagate.

This MVP prioritizes avoiding repeated sends, not guaranteed delivery. A crash
after reserving but before sending can leave an unsent `pending` row. A timeout
may mean Telegram accepted the message; a failure to save the success also leaves
`pending`. Neither state is automatically retried. The database and Telegram do
not share a transaction, so exactly-once delivery is not guaranteed.

The per-run limit counts failed HTTP attempts as well as successful ones. The
script continues saving the rest of the batch after reaching the limit. Existing
jobs are never backfilled: jobs skipped because credentials were absent, the
limit was reached, or the owner was inactive are not automatically notified on
later runs. No notifications are created for rejected or below-threshold jobs.

Migration `bf2b0ae7bf9d` adds `users` and `notifications`. Users have a unique
BigInteger `telegram_id`; notifications reference users/jobs, store the per-user
score and delivery status, and enforce `UNIQUE(user_id, job_id)`. The status CHECK
allows only `pending`, `sent`, and `failed`. `ix_notifications_job_id` supports
job lookups; the composite unique index also supports user lookups.

Tests use a fake Telegram client and `httpx.MockTransport`, never real Telegram
requests. They cover delivery ordering, duplicate races, failures, pending rows,
message formatting, token redaction, owner bootstrap, and pipeline limits.

## Callback feedback and long polling

Apply migrations and start the separate manual polling process:

```bash
poetry run alembic upgrade head
poetry run python -m src.scripts.telegram_polling
```

The runner uses the existing `TELEGRAM_BOT_TOKEN` and optionally bootstraps the
single owner from `TELEGRAM_CHAT_ID` with `OwnerService`. For the owner-bot MVP,
configure a private chat ID (the same ID as the owner Telegram user), not a group
chat ID. Other users are never registered from callbacks. Unknown/inactive users
receive a short callback answer and no feedback is saved.

Only one polling process should run for a bot. Long polling uses a 30-second
Telegram timeout, with a longer HTTP read timeout. Requests explicitly select
`callback_query` updates. No webhook is configured or deleted by this runner.
An existing webhook or another polling process can cause Telegram API conflicts;
resolve that configuration before running this local poller.

`TelegramClient.get_updates(offset=None, timeout=30)` returns update dictionaries.
`answer_callback_query(callback_query_id, text=None)` acknowledges a button press
without sending a new chat message. Both methods reuse the existing HTTP client
and sanitized error handling.

`parse_callback_data(data)` accepts `save:<job_id>` and `reject:<job_id>` and
returns `CallbackAction(job_id, feedback_type)` or `None` for invalid input.
IDs must be positive integers within the existing PostgreSQL INTEGER range.
The parser rejects malformed data, unknown actions, extra fields and huge IDs.
The handler takes the identity from `callback_query.from.id`, never from callback
data or the message's chat ID. It resolves the user and job through repositories.

`CallbackHandler(users, jobs, feedback, client).handle(callback)` maps `save` to
`saved` and `reject` to `rejected`. It commits feedback before answering with
`Вакансия сохранена` or `Отмечено как не подходящее`. The message and keyboard
remain unchanged. Logs contain events and internal user/job IDs, not raw update
payloads, names, chat contents, or the bot token.

`FeedbackRepository(session)` exposes async `get_by_user_job(user_id, job_id)`,
`add(feedback)` and `update_type(feedback, feedback_type)`. Repository methods do
not commit. `FeedbackService(session).set_feedback(user_id, job_id, feedback_type)`
validates `saved`/`rejected`, creates or updates the row and owns commit/rollback.
A concurrent insert conflict on the user/job pair is recovered by updating the
winning row. Unrelated DB errors propagate. Use a session without unrelated
pending writes and `expire_on_commit=False`, as provided by the session factory.

Migration `664c622669e5` adds `feedback(id, user_id, job_id, feedback_type,
created_at, updated_at)`, timezone-aware timestamps, FK to users/jobs,
`UNIQUE(user_id, job_id)`, a CHECK for the two allowed types and a job ID index.
Repeated presses preserve the same feedback row; changing the action replaces its
current type. The composite unique index supports later queries by user. Feedback
does not modify notification status, job records, or scoring weights.

`poll_updates(client, handle_update, timeout=30, retry_delay=3)` processes updates
sequentially and keeps `offset = update_id + 1` in memory after each handled update.
Ignored non-callback updates also advance the offset. Network errors pause for
3 seconds before retrying. Handler/DB errors leave the failing update unconfirmed;
it is retried before later updates. A failed/expired callback acknowledgement is
logged after handling, so it does not repeatedly overwrite newer feedback.

The next getUpdates request confirms the offset to Telegram. A process restart
can therefore replay a last unconfirmed callback; feedback writes are idempotent.
No persistent cursor or Redis is used. A new DB session is created per callback
and closed before the next long poll. Ctrl+C cancels polling, closes the HTTP
client and disposes the DB engine without a normal-shutdown traceback.

For a manual check, use an already sent job message. Press `Сохранить`, verify the
popup and `saved` row; then press `Не подходит` and verify `rejected` with the same
row ID and a single row for the user/job pair. Unit tests use mocks and never call
Telegram; DB checks can use a fake Telegram client without creating new jobs.
