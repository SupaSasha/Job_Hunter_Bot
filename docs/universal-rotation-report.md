# Universal matching follow-up

## Changed files

Collector/state: src/collectors/jooble.py, src/services/collection.py.
Defaults: src/schemas/filters.py, src/models/user_filter.py,
src/services/user_filters.py, migrations/versions/a2b3c4d5e6f7_worldwide_default.py.
Parsing/filtering: src/collectors/hacker_news.py, src/services/filters.py.
UI: src/bot/settings.py, src/i18n/en.py, src/i18n/es.py.
Deployment: scripts/deploy-excludes.txt anchors the runtime /data exclusion so
bundled src/data reference files are included. Existing deployment script is used.
Related README/project guide and historical report links are updated.
The git snapshot below includes earlier uncommitted project changes.

## Tests added/updated

Jooble: persistent rotation across new collector instances, full wrap, budgets
1/2/3, job cap, failure advancement, missing Redis state and shared scheduled/manual
collection under the source lock. Generic profiles cover Backend/FastAPI, Design,
Sales, Accounting and Recruiting. Neutral profession/region scores, new Worldwide
defaults, migration preservation, cross-currency salary safety and global timezone
presets are covered. HN includes Marketing Manager, Operations Manager, explicit
unknown titles and generic fallback. Existing formatter percentage-only behavior
is retained. Tests were not removed.

## Jooble queries after change

engineering, design, product, sales, marketing, customer support, finance,
operations, human resources, data.

The index is stored using Redis INCR in a market-specific key. Source locking
and CollectionService are shared by scheduled collection and manual /collect.
Default request budget remains 1 per cycle, rotating one profession each cycle.
At configured budgets 2 or 3, up to two professions share that same total budget;
any remaining request paginates the first query. Queries blocked by the job cap
do not consume an index. The ten queries are never all requested in one cycle.

## USAJOBS request filters after change

RemoteIndicator=True, DatePosted=30, SortField=opendate, SortDirection=Desc,
ResultsPerPage=50, Page=<current page>, Fields=Full.
No JobCategoryCode or mandatory Keyword. USAJOBS remains default OFF;
its request budget is unchanged.

## HN supported role patterns after change

Existing engineering/development roles plus sales, account executive, business
development, marketing, growth, customer support/success, recruiting, talent
acquisition, HR/human resources, operations, finance/accounting, legal,
project/product management, design, copywriting/content, data analysis and
consulting. Unknown explicit pipe-separated titles are retained (Ornithologist,
for example); unextractable hiring titles use Multiple roles.

## New user defaults

keywords/required_technologies/preferred_technologies/excluded_technologies=[],
employment_types/experience_levels=[], blacklisted_words/blacklisted_companies=[],
min_salary=None, currency=None, allowed_regions=[worldwide], remote_only=True,
exclude_us_only=False. Eight sources enabled; USAJOBS off. Existing saved rows
are preserved. The migration changes only a future-row server default.

## Timezone options

UTC; America/New_York, Chicago, Denver, Los_Angeles, Mexico_City, Sao_Paulo,
Montevideo, Argentina/Buenos_Aires; Europe/London, Madrid, Berlin;
Asia/Dubai, Kolkata, Singapore, Tokyo; Africa/Johannesburg, Cairo;
Australia/Sydney; Pacific/Auckland. Custom IANA input uses ZoneInfo.

## Currency options

Any, USD, EUR, GBP, CAD, AUD, BRL, MXN, UYU, Other.
Custom input: three ASCII letters, stored uppercase. No currency conversion.

## pytest result

1758 passed in 39.33s, including 88 PostgreSQL integration tests, zero skipped.
The database was isolated under /tmp; production data and .env were not used.

## ruff result

Passed: poetry run ruff check .

## black result

Passed: poetry run black --check . (BLACK_NUM_WORKERS=1), 188 Python files unchanged.

## git diff --stat

```text
 README.md                                          |  14 +-
 docs/getonboard-stage-report.md                    |   2 +
 docs/hacker-news-stage-report.md                   |   6 +
 docs/himalayas-stage-report.md                     |   2 +
 docs/jooble-stage-report.md                        |   8 +
 docs/project-guide.md                              | 115 +++---
 docs/scheduling-stage-report.md                    |   7 +-
 docs/usajobs-stage-report.md                       |   9 +-
 docs/user-filters-report.md                        |  67 ++--
 docs/weworkremotely-stage-report.md                |   2 +
 scripts/deploy-excludes.txt                        |   2 +-
 scripts/deploy.sh                                  |   2 +-
 src/bot/filters.py                                 |  75 +++-
 src/bot/pending_input.py                           |   3 +
 src/bot/settings.py                                |  98 ++++-
 src/bot/updates.py                                 |   7 +-
 src/collectors/getonboard.py                       |   3 +-
 src/collectors/hacker_news.py                      | 118 +++++-
 src/collectors/himalayas.py                        |  10 +-
 src/collectors/jooble.py                           |  65 +++-
 src/collectors/skills.py                           | 102 +++--
 src/collectors/usajobs.py                          |  29 +-
 src/collectors/weworkremotely.py                   |   4 +-
 src/i18n/en.py                                     | 104 +++--
 src/i18n/es.py                                     | 113 ++++--
 src/i18n/scoring.py                                |  75 ++--
 src/models/user_filter.py                          |   4 +-
 src/schemas/filters.py                             |  10 +-
 src/scripts/telegram_polling.py                    |   1 +
 src/services/collection.py                         |   6 +-
 src/services/default_filters.py                    |  22 +-
 src/services/filters.py                            |  52 +--
 src/services/normalization.py                      |   9 +-
 src/services/scoring.py                            | 428 ++++++++++-----------
 src/services/tokens.py                             |  25 +-
 src/services/user_filters.py                       | 129 ++++---
 tests/bot/test_formatter.py                        |   2 +-
 tests/bot/test_job_filter_menu.py                  |  54 +++
 tests/bot/test_settings.py                         |  99 ++++-
 tests/collectors/test_getonboard.py                |  13 +-
 tests/collectors/test_hacker_news.py               |  78 +++-
 tests/collectors/test_himalayas.py                 |  31 +-
 tests/collectors/test_jobicy.py                    |   2 +-
 tests/collectors/test_jooble.py                    | 192 +++++++--
 tests/collectors/test_usajobs.py                   |  50 ++-
 tests/collectors/test_weworkremotely.py            |  16 +-
 tests/conftest.py                                  |   6 +
 tests/integration/test_jooble_postgres.py          |  17 +-
 .../test_persistent_filters_postgres.py            |  72 +++-
 tests/integration/test_postgres_hardening.py       |   2 +-
 tests/integration/test_usajobs_postgres.py         |   8 +-
 tests/integration/test_user_language_postgres.py   |   6 +-
 tests/services/test_collection.py                  |  36 ++
 tests/services/test_digests.py                     |  60 ++-
 tests/services/test_filters.py                     |   9 +-
 tests/services/test_notification_settings.py       |  15 +
 tests/services/test_scoring.py                     | 327 +++++++++++++++-
 tests/services/test_tokens_timezones.py            |  33 +-
 tests/services/test_translator.py                  |  40 +-
 tests/services/test_user_filters.py                | 109 ++++--
 60 files changed, 2261 insertions(+), 744 deletions(-)
```

## git status

Pre-commit snapshot (user subsequently authorized commit, push and deployment):

```text
 M README.md
 M docs/getonboard-stage-report.md
 M docs/hacker-news-stage-report.md
 M docs/himalayas-stage-report.md
 M docs/jooble-stage-report.md
 M docs/project-guide.md
 M docs/scheduling-stage-report.md
 M docs/usajobs-stage-report.md
 M docs/user-filters-report.md
 M docs/weworkremotely-stage-report.md
 M scripts/deploy-excludes.txt
 M scripts/deploy.sh
 M src/bot/filters.py
 M src/bot/pending_input.py
 M src/bot/settings.py
 M src/bot/updates.py
 M src/collectors/getonboard.py
 M src/collectors/hacker_news.py
 M src/collectors/himalayas.py
 M src/collectors/jooble.py
 M src/collectors/skills.py
 M src/collectors/usajobs.py
 M src/collectors/weworkremotely.py
 M src/i18n/en.py
 M src/i18n/es.py
 M src/i18n/scoring.py
 M src/models/user_filter.py
 M src/schemas/filters.py
 M src/scripts/telegram_polling.py
 M src/services/collection.py
 M src/services/default_filters.py
 M src/services/filters.py
 M src/services/normalization.py
 M src/services/scoring.py
 M src/services/tokens.py
 M src/services/user_filters.py
 M tests/bot/test_formatter.py
 M tests/bot/test_job_filter_menu.py
 M tests/bot/test_settings.py
 M tests/collectors/test_getonboard.py
 M tests/collectors/test_hacker_news.py
 M tests/collectors/test_himalayas.py
 M tests/collectors/test_jobicy.py
 M tests/collectors/test_jooble.py
 M tests/collectors/test_usajobs.py
 M tests/collectors/test_weworkremotely.py
 M tests/conftest.py
 M tests/integration/test_jooble_postgres.py
 M tests/integration/test_persistent_filters_postgres.py
 M tests/integration/test_postgres_hardening.py
 M tests/integration/test_usajobs_postgres.py
 M tests/integration/test_user_language_postgres.py
 M tests/services/test_collection.py
 M tests/services/test_digests.py
 M tests/services/test_filters.py
 M tests/services/test_notification_settings.py
 M tests/services/test_scoring.py
 M tests/services/test_tokens_timezones.py
 M tests/services/test_translator.py
 M tests/services/test_user_filters.py
?? docs/universal-matching-report.md
?? migrations/versions/a2b3c4d5e6f7_worldwide_default.py
?? migrations/versions/d0e7c42b6a91_neutral_region_defaults.py
?? migrations/versions/f1a2b3c4d5e6_neutral_us_only_default.py
?? src/data/
?? src/scripts/validate_profiles.py
?? src/services/region_compatibility.py
?? src/services/regions.py
?? tests/fixtures/universal_profiles.json
?? tests/services/test_universal_matching.py
```
