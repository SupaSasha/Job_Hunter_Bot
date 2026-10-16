# Himalayas collector

## API verification

Implementation verified on October 16, 2026 against the
[official API documentation](https://himalayas.app/api),
[detailed reference](https://himalayas.app/docs/remote-jobs-api) and
[OpenAPI schema](https://himalayas.app/docs/openapi.json), plus live JSON.

Endpoint: `GET https://himalayas.app/jobs/api`, the unfiltered remote jobs feed.
An API key is not required. Optional `HIMALAYAS_API_KEY` supplies an Authorization
Bearer header for the documented higher allowance; it is hidden from settings
repr and never placed in URLs or application logs. Anonymous operation was
verified. `.env.example` includes an optional blank placeholder.

Pagination uses the current opaque `nextCursor` contract, not deprecated
offsets. Requests use `limit=20` and echo `cursor` only on later pages.
`HIMALAYAS_MAX_PAGES` defaults to 3 and permits 1–5; no historical crawl or
user-specific search is performed. It stops on an empty page, absent/repeated
cursor, or a page contributing no new IDs. Pages are spaced one second apart.
No publication watermark filter is documented for this endpoint, so each run
starts at the newest updated feed entries and existing dedup handles repeats.
The provider documents a daily cache; repeated scheduled checks may see the
same batch and do not promise real-time freshness.

Observed differences from parts of the documentation are handled explicitly:
live publication timestamps use Unix seconds, while OpenAPI also describes
milliseconds; both and aware ISO timestamps are accepted. Live country arrays
contain strings, while OpenAPI describes country objects; both are accepted.
Timezone arrays contain numeric offsets, including fractions, while the schema
also describes strings. `guid` is the source's stable unique identifier,
currently a Himalayas URL; it is retained verbatim as `external_id`.

## Mapping and boundaries

`HimalayasCollector.collect() -> list[JobDTO]` performs only bounded HTTP and
source parsing. `parse_job(raw, *, collected_at=None)` and `parse_page(payload)`
are separate from transport and independently tested. No new DTO, repository,
filter/scoring implementation or translation service was introduced.

| API field | JobDTO field / handling |
| --- | --- |
| guid | external_id, required |
| title, companyName | title, company |
| description | description, shared HTML-to-text helper |
| applicationLink | url, canonical HTTPS Himalayas vacancy page |
| locationRestrictions | location and remote_regions |
| timezoneRestrictions | timezone_text, shared normalization of representable integer intervals |
| employmentType | employment_type, shared canonical aliases |
| seniority | experience_level, shared normalization for single levels |
| categories | technologies, shared explicit technical-category selection |
| minSalary, maxSalary, currency, salaryPeriod | salary fields without currency/period conversion |
| pubDate | published_at, aware UTC |
| collection clock | collected_at, UTC |

The source feed establishes `remote=True`; geography is never assumed global.
Only a documented explicit empty location array becomes Worldwide. A missing,
null or unusable location field remains unknown. Country and region values
pass to shared normalization without expanding geographic hierarchy or using
company location to infer eligibility/timezone.

Explicit category labels such as Python, or unambiguous technical tokens in
labels such as Python-Developer, use the shared existing WWR technical skill
catalog. Nontechnical categories and ambiguous short fragments such as
Go-To-Market/C-Level are excluded. No technologies or seniority are extracted
from title/description in this collector. Single Entry-level/Mid-level values
use the existing junior/middle aliases; multiple seniority labels are retained
together rather than choosing or inventing a single level.

The current DTO stores integer timezone bounds. Fractional offsets stay in
timezone_text with both numeric bounds None, never rounded. Explicit offset
sets with gaps also retain their text without falsely creating a continuous
interval. A contiguous integer set can populate both bounds. The existing
filter/scorer consequently treat unrepresentable bounds as unknown; this stage
does not add exact discrete/fractional timezone matching or extend the DTO.

Missing salary/currency/period stay None. Integral numbers are retained;
fractional salary amounts cannot fit the current integer DTO and are left
unknown rather than silently truncated. Manager/Director/Executive and other
unmapped seniorities are preserved, without inventing scoring aliases.

## Shared architecture and integration

- Canonical source: `himalayas`; display name: Himalayas in EN and ES.
- Registry: `src/collectors/registry.py`; source policy/display catalog:
  `src/services/collector_policy.py`.
- Celery task: `jobs.collect_himalayas`, a thin wrapper over common collection.
- Redis lock: `collector:himalayas:lock`, through the existing 660-second lease.
- Windows: 06:00–07:00, 14:00–15:00, 22:00–23:00 in SCHEDULER_TIMEZONE
  (America/Montevideo by default), with persisted existing jitter.
- Collector states and collector runs use their existing lifecycle and counters.
- Owner /collect dispatches four real tasks asynchronously. /status and /stats
  discover the new source through shared catalogs and recorded state/runs.
- /filters → Sources includes Himalayas in both languages, with callback
  `filters:sources:himalayas`. Source branding is unchanged across locales.
- Job cards credit Himalayas and retain the source vacancy URL for Open vacancy.
- Daily/manual digests, eligibility, ranking and source-neutral scoring use the
  existing common pipeline. No source-specific score bonus was added.

`src/collectors/http.py` extracts the bounded JSON transport used by Get on Board
and Himalayas: 8 MiB decompressed limit, timeout/network/status/JSON failures,
sanitized errors and Retry-After scheduling. `src/collectors/skills.py` reuses
WWR's technical category catalog without changing its existing exact-label
selection. There are no aggressive HTTP retry loops or HTML/page scraping.

Revision `a814d5c0732e` follows `f72c4ea83910`. It appends Himalayas once to each
existing saved source list, preserving that list's previously enabled sources
and not re-enabling disabled old sources. New filter defaults derive from the
active source policy catalog. Other preferences, language, salary and trial
settings are not reset. Downgrade refuses to empty a Himalayas-only selection.

Manual collection CLI:

```bash
poetry run python -m src.scripts.collect_himalayas
```

## Validation

Full suite: **1014 passed**, including **44 real PostgreSQL integration cases**.
Integration tests use disposable schemas of `job_hunter_review_test`; no test
vacancies are inserted into production. Parser/HTTP unit tests have no network.

Coverage includes live-shaped fixtures and schema variants, all required DTO
fields, missing optionals, explicit geography, fractional/discrete timezones,
salary/date formats, cursor bounds/termination, HTTP errors, timeouts, invalid
JSON/schema, decompressed response limits, optional key handling and sanitization.
Shared WWR/Get on Board behavior remains covered. PostgreSQL tests verify
cross-source dedup against all three existing sources, repeat collection,
state/run/statistics integration, migration preservation and schema parity.
Both locales' source buttons/attribution and source-neutral scoring are tested.

Commands run:

```bash
poetry run ruff check .
poetry run black --check .
poetry run pytest
```

The full pytest invocation sets TEST_DATABASE_URL to the dedicated test DB.
The initially stopped local PostgreSQL/Redis services were started before the
successful integration run. No commit or push is performed in this stage.

Live production audit, deployment verification and final working tree follow.

## Live production collection and data audit

Production audit at 2026-10-16T14:11:15.901770+00:00 (October 16, America/Montevideo).
Three pages were fetched anonymously through the real collection pipeline.

| received | new | duplicates | cross-source duplicates | failed |
| ---: | ---: | ---: | ---: | ---: |
| 60 | 60 | 0 | 0 | 0 |

Quality of the 60 normalized incoming jobs:

| Field | Known | Complete |
| --- | ---: | ---: |
| company | 60/60 | 100.00% |
| salary | 23/60 | 38.33% |
| region | 60/60 | 100.00% |
| timezone | 60/60 | 100.00% |
| technologies | 9/60 | 15.00% |
| employment | 60/60 | 100.00% |
| experience | 60/60 | 100.00% |
| integer timezone range | 19/60 | 31.67% |

Timezone completeness means explicit timezone text is present, not that an
integer interval can represent it. Only 19/60 jobs have a representable integer
interval. The other 41 preserve explicit fractional/discrete restrictions in
text; they do not silently acquire broad numeric bounds. Most of this batch is
country-restricted (38 jobs include the United States); no country-to-region
hierarchy was inferred. Technical categories are conservative: most categories
name job roles rather than a recognized programming technology. These figures
measure populated fields, not user-specific suitability or job quality.

Comparison with stored jobs collected in the preceding seven days, before the
owner /collect verification (different sample sizes, not a controlled benchmark):

| Source | Jobs | Salary | Region | Timezone text/bounds | Technologies |
| --- | ---: | ---: | ---: | ---: | ---: |
| getonboard | 18 | 66.67% | 33.33% | 0.00% | 100.00% |
| himalayas | 60 | 38.33% | 100.00% | 100.00% | 15.00% |
| remoteok | 20 | 15.00% | 0.00% | 0.00% | 100.00% |
| weworkremotely | 138 | 0.00% | 100.00% | 0.00% | 24.64% |

All incoming Himalayas jobs had company, employment and source seniority fields.
Compared with these stored samples, Himalayas has more explicit timezone data;
WWR also has complete region data, while Get on Board and Remote OK have lower
region completeness in this window. Technology completeness is lower on the
Himalayas batch. No extraction from descriptions was added to inflate it.

### First five normalized jobs

Descriptions are intentionally omitted. These are actual production collection
results with original titles and company names.

```text
[Himalayas] Senior Product Manager — Seven Starling — us — UTC offsets: [UTC-10, UTC-9, UTC-8, UTC-7, UTC-6, UTC-5, UTC+14] — USD / 135000 / 150000 / annual
[Himalayas] Data Entry Clerk — Better Hearing Centers — us — UTC offsets: [UTC-10, UTC-9, UTC-8, UTC-7, UTC-6, UTC-5, UTC+14] — unknown / unknown / unknown / annual
[Himalayas] Community Moderator & Content Specialist — MENA Alliances — us — UTC offsets: [UTC-10, UTC-9, UTC-8, UTC-7, UTC-6, UTC-5, UTC+14] — unknown / unknown / unknown / annual
[Himalayas] ISSO Support and Continuous ATO Evidence Engineer — Zaden Technologies — us — UTC offsets: [UTC-10, UTC-9, UTC-8, UTC-7, UTC-6, UTC-5, UTC+14] — unknown / unknown / unknown / annual
[Himalayas] Senior Staff Software Engineer, Content Intelligence — Arc XP — us — UTC offsets: [UTC-10, UTC-9, UTC-8, UTC-7, UTC-6, UTC-5, UTC+14] — USD / 144600 / 241100 / annual
```

### Parsed JobDTO example

A compact synthetic fixture follows the verified schema, including explicit
Worldwide eligibility. Its description is authored test text.

```json
{
  "source": "himalayas",
  "external_id": "https://himalayas.app/companies/example/jobs/backend-engineer",
  "title": "Backend Engineer",
  "company": "Example Labs",
  "description": "Build APIs & services.",
  "url": "https://himalayas.app/companies/example/jobs/backend-engineer",
  "location": "Worldwide",
  "timezone_text": null,
  "timezone_min_utc_offset": null,
  "timezone_max_utc_offset": null,
  "remote": true,
  "remote_regions": [
    "worldwide"
  ],
  "employment_type": "full_time",
  "salary_min": 90000,
  "salary_max": 120000,
  "currency": "USD",
  "salary_period": "annual",
  "technologies": [
    "python",
    "fastapi",
    "postgresql"
  ],
  "experience_level": "middle",
  "published_at": "2026-10-16T11:50:13Z",
  "collected_at": "2026-10-16T14:17:10.289709Z"
}
```

### Cross-source duplicates

No matching company/title fingerprints were found between this bounded
Himalayas batch and stored Remote OK, WWR or Get on Board jobs in the existing
30-day dedup window. Therefore there are no live Himalayas cross-source examples
to show from this batch; this is not a claim about the complete provider feeds.
PostgreSQL tests independently demonstrate cross-source suppression against
all three sources and preserve the original row/source. The fingerprint
algorithm is unchanged.

## Deployment and owner command verification

The existing `scripts/deploy.sh` deployed the requested working-tree changes
without a commit or push. It applied revision **a814d5c0732e**, retained existing
PostgreSQL/Redis volumes and restarted the four application processes. All six
services are running, with configured healthchecks passing. Production `.env`
passed a checksum comparison against its pre-deployment snapshot.

A validated PostgreSQL backup is retained on the VPS at
`/opt/job_hunter_bot/backups/pre-himalayas-a39517c/database.dump`.
The configured owner's saved filter sources now include Himalayas.
No trial, language, score threshold or previously disabled old source was reset.

The requested owner CommandHandler paths were exercised with the real Telegram
client and existing Celery dispatcher, using the configured owner identity:

- `/status`: Telegram message 220; Himalayas present in output.
- `/collect`: Telegram message 221; all four collector tasks published asynchronously.
- `/stats`: Telegram message 222; Himalayas present in output.

All four real Celery tasks completed successfully:

| Source | Received | New | Duplicates | Cross-source duplicates | Failed |
| --- | ---: | ---: | ---: | ---: | ---: |
| Remote OK | 99 | 0 | 99 | 4 | 0 |
| We Work Remotely | 87 | 2 | 85 | 0 | 0 |
| Get on Board | 100 | 1 | 99 | 0 | 0 |
| Himalayas | 60 | 0 | 60 | 0 | 0 |

The Remote OK cross-source count is the common task's aggregate, not evidence
that those four overlaps were specifically with Himalayas. Worker logs confirm
receipt and successful completion of `jobs.collect_himalayas`, with its run
persisted in collector statistics. Repeated Himalayas collection inserted no
second copies. `/digest` was not invoked by these checks.

## Final checks and files

- `poetry run pytest`: **1014 passed in 46.72s**, including **44 PostgreSQL cases**.
- `poetry run ruff check .`: all checks passed.
- `poetry run black --check .`: 154 files unchanged.
- `git diff --check`: passed.
- No commit or push; HEAD remains the pre-stage documentation commit `a39517c`.

`git diff --stat` below covers tracked files; new files are listed in full by
`git status --short --untracked-files=all`.

```text
 .env.example                                       |  4 ++
 README.md                                          |  5 +-
 docs/project-guide.md                              | 30 ++++++++---
 src/bot/filters.py                                 |  7 +--
 src/collectors/getonboard.py                       | 46 ++++------------
 src/collectors/registry.py                         |  2 +
 src/collectors/weworkremotely.py                   | 63 +---------------------
 src/config.py                                      |  6 ++-
 src/models/user_filter.py                          |  3 +-
 src/services/collector_policy.py                   |  6 +++
 src/services/normalization.py                      | 14 +++++
 src/tasks/jobs.py                                  | 10 ++++
 tests/bot/test_commands.py                         | 20 ++++---
 tests/bot/test_formatter.py                        |  1 +
 .../test_persistent_filters_postgres.py            |  8 ++-
 tests/integration/test_postgres_hardening.py       |  2 +-
 tests/services/test_collection.py                  | 19 +++----
 tests/services/test_scheduling.py                  | 44 +++++++++++++--
 tests/services/test_statistics.py                  |  7 ++-
 tests/services/test_user_filters.py                |  1 +
 tests/tasks/test_tasks.py                          |  2 +
 tests/test_config.py                               |  4 ++
 22 files changed, 171 insertions(+), 133 deletions(-)
```

```text
## main...origin/main
 M .env.example
 M README.md
 M docs/project-guide.md
 M src/bot/filters.py
 M src/collectors/getonboard.py
 M src/collectors/registry.py
 M src/collectors/weworkremotely.py
 M src/config.py
 M src/models/user_filter.py
 M src/services/collector_policy.py
 M src/services/normalization.py
 M src/tasks/jobs.py
 M tests/bot/test_commands.py
 M tests/bot/test_formatter.py
 M tests/integration/test_persistent_filters_postgres.py
 M tests/integration/test_postgres_hardening.py
 M tests/services/test_collection.py
 M tests/services/test_scheduling.py
 M tests/services/test_statistics.py
 M tests/services/test_user_filters.py
 M tests/tasks/test_tasks.py
 M tests/test_config.py
?? docs/himalayas-stage-report.md
?? migrations/versions/a814d5c0732e_enable_himalayas_source.py
?? src/collectors/himalayas.py
?? src/collectors/http.py
?? src/collectors/skills.py
?? src/scripts/collect_himalayas.py
?? tests/collectors/test_himalayas.py
?? tests/fixtures/himalayas/jobs.json
?? tests/integration/test_himalayas_postgres.py
```
