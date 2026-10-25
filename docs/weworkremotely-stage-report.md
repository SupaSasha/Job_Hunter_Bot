# We Work Remotely stage report

> October 25, 2026 update: Structured skills are now preserved without a technical whitelist. Profession category labels are kept separate from skills. See [universal matching report](universal-matching-report.md). Earlier live-run details below are historical.

## Data source and scope

The integration uses the official public RSS endpoint:
https://weworkremotely.com/remote-jobs.rss

The [official RSS page](https://weworkremotely.com/remote-job-rss-feed) explicitly
offers this feed for reuse with links back to WWR. The
[API documentation](https://weworkremotely.com/api) describes token authentication;
the public RSS supplies the required listing data without credentials.
The first direct HTTP check returned 200 and 82 items. No alternative endpoints,
job-page scraping, browser automation, CAPTCHA bypass or authorization bypass
were used.

The collector uses httpx and stdlib ElementTree / HTMLParser. Dependencies,
database schema, scoring, filters and fingerprint algorithm are unchanged.
Collection does not send Telegram messages.

## Files

Created:

- src/collectors/weworkremotely.py
- src/collectors/registry.py
- src/scripts/collect_weworkremotely.py
- tests/collectors/test_weworkremotely.py
- docs/weworkremotely-stage-report.md

Modified:

- README.md
- src/bot/commands.py
- src/bot/dispatch.py
- src/collectors/base.py
- src/collectors/remoteok.py
- src/repositories/bot_queries.py
- src/scripts/telegram_polling.py
- src/services/collection.py
- src/services/collector_policy.py
- src/tasks/jobs.py
- tests/bot/test_commands.py
- tests/bot/test_dispatch.py
- tests/services/test_collection.py
- tests/services/test_deduplication.py
- tests/services/test_scheduling.py
- tests/tasks/test_tasks.py

## Collector API and mapping

```python
collector = WeWorkRemotelyCollector(timeout=20)
jobs = await collector.collect()  # list[JobDTO]

parse_feed(content: bytes) -> list[JobDTO]
parse_job_item(item: Element, *, collected_at=None) -> JobDTO
```

- source is always weworkremotely.
- external_id uses the source GUID, currently the WWR job permalink.
  A missing GUID falls back to the canonical job permalink; no random hash is used.
- url stays on the WWR job page, removing only tracking queries and fragments.
- title/company come from the RSS company/title separator.
- description becomes readable text; markup, scripts, styles and image tags are
  omitted without attempting semantic restructuring.
- remote is true because the source feed is specifically for remote jobs.
- region/country are explicit feed fields. Country restrictions override a generic
  Anywhere in the World label; headquarters and state are not treated as eligibility.
  Country flags and list conjunctions are removed. No geography is inferred from
  descriptions. Unknown regions remain empty.
- technologies are selected only from explicit technical skills/categories.
  Nontechnical categories and technology names appearing only in prose are ignored.
  Existing NormalizationService handles canonical technology names.
- type maps to employment_type. RFC feed dates become UTC-aware published_at;
  missing/invalid dates remain None. collected_at is UTC-aware.
- Salary, experience and timezone fields are not supplied by this feed and stay None.

HTTP failures and malformed feed documents raise CollectionError rather than
returning a misleading successful empty result. HTTP 429 honors Retry-After through
the scheduler cooldown; no immediate retry is made. The response is bounded to
8 MiB. Unexpected XML/HTML, DTD/entity declarations and wholly malformed item
batches fail safely. Individual malformed items are skipped with a warning,
matching the existing collector convention; valid empty channels are accepted.

## Shared pipeline, scheduler and commands

CollectionService.collect(source, expected_next_run=None, collector=None) now
selects a collector from a small registry and reuses the existing lock, state,
JobPipeline and JobSaveService flow. collect_remoteok remains a compatibility
wrapper. CollectionError moved to the collector base module; its previous import
from remoteok remains available.

```text
collector -> JobDTO -> NormalizationService
          -> JobSaveService / DeduplicationService -> PostgreSQL
```

The implemented-source registries contain exactly remoteok and weworkremotely.
SchedulerService already dispatched through policy.task_name, so no source-specific
if/elif chain or new scheduling framework was required.

| Property | WWR |
| --- | --- |
| Canonical source | weworkremotely |
| Celery task | jobs.collect_weworkremotely |
| Redis lock | collector:weworkremotely:lock |
| Local windows | 04:00–06:00, 16:00–18:00 |
| Scheduler timezone | SCHEDULER_TIMEZONE; currently America/Montevideo |
| Jitter | Existing random second within the next window, persisted in UTC |
| Ordinary failure retry | One hour; Retry-After can postpone it further |

Remote OK retains its 02:00–04:00, 10:00–12:00 and 18:00–20:00 windows.
WWR has its own last_started_at, last_success_at, last_finished_at, next_run_at,
last_status and last_error. Locks and stale-schedule checks remain source-scoped.
The dispatcher still checks due sources every 15 minutes; normal WWR collection
is twice daily, subject to queue delay or failures.

/collect now explicitly starts both registered collectors. The owner help text
and README describe this change. Publication remains off the polling event loop;
the handler never waits for collection results. As before, broker publication
is not atomic across tasks: a publication failure can occur after one was queued.

/status reads all persisted collector states and uses the policy registry for
display names and missing-state placeholders. It shows both sources without a
hardcoded pair of formatting branches. Public commands and digest behavior are
unchanged. No collection task invokes Telegram.

## Manual verification

Two real RSS requests through the production CollectionService and PostgreSQL
completed on 2026-09-28. These were deliberate verification runs, not an
automatic retry loop.

| Run | received | new | duplicates | failed |
| --- | ---: | ---: | ---: | ---: |
| First | 82 | 78 | 4 | 0 |
| Second | 82 | 0 | 82 | 0 |

The database contained 181 jobs after verification. No digest reservations or
feedback records were deleted. The existing daily digest was already empty for
the day; collection itself sent no Telegram messages.

First three collected listings (explicit feed eligibility, not inferred):

```text
[We Work Remotely] Senior SEO & GEO Specialist — Manaferra — Worldwide
[We Work Remotely] Product Owner — Zanda Health — Austria, Bosnia and Herzegovina, Belgium, Bulgaria, Switzerland, Cyprus, Czechia, Denmark, Estonia, Spain, Finland, France, United Kingdom of Great Britain and Northern Ireland, Greece, Croatia, Hungary, Ireland, Iceland, Italy, Lithuania, Latvia, Montenegro, North Macedonia, Malta, Netherlands, Norway, Poland, Portugal, Romania, Serbia, Sweden, Slovenia, Slovakia, Ukraine
[We Work Remotely] Senior Graphic Designer — BBE Marketing Inc — Worldwide
```

## Example mapped JobDTO

Actual collected record; description is shortened only in this report.

```json
{
  "source": "weworkremotely",
  "external_id": "https://weworkremotely.com/remote-jobs/manaferra-senior-seo-geo-specialist",
  "title": "Senior SEO & GEO Specialist",
  "company": "Manaferra",
  "description": "Headquarters: New York\nURL: https://manaferra.com/\nPosition overview\nManaferra is seeking a Senior SEO & GEO Specialist. The successful candidate will be responsible for the strate [excerpt]",
  "url": "https://weworkremotely.com/remote-jobs/manaferra-senior-seo-geo-specialist",
  "location": "Anywhere in the World",
  "timezone_text": null,
  "timezone_min_utc_offset": null,
  "timezone_max_utc_offset": null,
  "remote": true,
  "remote_regions": [
    "Worldwide"
  ],
  "employment_type": "Contract",
  "salary_min": null,
  "salary_max": null,
  "currency": null,
  "salary_period": null,
  "technologies": [],
  "experience_level": null,
  "published_at": "2026-09-28T20:10:18Z",
  "collected_at": "2026-09-28T21:24:59.055102Z"
}
```

## Cross-source deduplication

A real cross-source match was found:

- Remote OK: Sanctuary Computer / Senior Shopify Developer.
- WWR: Sanctuary Computer / Senior Shopify Developer.
- Fingerprint: 059a9ef12f6df39026aa631d68ebf5b0f47686b9448094c4338813ee2e596952.
- Result: duplicate by fingerprint; existing Remote OK job ID 14 was retained.

The three remaining first-run duplicates were same-company/title pairs within
WWR, with distinct slugs (one ending in -1):

- Collibra / CPS Solution Architect.
- Dropbox / Customer Evidence Manager.
- Ping Identity / Customer Success Manager.

These demonstrate the existing heuristic: it conflates matching company/title
pairs even when source IDs differ. The feed alone does not establish whether
each pair is a repost or a distinct opening. No fuzzy matching or weakening of
the fingerprint was introduced. Source identity remains uniquely constrained in
PostgreSQL; fingerprint deduplication remains a best-effort application check.

## Live state and /status

WWR's persisted next run after the second successful check is
2026-09-29 08:10:20 UTC (05:10:20 America/Montevideo).

The following status was rendered against the real DB without sending Telegram:

```text
Bot status: running

Remote OK
Last success: 2026-09-28 12:15
Next run: 2026-09-28 18:39
Last status: success

We Work Remotely
Last success: 2026-09-28 18:25
Next run: 2026-09-29 05:10
Last status: success

Jobs in database: 181

Daily digest:
Time: 09:00
Timezone: America/Montevideo
Last digest: Today (empty)
Enabled: Yes

Times shown in America/Montevideo.
```

Worker and polling were gracefully restarted with the new code. A real Celery
inspect confirmed both jobs.collect_remoteok and jobs.collect_weworkremotely
registered on the running worker. Beat remains running.

- Worker PID: 531082.
- Polling PID: 531120.
- Beat PID: 349832.

## Checks

- poetry run ruff check .: passed.
- poetry run black --check .: passed; 102 Python files unchanged.
- poetry run pytest -q: 455 passed.
- git diff --check: passed.

Tests make no real network calls. They cover RSS field mapping, HTML cleanup,
missing fields, GUID fallback, region restrictions, explicit technical tags,
UTC timestamps, malformed/oversized feeds, HTTP errors, timeouts, Retry-After,
WWR windows and jitter, source-specific locks, task registration and dispatch,
/status, /collect and cross-source fingerprint matching.

No commit or push was made.

## Git snapshot

git diff --stat (tracked files; new files are listed separately in status):

```text
 README.md                            | 78 +++++++++++++++++++++++++++++++-----
 src/bot/commands.py                  | 35 ++++++++++------
 src/bot/dispatch.py                  |  7 ++--
 src/collectors/base.py               |  9 +++++
 src/collectors/remoteok.py           |  5 +--
 src/repositories/bot_queries.py      |  7 ++++
 src/scripts/telegram_polling.py      |  6 ++-
 src/services/collection.py           | 24 +++++++++--
 src/services/collector_policy.py     | 10 ++++-
 src/tasks/jobs.py                    | 18 +++++++++
 tests/bot/test_commands.py           | 37 +++++++++++++----
 tests/bot/test_dispatch.py           | 14 ++++++-
 tests/services/test_collection.py    | 69 ++++++++++++++++++++++++++++++-
 tests/services/test_deduplication.py | 23 +++++++++++
 tests/services/test_scheduling.py    | 48 ++++++++++++++++++++++
 tests/tasks/test_tasks.py            | 13 ++++++
 16 files changed, 357 insertions(+), 46 deletions(-)
```

git status --short --branch:

```text
## main...origin/main
 M README.md
 M src/bot/commands.py
 M src/bot/dispatch.py
 M src/collectors/base.py
 M src/collectors/remoteok.py
 M src/repositories/bot_queries.py
 M src/scripts/telegram_polling.py
 M src/services/collection.py
 M src/services/collector_policy.py
 M src/tasks/jobs.py
 M tests/bot/test_commands.py
 M tests/bot/test_dispatch.py
 M tests/services/test_collection.py
 M tests/services/test_deduplication.py
 M tests/services/test_scheduling.py
 M tests/tasks/test_tasks.py
?? docs/weworkremotely-stage-report.md
?? src/collectors/registry.py
?? src/collectors/weworkremotely.py
?? src/scripts/collect_weworkremotely.py
?? tests/collectors/test_weworkremotely.py
```
