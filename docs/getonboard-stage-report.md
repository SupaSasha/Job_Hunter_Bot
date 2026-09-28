# Get on Board stage report

## Result and data source

Get on Board is connected to the existing JobDTO -> NormalizationService ->
JobSaveService / DeduplicationService -> PostgreSQL pipeline, Celery registry,
scheduler, CollectorState, /collect, /status and shared job-card source naming.

The collector uses Get on Board's official public JSON API, without credentials:

https://www.getonbrd.com/api/v0/categories/programming/jobs

Primary references checked during implementation:

- [Official public/private API overview](https://www.getonbrd.com/user-manual/get-on-board-s-api).
- [Current API capabilities](https://www.getonbrd.com/help/what-can-i-do-with-get-on-board-s-api).
- [Official API reference](https://www.getonbrd.com/api-doc.html).
- [Published OpenAPI specification](https://www.getonbrd.com/doc/openapi.yaml).
- [Official Ruby client examples for public categories and expansion](https://github.com/getonbrd/getonbrd-ruby).

The API directly provides published jobs, stable source IDs and expanded related
resources. This meets the preferred official-API route; RSS, page scraping and
browser automation are unnecessary. Discovery and live collection requests to the
category endpoint returned HTTP 200. No authorization, bot protection, or rate
limit was bypassed. The public search endpoint requires at least one search/filter
parameter; its unfiltered request returned an ordinary 422 validation error.

## Scope and pagination

The default collector covers the first two Programming pages with 50 records per
page (up to 100 before repeated-ID deduplication). Programming was selected to
match the project's existing developer-job profile. This is a bounded source
sample, not complete coverage of Get on Board or its entire history.

The API reference does not guarantee chronological ordering or provide an
incremental cursor for this endpoint. Therefore the collector does not discard
jobs using an assumed publication-date cutoff. Featured ordering or more than
100 relevant records may leave some jobs outside the default sample.

Configuration is limited to 1..5 pages and 1..120 records per page. Traversal stops
on an empty page, the declared last page, a short page without pagination metadata,
or a page that adds no new IDs. Requests are sequential with a one-second pause
between pages. There are no per-job detail calls.

HTTP uses the existing User-Agent, timeout, an 8 MiB response limit, sanitized
network/HTTP errors and no immediate retries. HTTP 429 Retry-After is passed to
the existing scheduler cooldown logic. A failed later page fails the fetch instead
of presenting the partial batch as complete.

## Files

Created:

- src/collectors/getonboard.py
- src/collectors/text.py
- src/scripts/collect_getonboard.py
- tests/collectors/test_getonboard.py
- docs/getonboard-stage-report.md

Modified:

- README.md
- src/bot/commands.py
- src/bot/formatter.py
- src/collectors/registry.py
- src/collectors/weworkremotely.py
- src/services/collector_policy.py
- src/services/normalization.py
- src/tasks/jobs.py
- tests/bot/test_commands.py
- tests/bot/test_formatter.py
- tests/services/test_collection.py
- tests/services/test_deduplication.py
- tests/services/test_normalization.py
- tests/services/test_scheduling.py
- tests/tasks/test_tasks.py

No dependency or migration was added. Filters, scoring, fingerprint calculation,
and the daily digest were not changed.

## Public API

```python
collector = GetOnBoardCollector(timeout=20, max_pages=2, per_page=50)
jobs = await collector.collect()  # list[JobDTO]

parse_job(raw: dict, *, collected_at=None) -> JobDTO
parse_page(payload: dict) -> tuple[list[JobDTO], int | None]
```

Standalone fetch without persistence:

```bash
poetry run python -m src.collectors.getonboard
```

Shared persistence pipeline:

```bash
poetry run python -m src.scripts.collect_getonboard
```

The collector only requests/parses source data. It does not call repositories,
normalization, filters, scoring or Telegram. The existing CollectionService selects
it from COLLECTORS and owns the source lock, state and reusable pipeline.

## Mapping

- source is getonboard; external_id is the API's stable job ID, not a hash.
- links.public_url supplies the job URL.
- Expanded company, tags, modality, seniority, location_regions, location_tenants
  and location_cities provide their explicit names, with no ID guessing.
- Description sections are converted to readable text through a small shared
  HTMLParser helper extracted from WWR. WWR behavior remains covered by its tests.
- remote requires an explicit true source flag. hybrid, no_remote and
  temporarily_remote modalities remain false for this remote delivery profile.
- A country value of Remote is not interpreted as a country or Worldwide.
  Expanded regions/countries supply remote_regions; company headquarters are
  ignored. The explicitly unrestricted fully_remote modality maps to Worldwide
  only when no narrower eligibility fields are supplied.
- Source region names pass to NormalizationService unchanged: Latin America
  becomes latam and South America becomes south_america there. No LATAM-to-Uruguay
  rule or source-specific eligibility branch was added.
- Explicit tag names supply technologies; description prose is not mined for skills.
- Full time and other employment names use existing canonical normalization.
  General Semi Senior / Semi-Senior / semi_senior aliases now normalize to middle.
- min_salary/max_salary are preserved as numeric values. Currency and period are
  only retained when explicitly supplied; no currency conversion or unit guess.
- remote_zone supplies timezone_text when present. Company country is never used
  to infer timezone. Existing normalization handles unambiguous UTC/GMT offsets.
- published_at epoch/aware ISO values and collected_at use UTC-aware datetimes.
  Missing/invalid optional fields stay None or empty.

## Scheduling, commands and delivery

| Property | Value |
| --- | --- |
| Canonical source | getonboard |
| Celery task | jobs.collect_getonboard |
| Redis lock | collector:getonboard:lock |
| Daily windows | 06:00–08:00 and 20:00–22:00 |
| Timezone | SCHEDULER_TIMEZONE, currently America/Montevideo |
| Jitter | Existing random second inside the next window, saved in UTC |

The selected windows avoid the existing ordinary Remote OK and WWR windows.
Retry or queue delays can still cause overlap; source locks remain independent.
Get on Board owns its own last_started_at, last_success_at, last_finished_at,
next_run_at, last_status and last_error. No future-source states were added.

COLLECTORS, COLLECTOR_POLICIES and COLLECTOR_TASKS now contain exactly three
implemented sources. SchedulerService already dispatches policy.task_name and
required no new source-specific branches.

/collect remains owner-only and publishes three independent tasks outside the
polling event loop. Its acknowledgment remains Collection started. Non-owner
denial remains tested. /status displays all three states, including Never before
a source's first success. The common source_display_name helper is reused by
/status and job cards, which now display Source: Get on Board (and the human
names for the two older sources).

Jobs go into the shared jobs table. The existing user filters, score thresholds,
daily reservation and job notification deduplication remain responsible for
delivery. Collection itself sends no Telegram messages.

## Real collection results

Two deliberate live production-pipeline checks completed on 2026-09-28 using
the real public API, Redis lock and PostgreSQL.

| Run | received | new | duplicates | failed |
| --- | ---: | ---: | ---: | ---: |
| First | 100 | 98 | 2 | 0 |
| Second | 100 | 0 | 100 | 0 |

Counts per source after the checks:

| Source | Persisted jobs |
| --- | ---: |
| Remote OK | 103 |
| We Work Remotely | 78 |
| Get on Board | 98 |
| Total | 279 |

First three actual listings:

```text
[Get on Board] Senior Front-end Developer — TCIT — Santiago, Chile
[Get on Board] Principal Engineer — Cocoon — Central America, South America
[Get on Board] Front-end Engineer — Cumplo — Santiago, Chile
```

## Example mapped JobDTO

Real remote Python listing; description is shortened only for the report.

```json
{
  "source": "getonboard",
  "external_id": "software-developer-ai-remote-steuart-nutrition-remote",
  "title": "Software Developer (AI )",
  "company": "STEUART NUTRITION",
  "description": "Steuart Nutrition is a GMP-certified contract manufacturer producing powders, liquids, capsules, and stick packs for growing wellness brands. We build and improve internal tools to [excerpt]",
  "url": "https://www.getonbrd.com/jobs/software-developer-ai-remote-steuart-nutrition-remote",
  "location": null,
  "timezone_text": null,
  "timezone_min_utc_offset": null,
  "timezone_max_utc_offset": null,
  "remote": true,
  "remote_regions": [
    "Worldwide"
  ],
  "employment_type": "Full time",
  "salary_min": 3200,
  "salary_max": 4500,
  "currency": null,
  "salary_period": null,
  "technologies": [
    "Web Application Development",
    "Code Documentation",
    "Agentic Coding",
    "JavaScript",
    "TypeScript",
    "Python",
    "API Integration"
  ],
  "experience_level": "Senior",
  "published_at": "2026-09-23T16:47:02Z",
  "collected_at": "2026-09-28T21:45:26.750726Z"
}
```

## LATAM and data quality observations

- 54 of 100 jobs were remote; 46 were nonremote/hybrid according to the source fields.
- All 54 remote jobs had usable region data after mapping. No remote record in this
  sample was lost because its region was missing. The generic Remote placeholder
  was replaced by explicitly expanded eligibility or unrestricted fully_remote.
- 12 remote jobs included South America; 25 were explicitly unrestricted Worldwide.
  Specific countries included Mexico, Colombia, Peru, Chile, Argentina, Brazil,
  Bolivia and Ecuador, among others. Lists can overlap, so region counts are not
  mutually exclusive. No direct Uruguay-only or Latin America label appeared in
  this sample; those mappings are covered by fixtures.
- 100 records contained explicit technology tags; 15 included Python after
  normalization. The existing user filter profile accepted 7 records. This does
  not assert that they meet the digest score threshold or were sent.
- 43 records exposed numeric salary values. None exposed currency or salary period;
  these remain None. No amount was labelled USD/month based on an assumption.
- No record exposed non-null timezone text. No timezone was inferred from employer
  location or country; existing filtering therefore has no offset restriction
  to compare for these records.
- Example accepted by current filters: STEUART NUTRITION / Software Developer (AI ),
  remote Worldwide, Python among explicit tags, salary 3200–4500 with unspecified
  currency/period. Existing filters/scoring were not adjusted based on this sample.

## Fingerprint duplicates

No new cross-source fingerprint match against Remote OK or WWR was found in this
Get on Board sample. Unit tests cover matching company/title pairs across each
of those sources and Get on Board. URL is not the cross-source key.

The first run's two duplicates were within Get on Board:

- Niuro / Web App Full-Stack Engineer: 2 records; fingerprint 4be6cb1d6596ee9140028f8514261f56a72e397868a13f2fc9efead59a2b128f.
- Factor IT / Tech Lead Senior: 2 records; fingerprint 1a96d591bb7b3c617480a86d61f34a8a817d4084ee9db721d1d4a353576e50ef.

Matching company/title values can represent reposts or separate openings; the
existing fingerprint heuristic cannot distinguish them. It was not broadened and
no fuzzy matching was added.

## Live /status and runtime

The following output was rendered against PostgreSQL without sending a test
Telegram message:

```text
Bot status: running

Remote OK
Last success: 2026-09-28 18:40
Next run: 2026-09-29 02:54
Last status: success

Get on Board
Last success: 2026-09-28 18:45
Next run: 2026-09-28 21:53
Last status: success

We Work Remotely
Last success: 2026-09-28 18:25
Next run: 2026-09-29 05:10
Last status: success

Jobs in database: 279

Daily digest:
Time: 09:00
Timezone: America/Montevideo
Last digest: Today (empty)
Enabled: Yes

Times shown in America/Montevideo.
```

Worker and polling were gracefully restarted to load the third collector. A real
Celery inspect confirmed all three jobs.collect_* tasks registered. Processes
remain running: worker PID 549654, polling PID 549721, Beat PID 349832.
The next persisted Get on Board run was 2026-09-29 00:53:57 UTC, equivalent to
2026-09-28 21:53:57 America/Montevideo.

## Checks

- poetry run ruff check .: passed.
- poetry run black --check .: passed; 106 Python files unchanged.
- poetry run pytest -q: 529 passed.
- git diff --check: passed.

Collector tests use small synthetic JSON fixtures and httpx.MockTransport, not
real network access. Coverage includes optional fields, LATAM mapping, country
restrictions, hybrid/unknown remote flags, salary units, aware dates, general
seniority aliases, bounded/repeated pagination, failed later pages, 429 cooldown,
HTTP/network failures and response limits. Integration unit tests cover separate
locks, all three policies/tasks, owner /collect dispatch, non-owner denial,
/status placeholders, source display names and cross-source fingerprints.

No commit or push was made.

## Git snapshot

git diff --stat (tracked files; created files appear separately in status):

```text
 README.md                            | 64 +++++++++++++++++++++++++++++++++---
 src/bot/commands.py                  |  5 ++-
 src/bot/formatter.py                 |  3 +-
 src/collectors/registry.py           |  2 ++
 src/collectors/weworkremotely.py     | 42 ++---------------------
 src/services/collector_policy.py     | 11 +++++++
 src/services/normalization.py        |  3 ++
 src/tasks/jobs.py                    | 13 ++++++++
 tests/bot/test_commands.py           | 36 ++++++++++++++++++++
 tests/bot/test_formatter.py          | 13 ++++++++
 tests/services/test_collection.py    | 31 ++++++++++++++++-
 tests/services/test_deduplication.py | 18 ++++++++++
 tests/services/test_normalization.py | 14 ++++++++
 tests/services/test_scheduling.py    | 29 ++++++++++++++--
 tests/tasks/test_tasks.py            |  2 ++
 15 files changed, 234 insertions(+), 52 deletions(-)
```

git status --short --branch:

```text
## main...origin/main
 M README.md
 M src/bot/commands.py
 M src/bot/formatter.py
 M src/collectors/registry.py
 M src/collectors/weworkremotely.py
 M src/services/collector_policy.py
 M src/services/normalization.py
 M src/tasks/jobs.py
 M tests/bot/test_commands.py
 M tests/bot/test_formatter.py
 M tests/services/test_collection.py
 M tests/services/test_deduplication.py
 M tests/services/test_normalization.py
 M tests/services/test_scheduling.py
 M tests/tasks/test_tasks.py
?? docs/getonboard-stage-report.md
?? src/collectors/getonboard.py
?? src/collectors/text.py
?? src/scripts/collect_getonboard.py
?? tests/collectors/test_getonboard.py
```
