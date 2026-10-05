# Repeatable manual digests

## Problem and resulting behavior

The Telegram Send digest now command (`/digest`) previously checked today's
latest run before publishing work, and the worker used the same daily
reservation as the scheduled digest. A completed, empty, partial or failed
attempt therefore blocked a new manual request, including newly collected jobs.

Manual requests now queue after the existing owner/private-chat authorization.
The worker records a separate manual run and selects new eligible vacancies
using the saved filters, score threshold, age window and maximum job count.
Previously sent or ambiguous notifications remain excluded. This matches the
requested policy: new matching jobs only; explicitly report when none remain.

- A previous completed, empty, partial or failed run never blocks another
  manual request that day.
- During an active run, another manual request receives a localized
  `Digest is already in progress.` response without duplicate job cards.
- An empty manual request receives `No new jobs match your filters.` or
  `No hay nuevas vacantes que coincidan con tus filtros.`.
- A scheduled digest still has one non-abandoned attempt per user/local day.
  Manual runs do not consume that attempt.
- Existing active/enabled-user checks, owner-only command access, premium
  settings, scoring, filtering and notification uniqueness remain unchanged.
- Automatic empty runs still send no Telegram message. Stale pending
  reservations remain recoverable with their history retained.

## Implementation and migration

`src/bot/commands.py` publishes manual work without rejecting previous attempts.
`DailyDigestService` passes `manual=run_now` to the repository, sends localized
empty/in-progress replies for manual requests and keeps scheduled behavior.

Revision `f72c4ea83910` follows `e93b6472a105`. It adds
`digest_runs.manual BOOLEAN NOT NULL DEFAULT false`, preserving all old rows,
statuses, selection metrics and delivery counts as scheduled history. The
scheduled unique index applies to `status <> 'abandoned' AND NOT manual`.
A separate partial unique index prevents multiple pending manual runs for
one user. Repository reservation also locks the parent user row, checks all
pending runs and commits before any Telegram request, serializing manual and
scheduled starts. Scheduler eligibility ignores manual history.

The migration does not remove run or notification rows, reset delivery states
or clear existing daily attempts. Downgrade refuses to discard manual history
without explicit operator review.

## Validation

Tests cover command publication after every run status, localized empty replies,
overlapping manual requests, the scheduled daily limit and real PostgreSQL
reservation races. End-to-end PostgreSQL coverage starts with a failed daily
run and an already-sent vacancy, delivers a fresh vacancy once, reports no new
matches, then delivers a newly inserted vacancy on another manual request.
Migration tests verify existing history and Alembic/ORM metadata parity.

Final full suite: **925 passed**, including **39 PostgreSQL integration cases**.
Ruff, Black and `git diff --check` passed. PostgreSQL cases use disposable
schemas in the dedicated `job_hunter_review_test` database. Telegram tests use
fake clients; no synthetic vacancies were inserted into production.

## Deployment

The language implementation was committed and deployed first as `85d0942`.
Production inspection then confirmed the language revision, enabled digest
delivery, score threshold 70 and two eligible new jobs behind today's empty
attempt. This read-only check did not send messages or consume reservations.

Before deploying this correction, the database was backed up to
`/opt/job_hunter_bot/backups/pre-manual-digest-85d0942/database.dump` on the VPS.
The existing deployment script preserves `.env`, database/Redis volumes and
history, applies Alembic before starting updated writers, then waits for
services. Production `.env` is checked against its pre-deployment checksum.

Live Telegram delivery is triggered by the owner's `/digest` command. The
deployment checks do not send unsolicited job messages.
