# Hacker News — Who is hiring?

> October 25, 2026 update: Role recognition now covers deterministic non-tech patterns including customer success, talent acquisition, project management, legal, copywriting and consulting. Unrecognized hiring comments retain a generic title. Non-tech skill text extraction is supported. See [universal matching report](universal-matching-report.md). Earlier live-run details below are historical.

> Historical snapshot verified October 16, 2026. Scoring was subsequently
> changed to use recipient filters only; statements below about unchanged
> scoring weights describe the earlier implementation stage.

## API verification and thread discovery

Verified October 16, 2026 against the [official Algolia HN API reference](https://hn.algolia.com/api),
the [official HN item model](https://github.com/HackerNews/API), and real JSON.
The collector uses HTTPS public Algolia endpoints, without an API key:

- `GET https://hn.algolia.com/api/v1/search_by_date`
- `GET https://hn.algolia.com/api/v1/items/<thread_id>`

Discovery searches Ask HN: Who is hiring? with `tags=story,author_whoishiring`,
`hitsPerPage=10` and a documented created_at_i lower bound at the start of the
previous UTC month. Search is bounded to recent posts by the official author.
Exact current-month title wins; if missing, only the previous month is eligible,
including December/January rollover. Author, story tag, numeric ID and publication
month are checked. A generic hiring/Who wants to be hired/freelancer thread is
not accepted. No story ID is hardcoded in runtime code.

The verified current thread is **Ask HN: Who is hiring? (October 2026)**,
ID **49922569**, [canonical story](https://news.ycombinator.com/item?id=49922569).
The discovery response includes hits with objectID, title, author, created_at
and tags. The item response contains id, type, title, author, parent_id and
children. Its 480,951-byte observed response has **266 direct children**; the
larger total comment count also includes replies.

One item request supplies the tree. The parser visits only root.children and
requires each accepted comment's parent_id to equal the thread ID. Embedded
reply trees are ignored, not recursively fetched or converted to jobs. A normal
sync makes two sequential requests; there is no global HN crawl, pagination
loop, per-comment HTTP request or per-user query. Repeated syncs reuse stable
comment IDs and the existing dedup pipeline.

The reference documents 10,000 requests/hour/IP. Daily bounded collection is far
below that limit. Existing JSON transport enforces an 8 MiB decompressed limit,
timeouts, sanitized HTTP/network/JSON errors and Retry-After deferral on 429,
without aggressive retries, scraping, proxies or browser automation.

## Public API and parser boundaries

`HackerNewsCollector(*, timeout=None)` implements
`async collect() -> list[JobDTO]`. Its last_report contains only thread metadata
and counts for the manual audit. There are no DB, repository, filter, scoring,
dedup or Telegram calls in the collector.

Independent helpers include `thread_titles(now)`, `find_thread(payload, now)`,
`parse_comment(raw, *, thread_id, collected_at=None) -> JobDTO | None`,
`parse_thread(payload, *, thread_id, title)`, and small extraction functions.
No HN-specific fields or new DTO/schema were introduced.

- **Identity/link/date:** positive comment ID becomes external_id; url is
  `https://news.ycombinator.com/item?id=<comment_id>`. Publication uses the aware
  source created_at timestamp; collected_at is current UTC. Invalid/naive dates
  remain unknown rather than receiving fabricated timestamps.
- **Description:** the existing HTML-to-text helper decodes entities and preserves
  text lines. No raw thread dump or giant comment bodies are logged.
- **Company/title:** a bounded, recognizable first field before a pipe supplies
  company, with URLs removed and company parentheses preserved. Clear roles in
  the first header or a short second line supply the title. Multiple distinct
  header roles or explicit role lists produce one Multiple roles entry. Missing
  roles use Job opening. The full description never becomes the title.
- **Intent/noise:** deleted/dead/empty entries, replies, job seekers, obvious
  thread instructions and unstructured discussion without hiring/header evidence
  are skipped. Malformed entries log only a numeric comment ID and exception
  class. Completely malformed thread structures fail instead of looking empty.
- **Remote:** explicit header Remote gives True; onsite, hybrid and negative
  remote markers give False. Missing evidence uses the project's existing False
  default, which cannot distinguish unknown from non-remote. The audit separately
  counts explicit evidence. Hybrid is not represented as fully remote.
- **Geography:** only explicit listed eligibility labels are retained for a
  remote-marked header. Bare Remote does not become worldwide. City/company HQ
  and timezone labels are not eligibility. No geography hierarchy was added;
  unknown location remains None and regions remain [].
- **Timezone:** explicit UTC/GMT labels or uppercase timezone abbreviations are
  retained from header metadata. Numeric interpretation uses the existing
  NormalizationService parser. Fractions/ambiguous abbreviations retain text
  without guessed integer bounds. Discrete offsets use the existing offsets-list
  notation, avoiding a false continuous range. Locations never imply timezone.
- **Employment/experience:** explicit header employment goes through common
  aliases. A single recognizable role can supply seniority; multi-role or
  conflicting values remain None. Shared scoring weights are unchanged.
- **Technologies:** token matching uses the existing technical vocabulary and
  aliases, followed by common normalization. URLs/email addresses are excluded;
  short ambiguous Go/C/JS/TS require explicit casing. General job-family labels
  are excluded. This is a deterministic heuristic, not semantic NLP: ordinary
  uses of vocabulary words can still be ambiguous.
- **Salary:** a small parser accepts a single clear prefixed numeric amount/range,
  k suffixes and comma separators. Multiple ranges, conflicting scales, reversed
  bounds and fractional amounts that cannot fit the integer DTO stay unknown.
  Currency requires an explicit ISO marker or an unambiguous currency symbol;
  a bare dollar sign does not establish USD. Hourly/yearly requires an explicit
  suffix. There is no period/currency conversion or annual assumption.

Parsing intentionally favors unknown values over guesses. It does not split a
company's multi-role post into synthetic vacancies or choose an arbitrary role's
salary/seniority. These limits are included in the completeness audit below.

## Example normalized JobDTO

Authored compact fixture example, not a production vacancy:

```json
{
  "source": "hacker_news",
  "external_id": "49922584",
  "title": "Senior Backend Engineer",
  "company": "Acme & Co",
  "description": "Acme & Co | Senior Backend Engineer | Remote | LATAM | Full-time | UTC-5 to UTC+1 | USD 120k–160k/year\nStack: Python / FastAPI / PostgreSQL / Redis / Docker. We are hiring.",
  "url": "https://news.ycombinator.com/item?id=49922584",
  "location": null,
  "timezone_text": "UTC-5 to UTC+1",
  "timezone_min_utc_offset": -5,
  "timezone_max_utc_offset": 1,
  "remote": true,
  "remote_regions": [
    "latam"
  ],
  "employment_type": "full_time",
  "salary_min": 120000,
  "salary_max": 160000,
  "currency": "USD",
  "salary_period": "yearly",
  "technologies": [
    "docker",
    "fastapi",
    "postgresql",
    "python",
    "redis"
  ],
  "experience_level": "senior",
  "published_at": "2026-10-01T15:02:37Z",
  "collected_at": "2026-10-16T16:35:05.035613Z"
}
```

## Shared application integration

- Canonical source: `hacker_news`; display name: Hacker News in EN and ES.
- Registry: `src/collectors/registry.py`; source/display policy:
  `src/services/collector_policy.py`.
- Schedule: **13:00–14:00 America/Montevideo**, once daily with existing persisted
  jitter (SCHEDULER_TIMEZONE remains configurable). No early-month special policy.
- Redis lock: `collector:hacker_news:lock`, using the common lock lifecycle.
- Celery task: `jobs.collect_hacker_news`, a thin common collection wrapper.
- Pipeline: JobDTO → NormalizationService → JobPipeline/JobSaveService → existing
  DeduplicationService → PostgreSQL. Fingerprints and source bonuses are unchanged.
- CollectorState/CollectorRun retain the existing state, timestamps, retry,
  schedule, duration and all collection counters.
- Owner `/collect` publishes seven independent tasks. `/status` and `/stats`
  discover Hacker News through the common catalogs and persisted state/runs.
- `/filters` includes `filters:sources:hacker_news` in both languages. Job cards
  credit Hacker News and open the canonical comment URL. Shared digest/filter/
  scoring behavior remains unchanged.

Migration **d749a8b3e205**, following c638e7a2910f, appends Hacker News once to
saved source selections and updates the source default, following the project's
all-active-source expansion policy. Previously disabled older sources and other
preferences stay unchanged. New users default to all seven sources. Downgrade
refuses to empty a Hacker News-only selection.

Manual CLI, using the existing pipeline and lock:

```bash
poetry run python -m src.scripts.collect_hacker_news
```

## Validation and live production audit

All checks passed: `poetry run ruff check .`,
`poetry run black --check --workers 1 .`, and the full pytest suite with
TEST_DATABASE_URL set to the dedicated local database: **1341 passed in 77.37
seconds**, including **65 real PostgreSQL integration cases**. Disposable schemas
are migrated and removed; production fixture jobs are never inserted.

Coverage includes current/previous thread detection and year rollover, strict
story/author validation, direct children versus replies, deterministic parsing,
unknowns, HTML entities, multi-role/noise/deleted cases, transport failures and
size limits, Retry-After, both locales, source-neutral scoring, seven-task dispatch
and scheduling. PostgreSQL tests verify dedup against each of the six sources,
repeat idempotency, state/runs/statistics, migration preservation/defaults, and
safe downgrade. Existing collector and bot tests remain green.

No commit or push is made for this stage.

### Deployment

A validated custom-format PostgreSQL backup was created at
`/opt/job_hunter_bot/backups/pre-hacker-news-1a292de/database.dump` (about 1.5 MiB,
mode 0600 in a 0700 directory). The existing deployment script transferred the
uncommitted source, built the image, applied migration d749a8b3e205 and restarted
application services. All six services remain running; API/worker/database/Redis
health checks passed. /health returns status=ok.
The server .env checksum matches its predeployment snapshot; the configured
The Muse key remains present. Persistent volumes were preserved.

### Live collection

One real production CollectionService run completed on October 16, 2026 at
16:35 UTC. It used the existing Redis lock, common normalization/dedup/storage,
CollectorRun and CollectorState. No test fixture jobs were inserted.

| Top-level comments | Jobs parsed | Ignored | Multi-role | Ambiguous |
| --- | --- | --- | --- | --- |
| 266 | 245 | 21 | 44 | 94 |

| Received | New | Duplicates | Cross-source duplicates | Failed |
| --- | --- | --- | --- | --- |
| 245 | 245 | 0 | 0 | 0 |

Multi-role comments are **17.96%** of parsed entries.
Ambiguous comments are **38.37%**. Ambiguous means
missing confident company or remote evidence, or a generic Job opening title;
these categories can overlap with multi-role entries. The ambiguity rate is
material and intentionally documented rather than addressed with increasingly
aggressive patterns. Ignored comments include absent/unsupported job structure
and obvious noise; the parser does not claim perfect spam classification.

The first five parsed entries, before any deduplication (— means unknown):

| Source | Company | Title | Region | Remote | Technologies |
| --- | --- | --- | --- | --- | --- |
| Hacker News | — | Full-Stack Software Engineer | — | Yes | aws, nodejs, postgresql, react, typescript |
| Hacker News | Shepherd (Series B) | Job opening | — | No / unconfirmed | nodejs, postgresql, react, redis, typescript |
| Hacker News | Sidekick Labs | Multiple roles | — | Yes | go, python |
| Hacker News | Open Education Applications / Neon | Multiple roles | — | No / unconfirmed | kubernetes, postgresql, python, react, typescript |
| Hacker News | PAGNOS | Cloud Engineer | — | Yes | aws, nodejs, react, typescript |

The first PrairieLearn comment does not use a pipe-delimited company field, so
company is deliberately unknown. Shepherd preserves its explicit Series B
parenthetical text; it has a generic title because no role is confidently
identified in its initial header. Sidekick Labs and Open Education Applications
remain one entry each for multiple roles. PAGNOS has one Cloud Engineer entry,
without treating generic mentions of developers in prose as additional roles.

### Data completeness

The denominator is all 245 parsed jobs. Title known requires a concrete role,
excluding Job opening and Multiple roles. Remote known requires explicit positive
or negative header evidence, not simply a non-null bool. Region known means at
least one recognized explicit label, not complete worldwide eligibility. Salary
known means a positive parsed numeric minimum or maximum. Timezone known includes
explicit text even when numeric offsets cannot be safely represented.

| Field | Known / total | Completeness |
| --- | --- | --- |
| Company | 233 / 245 | 95.1% |
| Title | 123 / 245 | 50.2% |
| Remote | 229 / 245 | 93.47% |
| Region | 43 / 245 | 17.55% |
| Salary | 50 / 245 | 20.41% |
| Timezone | 14 / 245 | 5.71% |
| Technologies | 135 / 245 | 55.1% |
| Employment | 169 / 245 | 68.98% |
| Experience | 42 / 245 | 17.14% |

There are 119 remote=True entries, 110 explicit negative/onsite/hybrid entries,
and 16 with unknown workplace evidence (stored as False under the legacy DTO).
Only 9 of the 50 salary-bearing entries have an explicit identified currency;
the rest retain unknown currency rather than assuming USD. Multi-role salaries
and seniority are intentionally withheld. Technologies are vocabulary matches,
not a manual semantic audit of all comments.

### Cross-source duplicate audit

The live batch was compared with stored Remote OK, We Work Remotely,
Get on Board, Himalayas, Jobicy and The Muse jobs collected within the existing
30-day fingerprint window. All six comparisons had **0 exact matches (0%)**.
No live duplicate examples exist in this sample. Different title formats,
generic/multiple-role headings and company parentheticals can hide real-world
overlap; no claim of zero underlying overlap is made. Fingerprints were not
changed to force matches. Real PostgreSQL tests verify duplicate suppression
against each of the six sources and repeat-collection idempotency.

### Postdeployment owner commands

The real command handler was invoked with the configured owner's private-chat
identity and delivered replies to that owner through Telegram. This verifies
handler, delivery and worker integration, not a newly received incoming polling
update. The existing single polling service continues running.

- `/status`: Telegram message 226 lists Hacker News, last success and next run.
- Owner `/collect`: message 227 confirms dispatch; all seven real Celery tasks
  completed successfully. Hacker News was received and succeeded in worker logs.
- `/stats`: message 228 includes Hacker News with two successful runs: received
  490, new 245, duplicates 245, cross-source 0, failed jobs 0. These totals match
  persisted CollectorRun records.
- The second Hacker News run received the same 245 jobs, inserted zero and
  classified all 245 as duplicates, demonstrating repeat idempotency live.
- Both existing filter profiles include hacker_news, and the database default
  includes all seven sources. EN/ES filter buttons and attribution are tested.
- No digest was automatically invoked. Server environment and the existing
  The Muse key were preserved; worker logs do not expose that key.

| Source | Received | New | Duplicates | Cross-source duplicates | Failed |
| --- | --- | --- | --- | --- | --- |
| remoteok | 99 | 2 | 97 | 4 | 0 |
| weworkremotely | 87 | 0 | 87 | 0 | 0 |
| getonboard | 100 | 0 | 100 | 0 | 0 |
| himalayas | 60 | 59 | 1 | 0 | 0 |
| jobicy | 100 | 31 | 69 | 6 | 0 |
| the_muse | 60 | 0 | 60 | 0 | 0 |
| hacker_news | 245 | 0 | 245 | 0 | 0 |

Final source state is success, last success
`2026-10-16 16:42:42.192630+00:00`, no error. Next run is
`2026-10-17 16:08:03+00:00` (**October 17, 13:08:03 America/Montevideo**), within
the next daily window. Alembic is at **d749a8b3e205**.

## Files and working tree

New files: collector, thin CLI, source-default migration, compact authored
comment/thread fixture, parser/HTTP tests, PostgreSQL integration tests and this
report. Existing changes cover source/task/policy catalogs, source-list/default/
scheduling/dispatch/statistics test expectations, README and project guide.
Shared normalization, scoring, fingerprint logic, HTTP transport, DTO and bot
handlers were reused without behavior changes. Full paths follow in status.

`git diff --stat` (tracked files only; seven new files are listed in status):

```text
 README.md                                          |  4 +--
 docs/project-guide.md                              | 35 ++++++++++++++++++----
 src/collectors/registry.py                         |  2 ++
 src/services/collector_policy.py                   |  6 ++++
 src/tasks/jobs.py                                  | 10 +++++++
 tests/bot/test_commands.py                         |  4 ++-
 tests/integration/test_himalayas_postgres.py       |  9 +++++-
 tests/integration/test_jobicy_postgres.py          |  4 ++-
 .../test_persistent_filters_postgres.py            |  2 ++
 tests/integration/test_postgres_hardening.py       |  2 +-
 tests/integration/test_the_muse_postgres.py        |  8 ++---
 tests/services/test_scheduling.py                  | 28 ++++++++++++++++-
 tests/services/test_statistics.py                  |  1 +
 tests/services/test_user_filters.py                |  1 +
 tests/tasks/test_tasks.py                          |  2 ++
 15 files changed, 101 insertions(+), 17 deletions(-)
```

`git status --short --branch --untracked-files=all`:

```text
## main...origin/main
 M README.md
 M docs/project-guide.md
 M src/collectors/registry.py
 M src/services/collector_policy.py
 M src/tasks/jobs.py
 M tests/bot/test_commands.py
 M tests/integration/test_himalayas_postgres.py
 M tests/integration/test_jobicy_postgres.py
 M tests/integration/test_persistent_filters_postgres.py
 M tests/integration/test_postgres_hardening.py
 M tests/integration/test_the_muse_postgres.py
 M tests/services/test_scheduling.py
 M tests/services/test_statistics.py
 M tests/services/test_user_filters.py
 M tests/tasks/test_tasks.py
?? docs/hacker-news-stage-report.md
?? migrations/versions/d749a8b3e205_enable_hacker_news_source.py
?? src/collectors/hacker_news.py
?? src/scripts/collect_hacker_news.py
?? tests/collectors/test_hacker_news.py
?? tests/fixtures/hacker_news/thread.json
?? tests/integration/test_hacker_news_postgres.py
```

HEAD remains 1a292de, in sync with origin/main. All stage changes are unstaged
and uncommitted. No commit, push, next source or new product feature was added.
