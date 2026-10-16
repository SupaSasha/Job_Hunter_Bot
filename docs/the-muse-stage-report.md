# The Muse collector

## API and authentication

Verified on October 16, 2026 using the [official API reference](https://www.themuse.com/developers/api/v2)
and real anonymous JSON responses. Endpoint:
`GET https://www.themuse.com/api/public/jobs`. The older api-v2 host redirects
and is not used. A testing request works without a key; ongoing use requires
app registration. Set `THE_MUSE_API_KEY` to the registered app key. Authentication
uses the documented `api_key` query parameter, not an invented Bearer header.
The provider documents 500 requests/hour anonymously and 3600 with a key.
[Register an app](https://www.themuse.com/developers/api/v2/apps).

Settings and `.env.example` include a blank key and `THE_MUSE_MAX_PAGES=3`.
The key is excluded from Settings repr. Existing Telegram HTTP log sanitization
was extracted into `src/logging_filters.py` and extended to redact api_key query
values, including percent-encoded keys in HTTPX/httpcore diagnostics. Both the
Telegram client and shared bounded JSON transport install the same filter.
Raw exception text, headers, keys and response bodies are not logged.

Production preflight found no configured server key. With MODE=PROD the collector
now rejects a missing registered key before sending a request. Anonymous access
remains available for development/testing. This does not block other collectors.

HTTP 401/403 returns a sanitized access-denied error identifying the key/quota
configuration to check; 403 can also indicate the provider's quota. HTTP 429
uses the existing Retry-After helper and shared persistent retry scheduling.
Timeout, network, other HTTP, invalid JSON/schema and oversized response failures
also use the existing sanitized CollectionError mechanism, without immediate
retry loops or HTML scraping. The decompressed per-response cap is 8 MiB.

## Actual response and parser

The observed response has `page`, `page_count`, `items_per_page`, `took`,
`timed_out`, `total`, `results` and `aggregations`. Pages contain 20 results.
Jobs have `id`, `name`, `contents`, `company`, `locations`, `levels`,
`categories`, `tags`, `publication_date`, `refs`, `type`, `short_name` and
`model_type`. Current links are in **refs.landing_page**, not an assumed API URL.
The observed type external describes the source record, not employment type.

`TheMuseCollector(*, timeout=None, max_pages=None)` implements
`async collect() -> list[JobDTO]`. Separate network-independent helpers:
`parse_job(raw, *, collected_at=None) -> JobDTO` and
`parse_page(payload, *, page) -> tuple[list[JobDTO], bool]`.
The collector only performs official HTTP and source parsing. Persistence,
deduplication, filters, scoring and Telegram are outside it.

| Source field | JobDTO field / handling |
| --- | --- |
| id | Required stable positive numeric ID, stored as a string |
| name | title, shared HTML entity/text cleanup |
| company.name | company, or None when absent |
| contents | description, existing HTML-to-text helper |
| refs.landing_page | url, required canonical HTTPS The Muse listing |
| locations[].name | location, preserving multiple locations |
| Explicit Flexible / Remote location | remote=True; absence uses the legacy False default |
| levels[].name | experience_level through shared normalization |
| publication_date | published_at, aware UTC; invalid/naive stays None |
| Current UTC collection clock | collected_at |

Remote eligibility geography is not explicit: `remote_regions=[]`, including
for remote-marked jobs. A city is not a US-only restriction, and the remote
marker does not mean worldwide. Cities/company headquarters never imply
timezone restrictions. Salary, currency, period, employment and timezone fields
are absent in the observed structured API and remain None. Broad categories and
employer-brand tags are not technologies, so `technologies=[]`. There is no
description regex, title-based inference or NLP.

Common normalization adds Mid Level → middle and Senior Level → senior.
Entry Level already maps to junior. Management and Internship remain their
explicit normalized labels, without inventing a scoring equivalence. Multiple
levels are retained together rather than selecting an arbitrary one.

### Remote semantics and manual checks

The existing DTO and database have a non-null bool, with False also covering
unconfirmed remote status. No DTO/schema change was introduced. Therefore the
collector sets True only for an explicit Flexible / Remote location; it does
not claim that every False result proves an office-only requirement. The
provider's label represents remote/flexible work, not a guarantee of unrestricted
or permanently fully remote work.

Real API records were checked separately from the remote-only live batch:

- Explicit remote: Atlassian, Principal Technical Product Manager - Commerce
  (Billing & Monetization); Bangalore, India plus Flexible / Remote → True,
  unknown eligibility regions.
- Explicit office: Cummins, Administrative Associate - Level III - General
  Management (Assistant); San Luis Potosí, Mexico → False. Manual inspection
  of the source description confirms an office role and full on-site work.
  This inspection does not add description parsing to the collector.
- Ambiguous city-only: Walmart, Retail Customer Service Associate; Omaha, NE →
  False, unknown eligibility. City alone is not treated as proof of office-only.
- Authored missing-locations case: title Remote Python Engineer with no location
  metadata → False. The title cannot override missing evidence.

Fixtures cover remote, non-remote, multiple locations/levels, company, HTML and
missing optionals. Descriptions are short authored text, not large API dumps.

### Example normalized DTO

Based on the real-shaped fixture; the description is authored fixture text:

```json
{
  "source": "the_muse",
  "external_id": "22229841",
  "title": "Principal Technical Product Manager - Commerce (Billing & Monetization)",
  "company": "Atlassian",
  "description": "Join our team & build useful products.",
  "url": "https://www.themuse.com/jobs/atlassian/principal-technical-product-manager-commerce-billing-monetization",
  "location": "Bangalore, India, Flexible / Remote",
  "remote": true,
  "remote_regions": [],
  "employment_type": null,
  "salary_min": null,
  "salary_max": null,
  "currency": null,
  "salary_period": null,
  "technologies": [],
  "experience_level": "senior",
  "published_at": "2026-10-03T21:25:38Z",
  "collected_at": "2026-10-16T15:48:52.356685Z",
  "timezone_text": null,
  "timezone_min_utc_offset": null,
  "timezone_max_utc_offset": null
}
```

## Pagination and freshness

The broad query is `page=0&descending=true&location=Flexible%20%2F%20Remote`.
It collects all categories, without Python/user-specific queries. Later requests
increment the zero-based page. The default cap is 3 pages/60 jobs; configuration
permits 1–5 pages. Collection stops at page_count, empty results or no new IDs,
deduplicates source IDs, and spaces successive pages one second apart.
Mismatched pagination, all-invalid pages and timed_out searches fail explicitly.

The provider describes a ranking combining several factors, not a guaranteed
publication-date sort. A descending flag is supported, but live data is not
newest-first. No documented publication watermark parameter was found; bounded
initial pages and existing dedup are used, with no historical crawler.

The live batch spans publication dates **2021-02-25 to 2026-10-15**; only **11/60**
were published within seven days. Original publication times are preserved,
never replaced by collection time. This is a material source-freshness limitation.
The existing digest candidate query uses collection age; this stage does not
change that shared behavior or add a new publication-age filter.

## Registry, scheduling and application integration

- Canonical source: `the_muse`; display name: The Muse in EN and ES.
- Collector registry: `src/collectors/registry.py`.
- Source/display/scheduling policy: `src/services/collector_policy.py`.
- Windows: 07:00–08:00 and 19:00–20:00 in SCHEDULER_TIMEZONE, default
  America/Montevideo, with existing persisted random jitter.
- Redis lock: `collector:the_muse:lock`, using the common lock lifecycle.
- Celery task: `jobs.collect_the_muse`, a thin async common-service wrapper.
- Pipeline: JobDTO → NormalizationService → JobPipeline/JobSaveService →
  DeduplicationService → PostgreSQL. Existing fingerprints are unchanged.
- CollectorState/CollectorRun use their existing timestamps, state, scheduling,
  duration, received/new/duplicate/cross-source/failed counters and retry lifecycle.
- Owner `/collect` dispatches six tasks. `/status` automatically lists The Muse
  with missing-state placeholders or persisted timestamps. `/stats` includes it
  through common catalogs and recorded runs, with no special statistics branch.
- `/filters` shows `filters:sources:the_muse` in both locales. Job cards attribute
  The Muse and open the source listing, not its API endpoint.
- Shared filter/scoring/digest behavior is unchanged; no source bonus or scoring
  weight changes were made.

Migration **c638e7a2910f**, following b927c64ed108, updates the database source
default and appends The Muse once to saved selections. This follows the project's
existing all-active-source expansion policy. Previously disabled older sources
stay disabled; other preferences and language are preserved. New users default
to all six sources. Downgrade refuses to empty a The Muse-only selection.

CLI using the real common collection service:

```bash
poetry run python -m src.scripts.collect_the_muse
```

## Live collection and duplicate audit

One real anonymous collection ran **2026-10-16 15:48:51–15:48:59 UTC** through
CollectionService in an isolated local PostgreSQL schema. It used the three-page
official API query, Redis lock, real normalization/dedup/persistence and state/run
repositories. The schema was removed after measurement.

The comparison used read-only projections of real production jobs collected in
the preceding 30 days: Remote OK 121, WWR 314, Get on Board 158, Himalayas 60,
Jobicy 99 (**752 total**). These reference records were copied into the isolated
schema; no production jobs, users, settings or services were modified. Live
results below are test-schema collection counts, not production insertions.

| Received | New | Duplicates | Cross-source duplicates | Failed | Duration |
| --- | --- | --- | --- | --- | --- |
| 60 | 60 | 0 | 0 | 0 | 8523 ms |

All five source comparisons had **zero exact fingerprint overlap (0%)**. No
duplicate examples exist in this sample. Real PostgreSQL tests separately verify
cross-source suppression against each of the five sources and repeat-collection
idempotency. No dedup changes were made to force matches.

Persisted state: success, last success `2026-10-16T15:48:59.587190Z`, no error;
next run `2026-10-16T22:33:24Z` (19:33:24 America/Montevideo), inside the scheduled
evening window. The matching CollectorRun contains the counters and duration above.

The first five received vacancies are listed below without descriptions.

| Source | Title | Company | Location | Remote | Experience |
| --- | --- | --- | --- | --- | --- |
| The Muse | Principal Technical Product Manager - Commerce (Billing & Monetization) | Atlassian | Bangalore, India, Flexible / Remote | Yes | senior |
| The Muse | Licensed Inside Sales Representative (Remote - Home Based Work) | Allstate | Dallas, TX, Flexible / Remote | Yes | middle |
| The Muse | Staff Controls Engineer- Ingénieur contrôleur ou ingénieure contrôleuse interne (Calgary/Montreal) | Equinix, Inc | Flexible / Remote, Gimli, Canada | Yes | senior |
| The Muse | Inside Auto Claims Specialist | Allstate | Flexible / Remote | Yes | middle |
| The Muse | Back-end Developer - Remote Internship | The Muse | Flexible / Remote | Yes | entry_level,_internship |

## Data completeness and category observations

Completeness covers all 60 received normalized jobs. Remote known is counted
from the explicit source marker, not merely from the non-null DTO bool. A named
city counts as location text but does not establish eligibility-region knowledge.
Experience known includes preserved multi-level labels, without choosing a level.

| Field | Known / total | Completeness |
| --- | --- | --- |
| Company | 60 / 60 | 100% |
| Remote Explicit | 60 / 60 | 100% |
| Region | 0 / 60 | 0% |
| Salary | 0 / 60 | 0% |
| Timezone | 0 / 60 | 0% |
| Technologies | 0 / 60 | 0% |
| Employment | 0 / 60 | 0% |
| Experience | 60 / 60 | 100% |

Company, location/remote marker and experience metadata are useful. Structured
salary, employment, technical skills and timezone requirements are unavailable
in this observed response. Description content is deliberately not mined to
populate them. All 60 live results are remote because of the explicit API query
and marker; non-remote/ambiguous handling is verified separately above and in tests.

Actual live categories and counts (some jobs have no category):

| Category | Jobs |
| --- | --- |
| Science and Engineering | 2 |
| Software Engineering | 8 |
| Sales | 1 |
| Account Management | 2 |
| Data and Analytics | 8 |
| Advertising and Marketing | 2 |
| Business Operations | 3 |
| Computer and IT | 2 |
| Legal Services | 1 |
| Software Engineer | 1 |

The only observed tag is Fortune 1000 (8 jobs), an employer-brand label rather
than a technical skill. Levels: Senior Level 41, Mid Level 19, Entry Level 1,
Internship 1; one job has two levels. Categories could be useful as a separate
future broad job-family field, especially for engineering/data selection, but
are not suitable as technologies. No DTO/category feature was introduced.

## Checks and production configuration

- `poetry run ruff check .`: passed.
- `poetry run black --check --workers 1 .`: passed.
- Full pytest with TEST_DATABASE_URL set to the dedicated local test database:
  **1216 passed**, including **57 real PostgreSQL integration cases**.
- `git diff --check`: passed.

Parser/HTTP tests use compact fixtures and HTTPX mock transport, without live
network. They cover all DTO fields, missing optionals, remote/city ambiguity,
levels, source-neutral scoring, both locales' source buttons/attribution,
pagination termination/limits, HTTP 401/403/429 and other errors, Retry-After,
timeouts, invalid JSON/schema, decompressed response size and key redaction in
HTTPX/httpcore logs. Existing Telegram sanitization tests remain green.
Integration tests migrate disposable schemas and verify each cross-source dedup
pair, repeat persistence, state/run/statistics, source defaults and migration
preservation/idempotency/downgrade safety. All previous collector tests remain green.

At the implementation handoff, deployment had not yet been requested. The VPS
was still running the previous Jobicy release. The subsequent deployment request
added the production key guard described above; server .env remains user-managed.
No Telegram commands/messages or digest were sent for this stage; /collect,
/status, /stats and /filters integration was tested locally. For production,
register an app and securely set THE_MUSE_API_KEY in the server .env, then apply
the source-default migration using the normal deployment process. Anonymous
access is available for testing but is not the provider's ongoing-use setup.
No API key value is included in this report.

## Files and Git state

New files: the collector, common HTTP log filter, thin CLI, source-default data
migration, parser/HTTP tests, compact fixture, PostgreSQL tests and this report.
Existing changes: source/task/config/policy registries, two shared experience
aliases, reuse of the common log filter by Telegram/JSON HTTP, documentation,
and source-list/dispatch/default expectations in existing tests. Complete paths
are included below. The working-tree snapshots below were captured before the later commit/push
request, at HEAD 555f99a. No subsequent source/product feature was started.

`git diff --stat` (tracked files only; eight new files are listed in status):

```text
 .env.example                                       |  4 +++
 README.md                                          |  4 +--
 docs/project-guide.md                              | 36 ++++++++++++++++++----
 src/bot/client.py                                  | 18 ++---------
 src/collectors/http.py                             |  3 ++
 src/collectors/registry.py                         |  2 ++
 src/config.py                                      |  8 ++++-
 src/services/collector_policy.py                   |  6 ++++
 src/services/normalization.py                      |  2 ++
 src/tasks/jobs.py                                  | 10 ++++++
 tests/bot/test_commands.py                         | 10 ++++--
 tests/integration/test_himalayas_postgres.py       |  3 +-
 tests/integration/test_jobicy_postgres.py          |  4 ++-
 .../test_persistent_filters_postgres.py            |  2 ++
 tests/integration/test_postgres_hardening.py       |  2 +-
 tests/services/test_scheduling.py                  | 29 ++++++++++++++++-
 tests/services/test_statistics.py                  |  1 +
 tests/services/test_user_filters.py                |  1 +
 tests/tasks/test_tasks.py                          |  2 ++
 19 files changed, 117 insertions(+), 30 deletions(-)
```

`git status --short --branch --untracked-files=all`:

```text
## main...origin/main
 M .env.example
 M README.md
 M docs/project-guide.md
 M src/bot/client.py
 M src/collectors/http.py
 M src/collectors/registry.py
 M src/config.py
 M src/services/collector_policy.py
 M src/services/normalization.py
 M src/tasks/jobs.py
 M tests/bot/test_commands.py
 M tests/integration/test_himalayas_postgres.py
 M tests/integration/test_jobicy_postgres.py
 M tests/integration/test_persistent_filters_postgres.py
 M tests/integration/test_postgres_hardening.py
 M tests/services/test_scheduling.py
 M tests/services/test_statistics.py
 M tests/services/test_user_filters.py
 M tests/tasks/test_tasks.py
?? docs/the-muse-stage-report.md
?? migrations/versions/c638e7a2910f_enable_the_muse_source.py
?? src/collectors/the_muse.py
?? src/logging_filters.py
?? src/scripts/collect_the_muse.py
?? tests/collectors/test_the_muse.py
?? tests/fixtures/the_muse/jobs.json
?? tests/integration/test_the_muse_postgres.py
```
