# Jooble collector

## Verified contract and authentication

Verified October 16, 2026 against the [official REST API documentation](https://help.jooble.org/en/support/solutions/articles/60001448238-rest-api-documentation),
[connection guide](https://help.jooble.org/en/support/solutions/articles/60000922689-how-to-connect-to-the-jooble-rest-api-after-receiving-the-key)
and [API registration portal](https://jooble.org/api/about).

Endpoint: `POST https://<regional-domain>/api/<API_KEY>`, with application/json.
The API key is a URL path credential, not a Bearer header or body field.
The documented response is `{totalCount, jobs: [...]}`; job fields are id, title,
location, snippet, salary, source, type, link, company and updated.

The key is country/domain-specific. `jooble.org` covers US jobs; UK and Germany
use their own regional domains/keys, for example uk.jooble.org and de.jooble.org.
One key is not global access. This implementation supports one explicitly chosen
domain and location, not a multi-country key manager. Domains are validated as
jooble.org or a two-letter regional Jooble subdomain; arbitrary hosts, credentials,
paths and complete URLs are rejected to avoid misdirecting the key.

The free plan has **500 requests per key over its lifetime**, not per month.
No additional public request-rate/paid allowance is assumed. Defaults make at
most two requests/run and four/day with successful twice-daily scheduled runs;
manual collection and existing failure retries can consume additional quota.
Requests are spaced one second apart, and 429 honors the shared Retry-After
defer mechanism rather than retrying immediately.

### Configuration

| Variable | Purpose / default |
| --- | --- |
| JOOBLE_API_KEY | Required domain-specific secret; empty/unconfigured by default |
| JOOBLE_API_DOMAIN | Required issuing regional domain; selected US configuration: jooble.org |
| JOOBLE_SEARCH_LOCATION | Required explicit location; selected US configuration: United States |
| JOOBLE_MAX_PAGES_PER_QUERY | Default 1, permitted 1–3 |
| JOOBLE_MAX_JOBS_PER_RUN | Default 40, permitted 1–200 |

Required fields and bounded settings are documented in .env.example. The
key is hidden from Settings repr, percent-encoded as one path segment, and
redacted in HTTPX and httpcore diagnostics, including relative request targets.
Raw response bodies, exception URLs and credentials are not logged.

**Selected market: US**, as confirmed by the user. Local .env and .env.example
use `JOOBLE_API_DOMAIN=jooble.org` and `JOOBLE_SEARCH_LOCATION=United States`.
The user supplied a local key, and a bounded live run succeeded for this market.
The examples below use authored UK-domain fixtures for tests; they do not
establish actual key access or represent the selected live market.
Production .env was not changed.

## Search, pagination and limits

Global constant `JOOBLE_SEARCH_QUERIES = ("software", "developer")` provides two
broad tech queries. There are no Python-only or per-user requests. The official
contract requires keywords and location; it does not document a dedicated remote
filter, publication watermark or newest-first sorting. SearchMode's undocumented
semantics are not guessed. Consequently these are bounded initial relevance
pages from the selected market, not a guaranteed newest/remote-only pool.

Each request includes keywords, configured location, one-based page,
ResultOnPage=20 and companysearch=False. Pages are interleaved between queries,
so one query does not consume all default capacity first. Collection stops per
query on empty/short pages, totalCount exhaustion or no new source IDs. The
configured page limit and overall unique-job cap also stop requests. A provider
response ignoring ResultOnPage still cannot exceed the returned-job cap.

Exact repeated Jooble IDs across pages/queries are removed before returning
JobDTOs. This does not replace the existing PostgreSQL same-source or 30-day
cross-source fingerprint dedup. No fingerprint, scoring bonus or weights changed.

The shared bounded JSON helper now accepts POST/JSON in addition to its existing
GET behavior. All existing clients retain GET defaults, response limits, sanitized
errors and Retry-After behavior. Each response has an 8 MiB decompressed cap.
Timeouts, network failures, HTTP errors, invalid JSON/schema and all-invalid
pages fail explicitly. HTTP 401/403 identifies the key/domain/quota configuration
to check without exposing the credential. There is no scraping, redirect bypass,
job-page request or aggressive retry loop.

## Public API and field mapping

`JoobleCollector(*, timeout=None, max_pages=None, max_jobs=None)` implements
`async collect() -> list[JobDTO]`. Network-independent helpers are
`parse_job(raw, *, collected_at=None)` and `parse_page(payload)`.
The collector handles only source HTTP/parsing, with no DB, repository,
filtering, scoring, Telegram or global dedup calls.

| Source | JobDTO handling |
| --- | --- |
| id | Stable integer ID to string; no positivity assumption, UUID or fingerprint fallback |
| title, company | title/company, shared HTML cleanup; absent company stays None |
| snippet | Plain description via existing HTML-to-text helper; no full-page enrichment |
| link | Official provided HTTP(S) navigation URL, unchanged; no redirect traversal |
| location | location text; only exact Remote, Remote job or Work from home establish remote=True |
| type | employment_type through shared normalization |
| salary | Conservative shared string parser, no currency/period conversion |
| updated | Aware update timestamp normalized to UTC, stored in existing published_at field |
| UTC collection clock | collected_at |

The upstream source label does not replace canonical jooble. The documented link
is a Jooble listing; original employer/board or redirect links are also preserved
if the API supplies them. All 39 unique jobs in the live sample supplied
`https://jooble.org/jdp/<id>` links. No link was dereferenced to work around
attribution/redirects, so downstream redirect behavior remains unverified.

The contract has no explicit eligibility regions, timezone restrictions,
structured skills or seniority. Accordingly remote_regions=[], technologies=[],
experience_level=None and all three timezone fields None. A city/country is not
us_only or worldwide. Search keywords, title and snippets never infer remote,
technologies or experience. The legacy bool DTO stores unconfirmed remote as
False; a city alone does not prove an office-only restriction.

Only updated, not original publication time, is documented. The existing date
field retains an aware upstream update timestamp without claiming it is original
publication. The documented naive example and date-only strings remain None:
neither market nor server timezone is guessed. Tests cover this choice explicitly.

### Salary reuse and uncertainty

HN's existing small salary parser was extracted into src/collectors/salary.py.
HN uses its original text mode unchanged. Jooble uses an exact full-field mode
which also accepts documented suffix-currency forms such as `17,600 UAH`, with
currency known and period unknown. Explicit USD ranges/year or GBP/hour are
accepted without conversion. A bare dollar symbol, ambiguous separators/scales,
extra compensation prose, conflicting ranges and unsupported fractional amounts
remain entirely unknown. No annual/hourly period is inferred from amount size.
There is no salary regex over the Jooble snippet.

## Shared application integration

- Canonical source/display: jooble / Jooble in both English and Spanish.
- Registry: src/collectors/registry.py; source/display/schedule policy:
  src/services/collector_policy.py.
- Celery task: jobs.collect_jooble, a thin common collection wrapper.
- Redis lock: collector:jooble:lock, using the existing lock lifecycle.
- Windows: **09:00–10:00 and 21:00–22:00 America/Montevideo** with the existing
  persisted jitter (SCHEDULER_TIMEZONE remains configurable).
- Common pipeline: JobDTO → NormalizationService → JobPipeline/JobSaveService →
  DeduplicationService → PostgreSQL. Common digest/filter/scoring logic is reused.
- Existing CollectorState and CollectorRun retain status, timestamps, next run,
  duration and received/new/duplicate/cross-source/failed counters.
- Missing key, domain or location raises CollectorConfigurationError before HTTP.
  The common service records a failed/configuration run and retry state; separate
  collectors continue normally. It is not reported as a successful empty run.
- Owner /collect dispatches eight tasks. /status and /stats discover Jooble through
  common catalogs and persisted state/runs, without source-specific handlers.
- /filters includes filters:sources:jooble in both locales; job cards attribute
  Jooble and open the API-provided listing link.

Migration **e85ab9c12460**, after d749a8b3e205, appends Jooble once to saved source
selections and updates the server default. This follows the current all-active
expansion policy. Disabled older sources, language and other preferences remain
unchanged; new users default to all eight. Downgrade refuses to empty a Jooble-only
selection. No other schema fields or Jooble-specific metrics subsystem was added.

CLI using the common service:

```bash
poetry run python -m src.scripts.collect_jooble
```

## Live run and metrics

```text
status: success
run started: 2026-10-16 17:06:15 America/Montevideo (20:06:15 UTC)
market configured: United States / jooble.org
market/domain used for live requests: United States / jooble.org
queries configured: software, developer
queries executed: 2 (one page/request each)
API results received: 40
unique Jooble jobs: 39
pipeline received: 39
new: 39
duplicates: 0
cross-source duplicates: 0
failed: 0
```

This was one manual collection through CollectionService, the real Redis lock,
shared normalization/dedup and local PostgreSQL. The existing database contained
334 jobs before collection and had revision 49f75b591334. No migration or user
filter update was needed or performed for this data-only audit. Production was
not contacted. Fixtures remain authored examples, separate from this live sample.

| Query | API results | Unique IDs | New after global dedup |
| --- | --- | --- | --- |
| software | 20 | 20 | 20 |
| developer | 20 | 20 | 20 |

One ID appeared in both queries. It was removed inside the collector: 1/40,
or **2.5% of raw API results**. The software query contributed 20 unique jobs;
developer contributed another 19. Per-query new counts overlap on the shared ID
and therefore do not sum to the pipeline's total.

Using the 39 jobs entering the global pipeline as the denominator:

| Global dedup outcome | Count | Rate |
| --- | --- | --- |
| Exact same-source duplicates already in the database | 0 | 0% |
| Cross-source duplicates | 0 | 0% |
| New unique jobs | 39 | 100% |

These rates describe this local database/sample only. They do not measure
overlap with production or establish future novelty or usefulness for remote
digests. In particular, none of these jobs had an explicit remote location label.
No automatic query changes or additional quota-consuming verification runs were
made.

Data completeness after shared normalization, denominator 39:

| Field | Known count | Rate |
| --- | --- | --- |
| Company | 39 | 100% |
| Remote confirmed by explicit location | 0 | 0% |
| Remote eligibility region | 0 | 0% |
| Salary parsed reliably | 0 | 0% |
| Timezone restrictions | 0 | 0% |
| Structured technologies | 0 | 0% |
| Employment type | 8 | 20.51% |
| Structured experience level | 0 | 0% |
| Timezone-aware update timestamp | 0 | 0% |

Remote false means unconfirmed in the legacy bool DTO; it does not prove an
office requirement. Unknown salary/date values are intentionally retained as
unknown under the conservative parsing rules, without currency/timezone guesses.

First five live jobs (links supplied by the API, not followed):

| Title | Company | Location | Jooble ID / link |
| --- | --- | --- | --- |
| Senior Software Engineer | HAN Staffing | Iselin, NJ | [701956784598919890](https://jooble.org/jdp/701956784598919890) |
| SME Software Engineer | VTG | Chantilly, Loudoun County, VA | [-5221319851151593904](https://jooble.org/jdp/-5221319851151593904) |
| Software Engineering PMTS | Salesforce | San Francisco, CA | [177541253903744994](https://jooble.org/jdp/177541253903744994) |
| Staff Software Engineer - ITAM | ServiceNow | Santa Clara, CA | [-5004698227669561312](https://jooble.org/jdp/-5004698227669561312) |
| Engineering - SRE - Site Reliability Engineer - Senior | Mindlance | Austin, TX | [-884478050876115519](https://jooble.org/jdp/-884478050876115519) |

Collector diagnostics expose safe per-query requests/received/unique/contributed
counts plus query_job_ids. A live audit can intersect returned IDs with newly
inserted run IDs outside the collector for per-query new-after-global-dedup;
overlapping queries can share that metric, while contributed counts show marginal
collector contributions. No DB access was added to the collector for attribution.

An actual collector + mocked HTTP + real PostgreSQL test demonstrates the audit
mechanics: both queries receive 2 results, 4 API results become 3 unique Jooble
jobs, global dedup yields 2 new and 1 cross-source duplicate, and each query finds
one newly inserted ID. This is a test result, not production/live effectiveness.

## Validation

All checks passed:

- `poetry run ruff check .`.
- `poetry run black --check --workers 1 .`: 177 files unchanged.
- Full pytest with TEST_DATABASE_URL pointing to the dedicated local
  job_hunter_review_test database: **1465 passed in 89.14 seconds**, including
  **76 real PostgreSQL integration cases**.
- `git diff --check`.

The PostgreSQL fixture migrates and removes isolated schemas. No production
fixtures or user settings were changed. Parser/HTTP tests cover documented DTO
mapping, missing optionals, employment, naive/aware dates, conservative salary,
remote/location distinctions, signed IDs, returned URLs, multi-query ID dedup,
round-robin/end/no-progress limits and overall caps, JSON POST/auth, missing
config, domain validation, 401/403/429/other HTTP, Retry-After, invalid JSON/schema,
network/timeouts, decompressed response limits and secret-path redaction.
Both locales' source UI/card attribution and source-neutral scoring are tested.
Integration cases verify cross-source dedup against all seven existing sources,
repeat idempotency, configuration-failure state and continued operation of another
collector, per-query audit mechanics, safe migration/defaults/downgrade and schema
parity. Existing HN salary behavior and Telegram/The Muse log redaction remain
covered by the full regression suite.

Implementation and the live audit were completed before the user's subsequent
commit/push request. No deployment was requested or performed. The
server continues running the previous seven-source release; production .env and
volumes were untouched. No Telegram messages or automatic digest were sent.
The local US key is configured and validated by this live run. To enable Jooble
on the server, set all three required variables in production as part of the
existing migration/deployment process. No API key is stored
in source control or this report.

## Example normalized JobDTO

Authored fixture example, not a real/live vacancy:

```json
{
  "source": "jooble",
  "external_id": "123",
  "title": "Senior Software Engineer",
  "company": "Acme & Co",
  "description": "Build useful software & APIs.",
  "url": "https://uk.jooble.org/jdp/123",
  "location": "Remote",
  "timezone_text": null,
  "timezone_min_utc_offset": null,
  "timezone_max_utc_offset": null,
  "remote": true,
  "remote_regions": [],
  "employment_type": "full_time",
  "salary_min": 120000,
  "salary_max": 160000,
  "currency": "USD",
  "salary_period": "yearly",
  "technologies": [],
  "experience_level": null,
  "published_at": "2026-10-16T09:30:00Z",
  "collected_at": "2026-10-16T18:33:59.190559Z"
}
```

## Files and working tree

New files are the Jooble collector, shared salary helper, thin CLI, source-default
migration, compact documented-shape fixture, parser/HTTP tests, PostgreSQL tests
and this report. Existing changes extend the shared JSON helper to POST, redact
path credentials, define a named configuration error, add settings/placeholders,
register Jooble, and update eight-source UI/task/schedule/default expectations
and docs. HN now imports the shared salary helper with unchanged default parsing.
Full paths follow in git status.

Pre-commit `git diff --stat` snapshot (tracked files only; eight new files follow
in status):

```text
 .env.example                                       |  9 +++++
 README.md                                          |  6 ++-
 docs/project-guide.md                              | 45 +++++++++++++++++++---
 src/collectors/base.py                             |  4 ++
 src/collectors/hacker_news.py                      | 42 ++-------------------
 src/collectors/http.py                             |  7 +++-
 src/collectors/registry.py                         |  2 +
 src/config.py                                      | 21 +++++++++++
 src/logging_filters.py                             |  7 ++++
 src/services/collector_policy.py                   |  6 +++
 src/tasks/jobs.py                                  | 10 +++++
 tests/bot/test_commands.py                         |  4 +-
 tests/integration/test_hacker_news_postgres.py     |  8 ++--
 tests/integration/test_himalayas_postgres.py       |  2 +
 tests/integration/test_jobicy_postgres.py          | 10 ++++-
 .../test_persistent_filters_postgres.py            |  2 +
 tests/integration/test_postgres_hardening.py       |  2 +-
 tests/integration/test_the_muse_postgres.py        |  8 ++--
 tests/services/test_scheduling.py                  | 28 +++++++++++++-
 tests/services/test_statistics.py                  |  1 +
 tests/services/test_user_filters.py                |  1 +
 tests/tasks/test_tasks.py                          |  2 +
 22 files changed, 168 insertions(+), 59 deletions(-)
```

Pre-commit `git status --short --branch --untracked-files=all` snapshot:

```text
## main...origin/main
 M .env.example
 M README.md
 M docs/project-guide.md
 M src/collectors/base.py
 M src/collectors/hacker_news.py
 M src/collectors/http.py
 M src/collectors/registry.py
 M src/config.py
 M src/logging_filters.py
 M src/services/collector_policy.py
 M src/tasks/jobs.py
 M tests/bot/test_commands.py
 M tests/integration/test_hacker_news_postgres.py
 M tests/integration/test_himalayas_postgres.py
 M tests/integration/test_jobicy_postgres.py
 M tests/integration/test_persistent_filters_postgres.py
 M tests/integration/test_postgres_hardening.py
 M tests/integration/test_the_muse_postgres.py
 M tests/services/test_scheduling.py
 M tests/services/test_statistics.py
 M tests/services/test_user_filters.py
 M tests/tasks/test_tasks.py
?? docs/jooble-stage-report.md
?? migrations/versions/e85ab9c12460_enable_jooble_source.py
?? src/collectors/jooble.py
?? src/collectors/salary.py
?? src/scripts/collect_jooble.py
?? tests/collectors/test_jooble.py
?? tests/fixtures/jooble/jobs.json
?? tests/integration/test_jooble_postgres.py
```

At the snapshot, HEAD was 6f9a7d5, in sync with origin/main, and stage changes
were unstaged and uncommitted. No USAJOBS, next collector or additional product
feature was added.
