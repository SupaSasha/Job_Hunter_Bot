# Hardening review implementation report

Date: 2026-10-02. Baseline: `0970e43`. Scope: correctness and bounded work in
existing delivery, polling, deduplication and collectors. No new sources,
onboarding, payments, ML, framework migration, or scoring weight changes.
All user-facing project text remains English. No commit or push was made.

## Review disposition

The implementation was checked against the current repository before editing.
The delivery, polling, unbounded candidate, fingerprint and experience issues
were confirmed and addressed in that order, followed by medium-priority work
and dependency/CI hygiene.

| Request | Status | Before → after | Verification |
| --- | --- | --- | --- |
| 1. Telegram delivery | Fixed | Every error became terminal failed → explicit rejections/connection failures become retryable; ambiguous outcomes become unknown. 429 carries retry_after and persists a deadline; atomic claims prevent concurrent retries. Existing legacy failed rows remain terminal. | Client and notification regression tests: connection failure, 429/4xx, timeouts, sent/unknown, cooldown and final-write failure; PostgreSQL candidate and concurrent claim tests. |
| 2. Poison updates / offset | Fixed | Failing update could block forever; offset lived in memory → three failures skip a logged poison update, Redis checkpoints successful/skipped updates after handling. Redis outages pause processing. | Polling tests cover retry limit, next update, callback, cancellation, Redis failure, and restart without replaying confirmed /collect, /digest and callback updates. |
| 3. Digest candidates | Fixed | Entire historical backlog loaded → collected_at window of 7 days, SQL limit 1000, newest first, future timestamps excluded, retryable cooldown honored. | Real PostgreSQL tests cover all notification states, age, ordering, cooldown and limit. |
| 4. Fingerprint deduplication | Fixed | Missing companies collided on title and company/title matching lasted forever → no fingerprint lookup without company; 30-day lookup with company. Source/external ID stays strict. | Unit tests cover no-company sources, senior/junior fingerprints and bounded lookup; PostgreSQL tests cover recent/60-day-old rows and strict identity. |
| 5. Experience parsing | Fixed | Any number of years could count → explicit experience context required, maximum only among valid matches. | Scoring regressions cover company/product age, professional/software/Python experience and multiple requirements. |
| 6. Delivery bootstrap | Fixed | Two attempted inserts per user every tick → two missing-only SELECTs, bulk insert only missing defaults, no INSERT/commit for initialized users. Scheduler timezone supplies new defaults. | Repository tests cover existing users, missing rows, trial preservation and configured timezone. |
| 7. Manual digest / stale pending | Fixed | Misleading started response and permanent pending reservation → command checks today's state, otherwise replies Digest queued. Stale pending becomes abandoned; history is retained and replacement allowed. | Command state tests, scheduler/service tests, PostgreSQL concurrent reservation and stale recovery tests. |
| 8. Multi-user scope | Documented; implementation unchanged | Per-user delivery settings could imply full personalization → README explicitly states shared filters and owner-oriented MVP; no new onboarding. | Existing authorization and command tests retained; documentation review. |
| 9. Remote OK | Fixed | Naive dates depended on host timezone and body was unbounded → UTC dates, streamed 8 MiB maximum, parsed Retry-After, sanitized error types and chained causes. | Collector regressions cover non-UTC host, response size and 429 deadline. |
| 10. Technology normalization | Fixed | C/C++/C# collapsed in scoring → shared canonicalization preserves symbols and existing aliases across normalization, filters and scoring. | Token/filter/scoring tests cover C variants, postgres/postgresql and fast api/fastapi. |
| 11. Timezone arithmetic | Fixed | Integer floor distorted fractional offsets → shared float calculation with current/relevant-date DST, distance bucket boundaries handle fractional hours. Job offset model unchanged. | India +5.5, Newfoundland -3.5/-2.5 and half-hour scoring tests. |
| 12. Dead completed_dates | Fixed | Production always passed an empty set → removed parameter and call sites; daily idempotency stays in PostgreSQL. | Scheduling tests updated; database reservation race test verifies the real guarantee. |
| 13. Celery wrappers | Fixed within scope | Repeated resource/collection implementation → shared collect_source_async helper, explicit stable named tasks remain. | Existing task/collection tests pass. Repo-wide search found compatibility wrapper use in tests, so it remains. |
| 14. CollectorRun retention | Documented; cleanup unchanged | No formal cleanup policy → recommendation below. No unused setting or destructive cleanup added. | No deletion performed. |
| 15. Dependencies | Fixed where confirmed | Direct pydantic import was transitive and root package installation failed → explicit dependency and application package-mode=false. Existing resolved versions retained. | poetry lock and poetry install pass. Black retained; Linux system tzdata remains appropriate. |
| 16. CI | Added | No basic CI → Python 3.12, Poetry install, Ruff, Black, unit suite and PostgreSQL 16 integration suite for push/PR. | Workflow reviewed and its commands run locally. GitHub-hosted execution requires a later push. |
| 17. PostgreSQL tests | Added | Repository mocks alone → isolated schemas migrated using actual Alembic revisions. | 14 tests cover job/notification uniqueness, fingerprint window, candidates, concurrent claims/reservations, stale history and ARRAY cardinality/ANY. |
| 18. Regression suite | Passed | Existing tests retained or updated for corrected contracts; new targeted regressions added. | Final counts and commands below. |
| 19. Migration safety | Fixed | New statuses/columns/indexes absent → reviewed additive/state-constraint migration, no existing row deletion or status conversion. | Applied locally; migration from empty database exercised by integration fixtures; alembic check clean. |
| 20. Scope constraints | Preserved | Existing sources, scoring weights, subscription rules, ORM, Redis and Celery retained. | Diff review and full regression suite. |
| 21. Report / Git | Completed | This report, updated README, SQL semantics, limitations and Git snapshot supplied. | No commit or push. |

Bootstrap remains a lazy backfill at startup and scheduler discovery so existing
users are supported. It still performs two reads on each discovery, but writes
only when defaults are missing. No full multi-user onboarding is implied.

Existing tests asserting terminal failure for every Telegram error were updated
to distinguish retryable/unknown. Bootstrap tests now model missing-row reads.
Fake candidate repositories accept the shared clock. The old completed_dates
parameter case was replaced by database-backed daily reservation coverage;
DST tests still cover repeated local clock times. Existing coverage was not
removed to hide failures.

## Delivery and recovery limits

- Retryable means definitely not delivered, not necessarily that the underlying
  configuration will recover. Permanent 4xx rejection can remain retryable but
  is tried only by a later eligible digest within the job age window.
- A 429 deadline is honored per notification. There is no separate immediate
  retry queue or bot-wide rate-limit engine. Completed digest attempts still
  block that local day; manual /digest does not force another completed run.
- Historical failed rows cannot safely be reclassified. Unknown outcomes and
  pending notification reservations remain excluded from automatic delivery,
  including after stale digest recovery. A database commit failure after an
  accepted Telegram send remains an ambiguous pending reservation.
- Digest execution has a 600-second timeout; pending recovery defaults to 30
  minutes and accepts settings no lower than 11 minutes. An abandoned run
  cannot overwrite its status through a later progress update. Recovery keeps
  historical rows and can resend a summary, but never resets sent-card identity.
- Polling checkpoints are saved after processing. A restart after confirmation
  does not replay the command. A crash between a side effect and saving its
  checkpoint still has an unavoidable replay window; no distributed exactly-once
  claim is made. Redis persistence and a single poller are operational requirements.
- Fingerprint matching remains a heuristic and is not race-proof across sources;
  source/external ID and user/job uniqueness are enforced by PostgreSQL.

## Candidate SQL and performance

The repository implements the following semantics (`since`, `now`, `user_id`
and `limit` are bound parameters):

```sql
SELECT j.*
FROM jobs AS j
WHERE j.collected_at >= :since
  AND j.collected_at <= :now
  AND NOT EXISTS (
      SELECT 1
      FROM notifications AS n
      WHERE n.user_id = :user_id
        AND n.job_id = j.id
        AND (
            n.status <> 'retryable'
            OR n.retry_after_until > :now
        )
  )
ORDER BY j.collected_at DESC, j.id DESC
LIMIT :limit;
```

`since = now - DIGEST_JOB_MAX_AGE_DAYS`, default 7 days; default limit 1000.
A retryable row with a NULL deadline is eligible. A future cooldown, sent,
unknown, pending or legacy failed row excludes its job. Missing notification
rows are eligible. Scoring then orders only this bounded candidate set by score
and applies the existing threshold/card count. No relationships are eagerly
loaded. Full descriptions remain available for existing filters and scoring.

The migration adds collected_at and fingerprint/collected_at indexes; the
existing unique notification user/job index supports correlated lookup.
Technology filters are resolved later, so no duplicated SQL prefilter was added.
ARRAY semantics are nevertheless exercised against real PostgreSQL.

A newest-first cap bounds memory and scoring cost; it is not a fairness guarantee.
When eligible volume exceeds 1000, older matching jobs may age out before being
considered. Measure candidate saturation, filter rejection rates and query/score
latency before adding pagination or persisted evaluations. A future
job_user_evaluations table should be keyed by user, job, filter revision and
scoring revision with explicit invalidation/expiry; it is unnecessary for the
current bounded MVP and is not included here.

## Migration

Revision: `49f75b591334`, parent: `9f28bc7d43a6`.

- Notification CHECK allows retryable and unknown; nullable retry_after_until added.
- Digest CHECK allows abandoned. uq_digest_user_date becomes a partial unique
  index excluding abandoned rows, preserving previous runs while permitting recovery.
- Jobs gain collected_at and (fingerprint, collected_at) indexes.
- Status columns are strings with CHECK constraints, not PostgreSQL native enums.
- No historical row rewrite, automatic deletes or trial resets are required.
- Downgrade refuses to discard retryable/unknown/abandoned meaning or history;
  those states require manual review first. Otherwise old constraints are restored.

The generated migration was inspected and explicit CHECK changes added because
Alembic autogeneration did not include them. Applied to the local application
DB; current revision is head. `poetry run alembic check` reports no new operations.
Other installations must run `poetry run alembic upgrade head` before starting
updated services. Large deployments should schedule the constraint/index work
in a maintenance window; this migration does not claim concurrent index creation.

## Validation

| Command | Result |
| --- | --- |
| poetry install | Passed; application mode fixes root package discovery |
| poetry run ruff check . | Passed |
| poetry run black --check . | Passed; 124 Python files |
| poetry run pytest -q | 635 passed; 14 integration cases skipped without TEST_DATABASE_URL |
| poetry run pytest -q tests/integration with TEST_DATABASE_URL | 14 passed against PostgreSQL 16 |
| poetry run alembic current | 49f75b591334 (head) |
| poetry run alembic check | No new upgrade operations detected |
| git diff --check | Passed |

Integration tests ran in the dedicated local database job_hunter_review_test.
Each test creates/migrates/drops only its own randomly named schema. Credentials
are supplied via environment and are not recorded here. No live Telegram sends,
collector network runs, or Celery/Beat/polling processes were started for this
review. CI execution itself has not occurred because no push was requested.

## Retention recommendation (not implemented)

- Jobs: consider a 90-day operational horizon, archiving before cleanup. Delete
  only under an explicit policy for feedback/notification references; never drop
  notification identities alone and thereby make old sent jobs eligible again.
  Source identity may need durable tombstones if job rows are removed.
- Collector runs: consider 90 days of detailed runs and retain daily source
  aggregates for longer-term trends. Select a separate 180-day or longer error
  history if operations needs it. Keep collector_states as current scheduling state.
- Digest history: retain abandoned/failed runs for recovery audits. Define a
  business retention period separately from the seven-day candidate window.
- No cleanup task, cleanup migration or unused retention setting was added.

## Git snapshot

Changes remain uncommitted. The snapshot below is captured after implementation;
`git diff --stat` describes tracked file changes, while `git status --short`
also lists new CI, migration, helper, test and report files.

```text
$ git diff --stat
 .env.example                                       |   5 +
 README.md                                          | 126 +++++++++++++++------
 migrations/env.py                                  |   4 +-
 poetry.lock                                        |   2 +-
 pyproject.toml                                     |   5 +
 src/bot/client.py                                  |  42 ++++++-
 src/bot/commands.py                                |  34 +++++-
 src/bot/polling.py                                 |  74 ++++++++++--
 src/bot/statistics.py                              |   3 +
 src/collectors/remoteok.py                         |  67 +++++++----
 src/config.py                                      |   3 +
 src/models/digest_run.py                           |  14 ++-
 src/models/job.py                                  |   4 +-
 src/models/notification.py                         |   3 +-
 src/repositories/digests.py                        |  59 +++++++++-
 src/repositories/jobs.py                           |   8 +-
 src/repositories/notifications.py                  |  27 ++++-
 src/repositories/scheduling.py                     |  44 ++++---
 src/repositories/statistics.py                     |   3 +-
 src/schemas/statistics.py                          |   3 +
 src/scripts/telegram_polling.py                    |   9 +-
 src/services/deduplication.py                      |  16 ++-
 src/services/digests.py                            |  12 +-
 src/services/entitlements.py                       |   9 +-
 src/services/filters.py                            |  36 ++----
 src/services/normalization.py                      |  40 +------
 src/services/notifications.py                      |  45 ++++++--
 src/services/scheduler.py                          |   3 +-
 src/services/scoring.py                            |  66 +++++------
 src/services/statistics.py                         |   4 +-
 src/tasks/jobs.py                                  |  20 ++--
 tests/bot/test_client.py                           |  43 +++++++
 tests/bot/test_commands.py                         |  38 ++++++-
 tests/bot/test_polling.py                          |  89 +++++++++++++++
 tests/collectors/test_remoteok.py                  |  52 +++++++++
 tests/repositories/test_scheduling_repositories.py |  61 +++++++++-
 tests/services/test_deduplication.py               |  30 ++++-
 tests/services/test_digests.py                     |   2 +-
 tests/services/test_notifications.py               |  39 ++++++-
 tests/services/test_scheduling.py                  |  32 +++---
 tests/services/test_scoring.py                     |  20 ++++
 41 files changed, 929 insertions(+), 267 deletions(-)
```

```text
$ git status --short --branch
## main...origin/main
 M .env.example
 M README.md
 M migrations/env.py
 M poetry.lock
 M pyproject.toml
 M src/bot/client.py
 M src/bot/commands.py
 M src/bot/polling.py
 M src/bot/statistics.py
 M src/collectors/remoteok.py
 M src/config.py
 M src/models/digest_run.py
 M src/models/job.py
 M src/models/notification.py
 M src/repositories/digests.py
 M src/repositories/jobs.py
 M src/repositories/notifications.py
 M src/repositories/scheduling.py
 M src/repositories/statistics.py
 M src/schemas/statistics.py
 M src/scripts/telegram_polling.py
 M src/services/deduplication.py
 M src/services/digests.py
 M src/services/entitlements.py
 M src/services/filters.py
 M src/services/normalization.py
 M src/services/notifications.py
 M src/services/scheduler.py
 M src/services/scoring.py
 M src/services/statistics.py
 M src/tasks/jobs.py
 M tests/bot/test_client.py
 M tests/bot/test_commands.py
 M tests/bot/test_polling.py
 M tests/collectors/test_remoteok.py
 M tests/repositories/test_scheduling_repositories.py
 M tests/services/test_deduplication.py
 M tests/services/test_digests.py
 M tests/services/test_notifications.py
 M tests/services/test_scheduling.py
 M tests/services/test_scoring.py
?? .github/
?? docs/hardening-review-report.md
?? migrations/versions/49f75b591334_harden_delivery_retries_and_digest_.py
?? src/services/timezones.py
?? src/services/tokens.py
?? tests/integration/
?? tests/services/test_tokens_timezones.py
```
