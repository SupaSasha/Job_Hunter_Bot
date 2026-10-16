# Jobicy collector

## Verified API

Verified on October 16, 2026 against the [official documentation](https://jobicy.com/jobs-rss-feed),
[official repository](https://github.com/Jobicy/remote-jobs-api),
[OpenAPI schema](https://jobicy.com/api/openapi.json) and live JSON.

Endpoint: `GET https://jobicy.com/api/v2/remote-jobs`. Public requests work
without an API key. No key configuration or Authorization header was added.
The observed API version is 2.2.19.

The response is an object with `apiVersion`, `documentationUrl`,
`friendlyNotice`, `jobCount`, `lastUpdate`, `nextCursor`, `hasMore`,
`appliedFilters`, `statusCode`, `success` and a `jobs` array. Each job contains
`id`, `url`, `jobSlug`, `jobTitle`, `companyName`, `companyLogo`, `jobIndustry`,
`jobType`, `jobGeo`, `jobLevel`, `jobDescription`, `jobExcerpt` and `pubDate`;
salary fields are optional. `jobType` and `jobIndustry` are arrays; `jobGeo`
is a comma-separated string. Publication timestamps are aware ISO timestamps.

Requests use `count=50`, followed by the opaque `cursor` when present.
`JOBICY_MAX_PAGES=2` defaults to at most 100 jobs; configuration permits 1–5
pages. The collector stops on empty/no-progress pages, absent/repeated cursors
or the page cap, deduplicates IDs, and spaces pages one second apart. The
unfiltered public feed provides the last seven days with a three-hour delay;
there is no documented publication-date filter. Missing jobs are not inferred
closed, and no historical crawl or user-specific search is performed.

Automated syncs must be at least an hour apart. The shared collection service
enforces Jobicy's one-hour interval under the existing Redis lock using
persisted `last_started_at`, including manual collection and process restarts.
Longer failure/Retry-After deferrals are respected. Cursor traversal is one
bounded sync, not multiple independent polls. Other sources retain their
existing manual collection behavior.

## Parser contract and DTO

`JobicyCollector(*, timeout=None, max_pages=None, count=50)` implements
`async collect() -> list[JobDTO]`. Network-independent helpers are
`parse_job(raw, *, collected_at=None) -> JobDTO` and
`parse_page(payload) -> tuple[list[JobDTO], str | None]`.
The collector performs HTTP and parsing only, with no persistence, filtering,
deduplication, scoring or Telegram calls.

| API field | JobDTO mapping |
| --- | --- |
| id | Required stable positive numeric ID, stored as a string |
| jobTitle, companyName | title, company, shared HTML entity/text cleanup |
| jobDescription | description, shared HTML-to-text helper |
| url | Canonical HTTPS jobicy.com/jobs/ listing URL |
| jobGeo | location and comma-separated remote_regions |
| jobType | employment_type through shared normalization |
| jobLevel | experience_level through shared normalization |
| salaryMin, salaryMax, salaryCurrency, salaryPeriod | Numeric salary values and original currency/period |
| pubDate | published_at, timezone-aware UTC |
| UTC collection clock | collected_at |

The remote feed sets `remote=True`, without implying unrestricted geography.
Only explicit Anywhere becomes worldwide. Missing geography remains unknown;
there is no source-specific geographic expansion or timezone inference.
Integral nonnegative salary values are accepted; malformed/fractional values
remain unknown. There is no currency conversion or hourly-to-yearly conversion.
Invalid/naive publication dates remain unknown rather than receiving a fabricated
publication timestamp.

The current documented and observed API has no structured technical skills/tags
or timezone requirements. `jobIndustry` is a broad category, not technology.
Accordingly `technologies=[]` and all three timezone fields are None, even when
titles/descriptions mention technologies or timezones. The requested tags-present
fixture would invent an unsupported field, so fixtures instead verify that real
industry categories do not become skills. No description NLP/regex was added.

Verified common aliases add Midweight → middle and the combined
Entry-Level, Junior label → junior.
Any → None means no stated experience restriction. Director and other existing
unmapped values remain explicit values; no seniority is inferred from titles.

Example normalized DTO based on a live-shaped fixture (description abbreviated):

```json
{
  "source": "jobicy",
  "external_id": "147750",
  "title": "Security Software Engineer, IAM",
  "company": "Vercel",
  "description": "Work with the remote team.",
  "url": "https://jobicy.com/jobs/147750-security-software-engineer-iam",
  "location": "USA",
  "remote": true,
  "remote_regions": ["us"],
  "employment_type": "full_time",
  "salary_min": 208000,
  "salary_max": 312000,
  "currency": "USD",
  "salary_period": "yearly",
  "technologies": [],
  "experience_level": "senior",
  "published_at": "2026-10-16T03:50:03Z",
  "collected_at": "2026-10-16T14:00:00Z",
  "timezone_text": null,
  "timezone_min_utc_offset": null,
  "timezone_max_utc_offset": null
}
```

## Shared integration

- Canonical source/display: `jobicy` / Jobicy in both EN and ES.
- Registry: `src/collectors/registry.py`; source/display/scheduling policy:
  `src/services/collector_policy.py`.
- Schedule: 03:00–04:00, 11:00–12:00, 19:00–20:00 in SCHEDULER_TIMEZONE
  (default America/Montevideo), with the existing persisted jitter.
- Redis lock: `collector:jobicy:lock`, through the shared lock lifecycle.
- Celery task: `jobs.collect_jobicy`, a thin common collection wrapper.
- Pipeline: JobDTO → NormalizationService → JobPipeline/JobSaveService →
  DeduplicationService → PostgreSQL. Existing fingerprint rules are unchanged.
- Existing CollectorState and CollectorRun retain timestamps, status, retry
  schedule and all counters. Skipped hourly-cooldown invocations also record a run.
- Owner `/collect` dispatches five tasks; `/status` discovers five states and
  `/stats` includes Jobicy through the shared catalog and run aggregation.
- `/filters` includes `filters:sources:jobicy` in both languages. Job cards
  attribute Jobicy and link to the canonical source listing.
- Common daily/manual digest, filtering and source-neutral scoring remain in
  use. No source bonus, weights or product behavior was added.

The existing bounded JSON helper provides an 8 MiB decompressed response cap,
timeouts, network/status errors including 429/Retry-After, invalid JSON/schema
handling and sanitized errors without response bodies or sensitive parameters.
The new shared cursor helper is also used by Himalayas, preserving its existing
page size, cap and parser behavior. There are no aggressive retries or HTML
scraping.

Migration `b927c64ed108` follows `a814d5c0732e`, changes the source default and
appends Jobicy once to saved source selections. Existing enabled/disabled older
sources and unrelated preferences are preserved. New profiles include all five
sources. Downgrade refuses to empty a Jobicy-only selection.

Manual CLI, using the same lock, state and pipeline:

```bash
poetry run python -m src.scripts.collect_jobicy
```

## Validation

All checks passed: `poetry run ruff check .`, `poetry run black --check --workers 1 .`,
and the full pytest suite: **1122 passed in 54.86 seconds**, including **50 real
PostgreSQL integration cases**. TEST_DATABASE_URL pointed to the dedicated
`job_hunter_review_test` database; tests create and remove disposable schemas.
No production fixture vacancies were inserted.

Coverage includes all DTO fields, compact live-shaped fixtures, missing fields,
unknown skills/timezones, geo restrictions, salary/date formats, stable IDs,
malformed items/pages, bounded cursor traversal and HTTP failures/sanitization.
Shared Himalayas behavior remains covered. PostgreSQL tests exercise cross-source
dedup against each of the four existing sources, repeat collection after the
hourly interval, cooldown persistence across service instances, state/run/stats,
and safe migration/defaults/downgrade. Both locales' attribution/source buttons,
source-neutral scoring, windows, task dispatch and longer Retry-After deferral
are tested.

## Production and live audit


### Deployment

A validated PostgreSQL custom-format backup was created at
`/opt/job_hunter_bot/backups/pre-jobicy-aa54c86/database.dump` (1.2 MiB,
mode 0600, directory 0700). The existing deployment script completed successfully:
source transfer, image build, migration and service restart. All six services
are running; PostgreSQL, Redis, API and worker passed their health checks.
The server `.env` checksum matches its pre-deployment snapshot, and persistent
volumes were preserved. Alembic is at `b927c64ed108`.
Both existing filter profiles now include Jobicy; the database source default
also includes all five sources. Migration preservation is covered by real
PostgreSQL tests. No commit, push or automatic /digest was performed.

### Live collection

One bounded two-page Jobicy collection ran through the real production
CollectionService at **2026-10-16 14:49:21–14:49:23 UTC**. Result:

| Received | New | Duplicates | Cross-source duplicates | Failed | Duration |
| --- | --- | --- | --- | --- | --- |
| 100 | 99 | 1 | 1 | 0 | 2280 ms |

The first five received jobs, before deduplication:

| Source | Title | Company | Region | Employment | Salary |
| --- | --- | --- | --- | --- | --- |
| Jobicy | Security Software Engineer, IAM | Vercel | USA | full_time | 208000–312000 USD / yearly |
| Jobicy | Major Gifts Officer | Mozilla | Canada, Germany, UK, USA | full_time | 102200–131523 USD / yearly |
| Jobicy | Postgres Engineer | Supabase | Anywhere | full_time | Unknown |
| Jobicy | Marketplace Operations Manager II | Wheel | USA | full_time | 122075–155000 USD / yearly |
| Jobicy | ANALYST DIGITAL MARKETING IV (Remote) IV | TE Connectivity | USA | full_time | 116300–174400 USD / yearly |

The first Vercel job already existed under We Work Remotely and was correctly
excluded from new storage. The audit used the existing exact normalized
company/title fingerprint and a 30-day comparison window against all four
existing sources. Observed matches: Remote OK 0, WWR 1, Get on Board 0,
Himalayas 0; overlap is **1% of the received batch**. Only one live cross-source
match existed, so additional examples are not fabricated. PostgreSQL tests
verify deduplication against each source and repeat collection after an hour.
No fingerprint or source-specific dedup rule was changed.

### Data completeness

Completeness is measured on all 100 normalized received jobs, including the
one excluded duplicate. Salary known means a positive minimum or maximum;
experience known excludes Any (no stated restriction).

| Field | Known / total | Completeness |
| --- | --- | --- |
| Company | 100 / 100 | 100% |
| Salary | 49 / 100 | 49% |
| Region | 100 / 100 | 100% |
| Timezone | 0 / 100 | 0% |
| Technologies | 0 / 100 | 0% |
| Employment | 100 / 100 | 100% |
| Experience | 82 / 100 | 82% |

Useful source fields are companyName, explicit jobGeo, jobType, jobLevel,
structured numeric salary and pubDate. All jobs have explicit geography;
5 are worldwide, 55 mention the US, and 5 mention LATAM (multiregion jobs can
count in multiple groups). This is a global collection, not a Python-only query.
Absent structured technologies/timezones are a documented data limitation;
industry labels and descriptions are deliberately not used to fill them.

For context, existing stored jobs collected in the preceding seven days had
these completeness percentages at audit time. These differently sized batches
are descriptive observations, not a source quality ranking:

| Source | Stored jobs | Company | Salary | Region | Timezone | Technologies | Employment | Experience |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| getonboard | 19 | 100% | 63.16% | 31.58% | 0% | 100% | 100% | 100% |
| himalayas | 60 | 100% | 38.33% | 100% | 100% | 15% | 100% | 100% |
| jobicy | 99 | 100% | 48.48% | 100% | 0% | 0% | 100% | 81.82% |
| remoteok | 20 | 100% | 15% | 0% | 0% | 100% | 0% | 0% |
| weworkremotely | 140 | 100% | 0% | 100% | 0% | 25.71% | 99.29% | 0% |

### Postdeployment owner commands

The real command handler was invoked with the configured owner identity and
sent its responses to the owner via Telegram; this verifies handler/delivery,
not a new incoming Telegram update. The existing polling service remains running.

- `/status`: Telegram message 223 includes Jobicy, last success and next run.
- `/collect`: message 224 confirms dispatch. All five real tasks completed in
  Celery with SUCCESS; detailed results follow.
- The Jobicy task was received and completed in worker logs. It returned
  skipped/cooldown because the live collection had just succeeded, avoiding
  a second API sync within the documented hour. A separate skipped run is
  recorded; source state remains success.

| Source | Received | New | Duplicates | Cross-source duplicates | Failed | Outcome |
| --- | --- | --- | --- | --- | --- | --- |
| remoteok | 99 | 0 | 99 | 4 | 0 | success |
| weworkremotely | 87 | 1 | 86 | 0 | 0 | success |
| getonboard | 100 | 0 | 100 | 0 | 0 | success |
| himalayas | 60 | 0 | 60 | 0 | 0 | success |
| jobicy | 0 | 0 | 0 | 0 | 0 | cooldown |

Jobicy state after checks: last success `2026-10-16T14:49:23.878466Z`,
next run `2026-10-16T22:35:28Z` (**19:35:28 America/Montevideo**, inside the
19:00–20:00 window), status success, no error. The cooldown run did not reset
that schedule or the successful timestamps.

`/stats` was delivered as Telegram message 225 and reports Jobicy with two runs:
one success, one skipped, received 100, new 99, duplicates 1, cross-source
1, failed jobs 0. These values agree with PostgreSQL run records and the live
audit. EN/ES source buttons and card attribution are verified by unit tests;
production migration/default checks confirm source availability for users.

## Files and working tree

New runtime files are the Jobicy collector, shared cursor helper, collection
CLI and source-default migration. Existing runtime changes cover the source
registry, config, scheduling/hourly guard, thin Celery task and three shared
experience aliases. Himalayas now reuses the cursor helper. README and project
guide include Jobicy. New parser/HTTP fixtures and PostgreSQL tests accompany
updates to source catalogs, dispatch, state, statistics and filter assertions.
The complete paths are in the status snapshot below.

`git diff --stat` (tracked files only; eight new files follow in git status):

```text
 .env.example                                       |  3 ++
 README.md                                          |  2 +-
 docs/project-guide.md                              | 31 ++++++++++---
 src/collectors/himalayas.py                        | 43 ++++-------------
 src/collectors/registry.py                         |  2 +
 src/config.py                                      |  1 +
 src/services/collection.py                         | 11 +++++
 src/services/collector_policy.py                   |  8 ++++
 src/services/normalization.py                      |  3 ++
 src/tasks/jobs.py                                  | 10 ++++
 tests/bot/test_commands.py                         |  6 ++-
 tests/collectors/test_himalayas.py                 |  4 +-
 tests/integration/test_himalayas_postgres.py       |  3 +-
 .../test_persistent_filters_postgres.py            |  2 +
 tests/integration/test_postgres_hardening.py       |  2 +-
 tests/services/test_collection.py                  | 54 ++++++++++++++++++++++
 tests/services/test_scheduling.py                  | 29 +++++++++++-
 tests/services/test_statistics.py                  |  1 +
 tests/services/test_user_filters.py                |  1 +
 tests/tasks/test_tasks.py                          |  2 +
 20 files changed, 171 insertions(+), 47 deletions(-)
```

`git status --short --branch --untracked-files=all`:

```text
## main...origin/main
 M .env.example
 M README.md
 M docs/project-guide.md
 M src/collectors/himalayas.py
 M src/collectors/registry.py
 M src/config.py
 M src/services/collection.py
 M src/services/collector_policy.py
 M src/services/normalization.py
 M src/tasks/jobs.py
 M tests/bot/test_commands.py
 M tests/collectors/test_himalayas.py
 M tests/integration/test_himalayas_postgres.py
 M tests/integration/test_persistent_filters_postgres.py
 M tests/integration/test_postgres_hardening.py
 M tests/services/test_collection.py
 M tests/services/test_scheduling.py
 M tests/services/test_statistics.py
 M tests/services/test_user_filters.py
 M tests/tasks/test_tasks.py
?? docs/jobicy-stage-report.md
?? migrations/versions/b927c64ed108_enable_jobicy_source.py
?? src/collectors/jobicy.py
?? src/collectors/pagination.py
?? src/scripts/collect_jobicy.py
?? tests/collectors/test_jobicy.py
?? tests/fixtures/jobicy/jobs.json
?? tests/integration/test_jobicy_postgres.py
```

Branch remains at aa54c86, in sync with origin/main. All stage changes are
uncommitted and unstaged. No subsequent source or feature was started.
