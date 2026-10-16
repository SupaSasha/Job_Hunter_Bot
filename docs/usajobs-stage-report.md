# USAJOBS collector

## Official API research

Checked October 16, 2026. Search endpoint:
`GET https://data.usajobs.gov/api/Search`. The
[authentication guide](https://developer.usajobs.gov/guides/authentication)
requires Host=data.usajobs.gov, User-Agent equal to the registration email and
Authorization-Key equal to the issued API key. Credentials are requested through
the [official application](https://developer.usajobs.gov/apirequest/).

The [search reference](https://developer.usajobs.gov/api-reference/get-api-search)
supports occupational series, remote filtering, DatePosted, opening-date sorting,
one-based Page and ResultsPerPage. Results have SearchResult counts and items,
each containing MatchedObjectId and MatchedObjectDescriptor. The descriptor
includes agency, position URL, locations, remuneration, publication/closing
dates and UserArea.Details. Fields=Full requests summary/eligibility metadata
within search; there is no per-job detail request.

The [search tutorial](https://developer.usajobs.gov/tutorials/search-jobs) identifies
series 2210 as Information Technology Management. This is the initial global
category; no user-specific calls or keyword expansion is needed. It does not
cover all engineering/data occupations. Search uses the default public access;
no Status/internal access is assumed.

The [published limits](https://developer.usajobs.gov/guides/rate-limiting) specify
500 rows/page and 10,000 rows/query. They do not specify a numeric public QPS or
daily key allowance. The collector uses much smaller bounds, spaces requests one
second apart and defers on 429 via shared Retry-After handling. No immediate retry
loop, scraping, Playwright or undocumented endpoint was introduced.

The public [remuneration codelist](https://developer.usajobs.gov/api-reference/get-codelist-remunerationrateintervalcodes)
was also requested without credentials and returned HTTP 200: PA=Per Year,
PH=Per Hour; other values include BW, FB, PD, PM, PW, ST, SY and WC. This verifies
reference codes, not authenticated search or a live job collection.

## Configuration and source integration

| Variable | Required/default |
| --- | --- |
| USAJOBS_API_KEY | Required secret; no default |
| USAJOBS_EMAIL | Required registration email; no default |
| USAJOBS_MAX_PAGES_PER_QUERY | Default 2; range 1–5 |
| USAJOBS_MAX_JOBS_PER_RUN | Default 100; range 1–500 |

Implementation adds only placeholders to .env.example. The user supplied the
local credentials before the live run; no agent edits to local/production .env
were made. Both credentials are hidden from Settings repr. Missing values or
invalid header characters raise CollectorConfigurationError before an HTTP
client is constructed. HTTP 401/403 identifies variable names to check, without
their values. Shared HTTP exceptions omit URLs, headers and response bodies.
HTTPX/httpcore diagnostics redact the configured key/email, including escaped
byte representations of headers. No credential is stored in this report.

Canonical source: usajobs. Display brand: USAJOBS in EN/ES. The registry contains
nine collectors; CollectionService provides the existing run/state lifecycle,
normalization, same-source/global dedup and PostgreSQL persistence. The collector
never accesses DB/repositories, user filters, scoring or Telegram.

- Class: src/collectors/usajobs.py, USAJobsCollector(BaseJobCollector).
- Interface: async collect() -> list[JobDTO].
- Parser helpers: parse_job and parse_page, independently testable without HTTP.
- Registry: src/collectors/registry.py.
- Celery task: jobs.collect_usajobs, thin common-task wrapper.
- Lock: collector:usajobs:lock, existing 660-second lease and ownership-safe release.
- Schedule: one jittered daily run in 15:00–16:00 America/Montevideo.
- Owner /collect dispatches all nine tasks; a source configuration failure does
  not stop the other independent collectors.
- /status includes USAJOBS and shows configuration required for a stored
  CollectorConfigurationError; the safe label is localized into EN/ES.
- /stats uses the existing CollectorRun counters/duration and quality statistics.
- /filters lists USAJOBS through the existing source keyboard, initially off.

**USAJOBS is default OFF** for existing/new users, including owner bootstrap and
reset. A generic policy default_enabled flag separates AVAILABLE_SOURCES from
DEFAULT_SOURCES. All eight prior sources retain their existing defaults. Current
saved selections remain untouched; enabling USAJOBS is explicit and does not
change exclude_us_only or other preferences. The SQL and ORM source defaults
remain unchanged, so **no Alembic migration was created**. Schema parity and raw
SQL/new-user/service defaults are checked against real PostgreSQL.

The existing keyboard supports brand labels but not source descriptions; no new
keyboard structure was needed. No source scoring bonus/penalty, special digest
logic or source-specific FilterService condition was added.

## Search and bounds

USAJOBS_CATEGORIES = ("2210",). Each request includes:

```text
JobCategoryCode=2210
RemoteIndicator=True
DatePosted=30
SortField=opendate
SortDirection=Desc
ResultsPerPage=50
Page=1, 2, ...
Fields=Full
```

Defaults make at most two requests, yielding at most 100 unique control numbers
per run. The response has an 8 MiB decompressed limit and existing HTTP timeout.
All category/page requests share the overall cap. Short pages, exhausted totals,
repeated pages without new eligible IDs and configured bounds stop pagination.
Closed-only pages can advance within the fixed page bound. Category pages are
interleaved if categories are extended later; queries are not changed by audits.

Repeated MatchedObjectId values are removed within the run before JobDTOs enter
the common pipeline. The existing source/external_id and 30-day cross-source
agency/title fingerprint checks remain enabled. The collector exposes safe
per-category counts and query_job_ids for external new-after-dedup audits. No
cursor or whole-catalog crawl was added.

## Mapping and interpretation

| JobDTO field | Mapping/limitations |
| --- | --- |
| source | usajobs |
| external_id | MatchedObjectId control number, not PositionID announcement label/hash |
| title | PositionTitle, HTML cleanup |
| company | OrganizationName, falling back to DepartmentName; otherwise None |
| url | PositionURI, validated official HTTPS USAJOBS host; not API/ApplyURI |
| description | JobSummary, else QualificationSummary; eligibility and explicit telework note; bounded 12,000 characters |
| location | Distinct PositionLocation.LocationName values, fallback PositionLocationDisplay; first five plus +N more |
| remote | Explicit Details.RemoteIndicator boolean/Yes/No when supplied; otherwise exact official remote location label (with or without the United States suffix); telework alone never suffices |
| remote_regions | us_only only for the explicit U.S. remote location or recognized unconditional citizenship statements; otherwise [] |
| employment_type | Single PositionSchedule code 1/2 → full_time/part_time |
| salary_min/max | Single valid nonnegative ordered integer-valued remuneration range; no conversion/rounding |
| currency | USD for a valid structured remuneration range |
| salary_period | PA → yearly, PH → hourly; other periods None |
| technologies | []: no structured technology list or description NLP |
| experience_level | None: federal grades do not establish conventional seniority |
| published_at | Offset-aware PublicationStartDate → UTC; undocumented naive values remain None |
| collected_at | Current UTC |
| timezone_text / minimum / maximum offset | All None; no inference from location |

The [official announcement help](https://help.usajobs.gov/how-to/job-announcement/overview)
distinguishes fully remote from telework/hybrid and identifies the remote location
label as Anywhere in the U.S. (remote job). That explicit geographical statement,
not the agency address, establishes us_only. Missing/ambiguous remote metadata
uses the legacy boolean False, meaning unconfirmed, not proof of office work.
Explicit false takes precedence over an inconsistent remote location label.

Exact unconditional citizen-only statements in WhoMayApply.Name, KeyRequirements
or Requirements can also establish us_only. Public hiring paths, U.S. cities,
security clearances and federal grades do not. Conditional/negated requirements
are not classified by substring matching. Other source eligibility text remains
in the description. us_only is an MVP eligibility exclusion marker, not a new
citizenship model. Existing region/exclude_us_only filters still apply after
opt-in; users may enable USAJOBS while retaining exclude_us_only=True.

Permanent, Term and Temporary are appointment-tenure concepts, not reliably
contract employment; they are not forced into contract. Multiple/intermittent
schedules remain unknown. Ambiguous/multiple salary ranges remain unknown.
The existing integer salary DTO cannot preserve cents, so fractional amounts
are deliberately not rounded. A valid range with unknown period keeps amounts
and USD; the existing DTO supports an unknown salary period.

The help page defines closing calendar dates through 11:59 p.m. Eastern Time.
Date-only/naive-midnight ApplicationCloseDate values are treated as the entire
closing day in America/New_York, with DST, and skipped after its end. Explicitly
offset-aware deadlines are compared as instants. Arbitrary naive non-midnight
deadlines have no verified timezone contract and are retained conservatively;
no server timezone is used. Invalid/absent deadlines do not cause false expiry.
Closed items are skipped, malformed items counted/logged generically, all-invalid
pages fail; a valid empty or closed-only page is not a schema failure.

## Live collection and usefulness audit

One authenticated manual collection succeeded on 2026-10-16 17:41:26
America/Montevideo. It used the user-supplied local credentials, the real Redis
lock, CollectionService, shared normalization/dedup and local PostgreSQL.
Production was not contacted and no Telegram message/digest was sent.

```text
status: success
configured category: 2210 (Information Technology Management)
configured remote filter: True
authenticated categories executed: 1
API requests: 1 (short page; no second request needed)
API results received: 1
unique USAJOBS jobs: 1
remote jobs: 1
telework-only jobs: 0
closed jobs skipped: 0
malformed jobs: 0
pipeline received: 1
new: 1
duplicates: 0
cross-source duplicates: 0
failed: 0
```

Persisted CollectorState and CollectorRun both report success. The local database
contained 373 jobs before collection and had revision 49f75b591334; no migration
was required or applied for the data-only audit. Duplicate rates describe this
local database only, not production overlap.

| Category | Requests | Received | Unique | Remote | New after global dedup |
| --- | --- | --- | --- | --- | --- |
| 2210 | 1 | 1 | 1 | 1 | 1 |

No repeated control numbers occurred inside this response. Pipeline same-source
duplicate rate: 0%; cross-source duplicate rate: 0%; new-unique rate: 100%.
These percentages have a denominator of one and do not establish the source's
long-term usefulness.

The API supplied an explicit remote flag and the location
`Anywhere in the U.S. (remote job), United States`. The country suffix exposed a
parser gap: the initial run confirmed remote but did not mark the location
us_only. The parser now recognizes this exact official label variant; regression
cases cover both variants and exclude_us_only after opt-in. The single audited
local row was corrected to remote_regions=["us_only"] in a transaction, without
another API request. The pipeline counts above remain those of the original
successful collection; quality/usefulness below describes the corrected record.

| Product usefulness, denominator 1 | Count | Rate |
| --- | --- | --- |
| Remote confirmed | 1 | 100% |
| Telework-only | 0 | 0% |
| Explicit U.S. restriction | 1 | 100% |
| Survives exclude_us_only alone | 0 | 0% |
| Survives all default filters | 0 | 0% |
| Survives default filters after source opt-in | 0 | 0% |

The U.S. restriction is geographical evidence, not a finding that only citizens
can apply. USAJOBS remains off by default. Enabling the source does not bypass
exclude_us_only or region filters. Search/category choices were not changed.

| Data completeness, denominator 1 | Known count | Rate |
| --- | --- | --- |
| Agency | 1 | 100% |
| Remote confirmed | 1 | 100% |
| Salary | 1 | 100% |
| Location | 1 | 100% |
| Employment type | 1 | 100% |
| Region/eligibility restriction | 1 | 100% |
| Structured technologies | 0 | 0% |
| Conventional experience | 0 | 0% |
| Timezone-aware publication date | 0 | 0% |

First results (one job returned; no additional four examples invented):

[USAJOBS] [Information Technology Specialist (Database Administrator)](https://www.usajobs.gov:443/job/888818100) —
Smithsonian Institution — Remote: Yes —
Anywhere in the U.S. (remote job), United States — USD 143,913–187,093/year.

Control number: 888818100. Employment: full_time. The official position
URL is retained, including its explicit :443 port; no job/detail page was fetched.
The response used integer result counts, a SearchResultItems list and the expected
descriptor/Details structure, including RemoteIndicator and TeleworkEligible.
Full response bodies, agency contact values and auth headers were not logged.

## Fixtures and example DTO

tests/fixtures/usajobs/search.json uses compact **authored**, documented-shape
values, not live observations: remote federal/citizen-only, office/hourly,
telework-only/multiple schedules, expired and minimal jobs. The live run confirmed
the search response/header contract and presence of
remote metadata for the single observed result; the other fixture variants remain
authored test cases, not live observations.

Example parsed fixture (not a real vacancy):

```json
{
  "source": "usajobs",
  "external_id": "800000001",
  "title": "Information Technology Specialist",
  "company": "Example Federal Agency",
  "description": "Build reliable public services & tools.\n\nEligibility: U.S. citizens only; You must be a U.S. citizen to apply for this job.\n\nTelework eligible: No",
  "url": "https://www.usajobs.gov/job/800000001",
  "location": "Anywhere in the U.S. (remote job)",
  "timezone_text": null,
  "timezone_min_utc_offset": null,
  "timezone_max_utc_offset": null,
  "remote": true,
  "remote_regions": [
    "us_only"
  ],
  "employment_type": "full_time",
  "salary_min": 80000,
  "salary_max": 120000,
  "currency": "USD",
  "salary_period": "yearly",
  "technologies": [],
  "experience_level": null,
  "published_at": "2026-10-15T12:00:00Z",
  "collected_at": "2026-10-16T12:00:00Z"
}
```

## Verification

Results are recorded below after the final checks. Coverage includes individual
DTO fields, agency fallback, official URLs and IDs, remote/telework distinctions,
citizenship exceptions, unknown optional fields, salary units/limits, ET/DST
closing dates, publication offsets, pagination/repeat/multi-category dedup/caps,
missing credentials before HTTP, safe logs including escaped headers, auth errors,
429/Retry-After, network/timeout, malformed JSON/schema and decompressed limits.

PostgreSQL cases exercise dedup against all eight existing sources, repeated
collection, state/run/statistics, real collector with mock HTTP through the common
pipeline, configuration-failure isolation, preserved selections, manual opt-in,
new-user SQL/ORM/service defaults and Alembic schema parity without a migration.
Both source-menu and configuration-status labels are checked in EN/ES. Existing
filter/scoring behavior and every older collector remain in the regression suite.

- `poetry run ruff check .`: passed.
- `poetry run black --check --workers 1 .`: passed, 181 files unchanged.
- Full pytest with TEST_DATABASE_URL set programmatically to the dedicated local
  job_hunter_review_test database: **1582 passed in 103.64 seconds**, including
  **87 real PostgreSQL integration cases**, with no skips/failures.
- The final full run includes the USAJOBS task wrapper and both remote-location
  regression cases added after the live audit.
- `git diff --check`: passed.

Integration fixtures create, migrate and remove isolated UUID schemas. No
application/production tables or user selections were used as test fixtures.
The public salary codelist request and the subsequent authenticated collection
both succeeded. The observed remote-location variant was corrected and tested.
No response/body or credential was logged. All source-contract fixtures are
authored, not claimed as live evidence.

## Files and repository state

Implementation starts at bd5baf5. Implementation and the local live audit were
completed before the user's subsequent commit/push/deployment request. Production
.env/volumes and Telegram messages were untouched during those checks. No new
source after USAJOBS or additional product feature is included.

Pre-commit snapshot (`git diff --stat`; six new files are listed below):

```text
 .env.example                        |  7 ++++++
 README.md                           |  2 ++
 docs/project-guide.md               | 50 +++++++++++++++++++++++++++++++++++++
 src/bot/commands.py                 |  6 +++++
 src/bot/filters.py                  |  4 +--
 src/collectors/registry.py          |  2 ++
 src/config.py                       |  6 +++++
 src/i18n/en.py                      |  1 +
 src/i18n/es.py                      |  1 +
 src/logging_filters.py              | 11 +++++++-
 src/models/user_filter.py           |  5 +++-
 src/services/collector_policy.py    |  8 ++++++
 src/services/user_filters.py        |  9 +++++--
 src/tasks/jobs.py                   | 10 ++++++++
 tests/bot/test_commands.py          | 24 +++++++++++++++++-
 tests/bot/test_job_filter_menu.py   | 12 +++++++++
 tests/services/test_scheduling.py   | 23 ++++++++++++++++-
 tests/services/test_statistics.py   |  1 +
 tests/services/test_user_filters.py | 11 ++++++++
 tests/tasks/test_tasks.py           |  2 ++
 20 files changed, 187 insertions(+), 8 deletions(-)
```

Pre-commit `git status --short --branch --untracked-files=all`:

```text
## main...origin/main
 M .env.example
 M README.md
 M docs/project-guide.md
 M src/bot/commands.py
 M src/bot/filters.py
 M src/collectors/registry.py
 M src/config.py
 M src/i18n/en.py
 M src/i18n/es.py
 M src/logging_filters.py
 M src/models/user_filter.py
 M src/services/collector_policy.py
 M src/services/user_filters.py
 M src/tasks/jobs.py
 M tests/bot/test_commands.py
 M tests/bot/test_job_filter_menu.py
 M tests/services/test_scheduling.py
 M tests/services/test_statistics.py
 M tests/services/test_user_filters.py
 M tests/tasks/test_tasks.py
?? docs/usajobs-stage-report.md
?? src/collectors/usajobs.py
?? src/scripts/collect_usajobs.py
?? tests/collectors/test_usajobs.py
?? tests/fixtures/usajobs/search.json
?? tests/integration/test_usajobs_postgres.py
```
