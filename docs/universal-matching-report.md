# Universal remote job matching — October 25, 2026

> Historical snapshot of the preceding stage. The follow-up changes the default
> region to Worldwide, replaces Jooble's `jobs` query with Redis-backed profession
> rotation, expands timezone presets and improves HN fallback. See
> [the current report](universal-rotation-report.md).

The bot remains remote-first. Collection and matching are independent of the
owner's profession and location. No new job source, ML/LLM, payment or analytics
implementation was added. The database column `technologies` remains unchanged.
This report includes the earlier uncommitted work and the completed follow-up.

## Before and after

| Area | Before the requested stage | After |
| --- | --- | --- |
| Default keywords | Python owner bootstrap | Empty |
| Default skills | Python/backend stack | Empty required/preferred/excluded lists |
| Default regions | Worldwide/LATAM/South America/Uruguay | Empty = no region restriction |
| US-only exclusion | Enabled globally | False for future users; explicit user filter |
| Scoring | Python/LATAM/Middle/full-time bonuses | User-relative keywords, skills, region, timezone, employment, experience, salary and remote preference |
| Skill model | Technical whitelist, compact ASCII tokens | Generic Unicode skills, preserved multiword boundaries, explicit aliases |
| Get on Board | Programming category | Public remote search without keyword, country or category |
| Jooble | software/developer | One profession-neutral `jobs` search; bounded regional coverage |
| USAJOBS | Mandatory IT series 2210 | Broad remote search; no category/keyword restriction; default OFF |
| HN parser | Mostly technical roles | Deterministic professional patterns, non-tech skills and hiring fallback |
| Timezone UI | Eight presets | Fifteen global presets and custom IANA input |
| Currency UI | USD/EUR/UYU/Any | Eight presets, Other three-letter code, Any |
| Regions/countries | Uruguay as a privileged region | Symmetric regional presets and a generic country editor |
| Experience inference | Substring matches and ambiguous staff/middle titles | Explicit generic seniority markers; unknown/noncomparable metadata does not reject |

## Defaults and compatibility

New users, including the owner, receive empty keyword, skill, blacklist,
employment and experience lists, no minimum salary or currency, no region
restriction, `remote_only=True`, and `exclude_us_only=False`.
The eight sources Remote OK, WWR, Get on Board, Himalayas, Jobicy, The Muse,
Hacker News and Jooble are selected. USAJOBS is available but unselected.

`allowed_regions` is the only region preference. The four former DTO booleans
worldwide_allowed, latam_allowed, south_america_allowed and uruguay_allowed were
removed from DTO, mapping, hard filtering and scoring. They were never ORM
columns, so removing them requires no destructive schema migration. Stale extra
DTO keys are ignored and cannot re-enable a region.

Saved filter rows are not overwritten during bootstrap or reads. Existing
Python/LATAM/Uruguay profiles and explicit US-only exclusions remain intact.
Compact historical skills such as uxresearch are accepted through explicit
aliases; reads preserve saved strings, and user-requested add/remove/exclude
operations compare canonical tokens. No fuzzy matching or mass data rewrite.

The two new migrations change only server defaults for future user_filters rows:

- d0e7c42b6a91: allowed_regions becomes an empty array.
- f1a2b3c4d5e6: exclude_us_only becomes false.

Both are ALTER DEFAULT operations. Integration tests downgrade to the preceding
revision, insert a personal profile, upgrade, compare the saved arrays/boolean,
and insert a future row to check the new defaults. Alembic metadata checks pass.
Migrations were applied only to a temporary test PostgreSQL, not production.

## Skills, categories, keywords and experience

`technologies` now represents generic searchable professional skills/tags.
Structured source skills retain unknown tokens rather than using a profession
whitelist. WWR and Himalayas no longer use TECHNICAL_CATEGORIES. Broad categories
Engineering/Marketing/Sales/Finance/Design and role labels are separated from
skills. Jooble, Jobicy, The Muse and USAJOBS do not invent structured skills when
the source has none. A future dedicated profession/category field could retain
that metadata; this stage does not add a schema column.

Canonical aliases include postgres → postgresql, fast api → fastapi,
node.js → nodejs, MS Excel/Microsoft Excel → excel. Multiword tokens such as
UX Research, B2B Sales and Talent Acquisition retain spaces. Unicode survives.
Google Ads and Google Adsense remain different. Known generic noise such as
communication, team player, motivated and responsible is excluded from normalized
source skills. No large handwritten universal skill dictionary was introduced.
The small HN text vocabulary is an extraction aid, never an input whitelist.

Hard filters remain user-driven. Keyword/blacklist and preferred-skill text
matching use literal Unicode-aware word boundaries. Required and excluded skills
compare normalized structured skills. Currency mismatch is handled without FX;
Any does not restrict currency. Employment values such as temporary, seasonal and
permanent are not silently converted to full_time.

Only comparable experience metadata is used to reject. Missing and noncomparable
source levels pass. Manager/Director are not assigned IT hierarchy levels.
Leadership Consultant, Staff Accountant and Middle School Teacher do not acquire
lead/staff/middle through title substring matching. Explicit Junior, Senior,
Lead, Principal and mid-level markers can inform user-relative scoring.
Years-of-experience are not scored globally.

## Collector audit and request budgets

| Collector | Profession/query restriction now | Region restriction / skills handling |
| --- | --- | --- |
| Remote OK | General existing API feed | Source geography only; generic structured tags |
| WWR | General RSS feed | Source geography only; preserves professional skills, separates categories |
| Get on Board | `/api/v0/search/jobs?remote=true`, no query/category/country | Source eligibility only; expanded tags and relationships |
| Himalayas | General remote feed | Source location restrictions; generic skills/tags/specific labels |
| Jobicy | General remote feed; no profession parameter | Source jobGeo; industry stays separate from skills |
| The Muse | Existing Flexible / Remote location search; no category | No inferred global eligibility or invented skills |
| HN | Official monthly hiring thread | Explicit remote/region metadata; deterministic role/skill patterns |
| Jooble | One `jobs` query, shared collection | Explicit configured regional domain/location; no per-user searches |
| USAJOBS | RemoteIndicator=True; no JobCategoryCode or Keyword | US-centric source, opt-in; explicit eligibility retained |

Jooble documentation marks keywords and location as required and the key as
country/domain-specific. It does not document a complete general collection
endpoint or a supported empty-keyword strategy. Keeping one `jobs` query is the
bounded profession-neutral compromise. This keyword can miss vacancies; it does
not promise all professions or all world markets in every run. No live keyed
Jooble request was made for this stage.

| API request budget, excluding existing retry behavior | Before | After |
| --- | --- | --- |
| Jooble, default per collection run | 2 queries × 1 page = 2 | 1 query × 1 page = 1 |
| Jooble, configured ceiling | 2 × 3 = 6 | 1 × 3 = 3 |
| USAJOBS, default per run | 1 category × 2 pages = 2 | 1 remote search × 2 pages = 2 |
| USAJOBS, configured ceiling | 1 × 5 = 5 | 1 × 5 = 5 |
| Get on Board, default per run | 2 category pages | 2 remote search pages |

No significant quota increase: Jooble's request ceiling decreased, USAJOBS and
Get on Board are unchanged. Existing page/job caps, deduplication, scheduling,
request pacing and retry guards remain. Broader results are still truncated by
the same limits. No per-user collector requests or fan-out across categories.

API decisions were checked against primary documentation:
[Jooble REST](https://jooblehelpcenter.freshdesk.com/en/support/solutions/articles/60001448238-rest-api-documentation),
[Get on Board OpenAPI](https://www.getonbrd.com/doc/openapi.yaml?v=2026-05-08-agent-docs),
and [USAJOBS Search](https://developer.usajobs.gov/api-reference/get-api-search).
A public Get on Board request with remote=true, no query, per_page=3 and expanded
relationships returned three jobs and pagination metadata. It made no DB writes.
The protected `/api/v0/jobs` endpoint is company-specific and was not adopted.

HN fixtures cover Sales/Account Executive, Customer Success Manager, Recruiter,
Accountant, business development, marketing, growth, talent acquisition, HR,
operations, finance, legal, project/product management, designers, copywriters,
content, data analysts and consultants. Unrecognized explicit hiring posts such
as Ornithologist remain with `Job opening`; multiple roles remain a single entry.

## User interface

- `/filters → Regions → Specific countries → Add/Remove/Clear`: comma-separated
  names or ISO alpha-2/alpha-3 codes. Example: Uruguay, Spain, Canada / UY, ES, CA.
  Canonical names are stored in the existing allowed_regions array; legacy
  uruguay, canada and us values remain compatible. Region toggles preserve
  selected countries. The editor supports all 249 ISO entries through bundled
  static data and CLDR region membership, without runtime geo services.
- Regional presets: Worldwide, Americas, North America, LATAM, South America,
  Europe, EU, EMEA, APAC, Asia, Africa and Oceania. Worldwide and no selection
  both accept any known region; worldwide vacancies remain compatible with
  specific user regions. EMEA = Europe/Africa/Western Asia; APAC = Asia/Oceania.
- `/settings → Timezone`: global presets plus Other / Custom timezone. Send an
  IANA name, for example Europe/Berlin, Asia/Tokyo or America/Mexico_City.
  ZoneInfo validates input and handles DST. No guessed Telegram timezone or fixed
  GMT-offset picker. Existing scheduler/model Montevideo defaults are temporary
  application fallbacks; user settings override them.
- `/filters → Salary → Currency`: USD, EUR, GBP, CAD, AUD, BRL, MXN, UYU, Other,
  Any. Custom input accepts three ASCII letters and stores uppercase. USD/EUR/
  GBP/BRL/JPY pass; US/DOLLAR/123 fail. This is format validation, not an FX service.
- Shared pending input expires in 600 seconds, supports /cancel, keeps invalid
  entries pending for retry and clears after successful persistence. Settings
  and filters consume only their own pending actions. Identity/private-chat
  checks remain in place.
- EN: Skills, Required skills, Preferred skills, Excluded skills.
- ES: Habilidades, Habilidades requeridas, Habilidades preferidas, Habilidades excluidas.
- Examples cover Python/FastAPI, Figma/UX Research, Salesforce/B2B Sales and
  Excel/Accounting. Keywords include accountant, sales, designer and python.

## Manual offline validation

Run `poetry run python -m src.scripts.validate_profiles`. These are authored
fixtures, not live listings or production users. All 15 jobs are evaluated for
each profile through normalization, hard filters and scoring; the expected top
three are checked automatically by pytest.

| Profile | Top 1 | Top 2 | Top 3 |
| --- | --- | --- | --- |
| Backend, Worldwide | Python Backend Developer (100) | Python Backend Engineer (90) | Backend API Engineer (80) |
| Design, Europe | UX Designer (100) | UI Designer (90) | Brand Designer (80) |
| Sales, Worldwide | Sales Manager (100) | Enterprise Sales Executive (90) | Sales Representative (80) |
| Accounting, Worldwide | Senior Accountant (100) | Staff Accountant (90) | Tax Accountant (80) |
| Support, LATAM | Customer Support Specialist (100) | Customer Support Agent (90) | Customer Support Associate (90) |

## Bias audit

The requested broad search across src/tests was run with rg, equivalent to the
prompt's grep expression. Remaining occurrences are implementation dependencies,
ordinary aliases, the HN extraction vocabulary, user-selected region/skill values,
professional examples and fixtures. No product-wide Python/backend/LATAM profile
or technical input whitelist remains.

Every occurrence from the two focused source-code searches is explained below:

| File / occurrence | Why retained |
| --- | --- |
| src/collectors/jooble.py:21 JOOBLE_SEARCH_QUERIES | Single profession-neutral `jobs` strategy |
| src/collectors/jooble.py:120 search_queries assignment | Uses that same bounded strategy |
| src/config.py:23 America/Montevideo | Operational application fallback, user-overridable |
| src/models/scheduling.py:40 America/Montevideo | Notification-settings fallback, no location inference or scoring preference |
| src/bot/settings.py:29 America/Montevideo | One ordinary preset beside global/custom zones |
| src/services/user_filters.py:37 UYU | One of eight currency presets; other codes accepted |
| src/collectors/salary.py:6 UYU | Existing salary text currency alias, not a UI restriction |

No matches remain in src for personal Python/FastAPI/LATAM/Uruguay defaults,
2210, latam_allowed, uruguay_allowed, south_america_allowed or
TECHNICAL_CATEGORIES. Country names in static ISO data and UI labels are ordinary
countries, not privileged rules.

## Requirement coverage

| Prompt items | Result / evidence |
| --- | --- |
| 1–3, 26, 35 | Neutral DTO/ORM/bootstrap; no legacy flags or overwritten saved filters |
| 4–6, 17 | Generic normalization and source skills; category separation; unchanged schema |
| 7–8, 18–22 | User-relative filters/scoring, Unicode boundaries, safe experience handling |
| 9–16 | All nine collectors audited; broad searches, quota caps and HN roles/fallback |
| 23–25, 45 | Generic country editor, regional membership and neutral region scoring |
| 27–28, 44 | Custom global IANA selection, ZoneInfo validation, no timezone guessing |
| 29–30, 43 | Generic currency UI, validation and existing no-FX salary semantics |
| 31–32 | Remote-first wording, eight default sources, USAJOBS opt-in |
| 33–34, 36 | EN/ES skills wording, diverse examples and product docs |
| 37–42 | Neutral/default/preservation, non-tech profile, normalization and collector tests |
| 46–47 | Default-only migrations and unchanged/decreased request budgets |
| 48–49 | Five-profile top-three validation and focused/broad bias audit |
| 50 | Ruff, Black and full pytest with temporary PostgreSQL (results below) |
| 51 | No commit or push |

## Final checks

- `poetry run ruff check .`: passed.
- `poetry run black --check .` with `BLACK_NUM_WORKERS=1`: passed, 187 Python files unchanged.
- Full `poetry run pytest` with TEST_DATABASE_URL pointing to the disposable
  PostgreSQL under /tmp: **1743 passed, zero skipped**, including **88 integration tests**.
- `git diff --check`: passed.
- `poetry run python -m src.scripts.validate_profiles`: all five expected top-three rankings passed.
- Final HN examples: `Acme | Remote | Sales | Account Executive` → Account Executive;
  Customer Success Manager, Recruiter and Accountant preserve their full titles.
- Production database, user preferences and .env were not changed.
- No commit or push; HEAD remains 7cddff0.

The first sandbox-only full-suite attempts stalled in an existing asyncio.to_thread
Celery dispatcher test. The full suite was then executed successfully with the
required local socket/thread permissions and the isolated test database. No tests
were removed or skipped to obtain the passing result.

## Git state

This snapshot includes the user's pre-existing uncommitted changes. `git diff --stat`
counts tracked changes only; the untracked migration, data, script, report and test
files are listed by git status below.

```text
 README.md                                          |  12 +-
 docs/getonboard-stage-report.md                    |   2 +
 docs/hacker-news-stage-report.md                   |   6 +
 docs/himalayas-stage-report.md                     |   2 +
 docs/jooble-stage-report.md                        |   8 +
 docs/project-guide.md                              | 107 +++---
 docs/scheduling-stage-report.md                    |   7 +-
 docs/usajobs-stage-report.md                       |   9 +-
 docs/user-filters-report.md                        |  67 ++--
 docs/weworkremotely-stage-report.md                |   2 +
 scripts/deploy.sh                                  |   2 +-
 src/bot/filters.py                                 |  75 +++-
 src/bot/pending_input.py                           |   3 +
 src/bot/settings.py                                |  85 ++++
 src/bot/updates.py                                 |   7 +-
 src/collectors/getonboard.py                       |   3 +-
 src/collectors/hacker_news.py                      |  63 ++-
 src/collectors/himalayas.py                        |  10 +-
 src/collectors/jooble.py                           |   2 +-
 src/collectors/skills.py                           | 102 +++--
 src/collectors/usajobs.py                          |  29 +-
 src/collectors/weworkremotely.py                   |   4 +-
 src/i18n/en.py                                     | 102 +++--
 src/i18n/es.py                                     | 113 ++++--
 src/i18n/scoring.py                                |  75 ++--
 src/models/user_filter.py                          |   4 +-
 src/schemas/filters.py                             |   8 +-
 src/scripts/telegram_polling.py                    |   1 +
 src/services/default_filters.py                    |  22 +-
 src/services/filters.py                            |  44 +--
 src/services/normalization.py                      |   9 +-
 src/services/scoring.py                            | 428 ++++++++++-----------
 src/services/tokens.py                             |  25 +-
 src/services/user_filters.py                       | 132 ++++---
 tests/bot/test_job_filter_menu.py                  |  54 +++
 tests/bot/test_settings.py                         |  96 ++++-
 tests/collectors/test_getonboard.py                |  13 +-
 tests/collectors/test_hacker_news.py               |  74 +++-
 tests/collectors/test_himalayas.py                 |  31 +-
 tests/collectors/test_jobicy.py                    |   2 +-
 tests/collectors/test_jooble.py                    |  47 ++-
 tests/collectors/test_usajobs.py                   |  50 ++-
 tests/collectors/test_weworkremotely.py            |  16 +-
 tests/integration/test_jooble_postgres.py          |  16 +-
 .../test_persistent_filters_postgres.py            |  75 +++-
 tests/integration/test_postgres_hardening.py       |   2 +-
 tests/integration/test_usajobs_postgres.py         |   8 +-
 tests/integration/test_user_language_postgres.py   |   6 +-
 tests/services/test_digests.py                     |  60 ++-
 tests/services/test_filters.py                     |   9 +-
 tests/services/test_notification_settings.py       |  15 +
 tests/services/test_scoring.py                     | 324 +++++++++++++++-
 tests/services/test_tokens_timezones.py            |  33 +-
 tests/services/test_translator.py                  |  40 +-
 tests/services/test_user_filters.py                | 107 ++++--
 55 files changed, 1955 insertions(+), 693 deletions(-)
```

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
 M src/services/default_filters.py
 M src/services/filters.py
 M src/services/normalization.py
 M src/services/scoring.py
 M src/services/tokens.py
 M src/services/user_filters.py
 M tests/bot/test_job_filter_menu.py
 M tests/bot/test_settings.py
 M tests/collectors/test_getonboard.py
 M tests/collectors/test_hacker_news.py
 M tests/collectors/test_himalayas.py
 M tests/collectors/test_jobicy.py
 M tests/collectors/test_jooble.py
 M tests/collectors/test_usajobs.py
 M tests/collectors/test_weworkremotely.py
 M tests/integration/test_jooble_postgres.py
 M tests/integration/test_persistent_filters_postgres.py
 M tests/integration/test_postgres_hardening.py
 M tests/integration/test_usajobs_postgres.py
 M tests/integration/test_user_language_postgres.py
 M tests/services/test_digests.py
 M tests/services/test_filters.py
 M tests/services/test_notification_settings.py
 M tests/services/test_scoring.py
 M tests/services/test_tokens_timezones.py
 M tests/services/test_translator.py
 M tests/services/test_user_filters.py
?? docs/universal-matching-report.md
?? migrations/versions/d0e7c42b6a91_neutral_region_defaults.py
?? migrations/versions/f1a2b3c4d5e6_neutral_us_only_default.py
?? src/data/
?? src/scripts/validate_profiles.py
?? src/services/region_compatibility.py
?? src/services/regions.py
?? tests/fixtures/universal_profiles.json
?? tests/services/test_universal_matching.py
```
