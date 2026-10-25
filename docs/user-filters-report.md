# Persistent user filters

Stage completed locally on 2026-10-05. Job search preferences now persist per
user in PostgreSQL and are edited through /filters. Every digest loads its
recipient's saved DTO before filtering and scoring. /settings continues to
manage notification timezone, digest time, minimum score and plan information.

## Files

Created:

- `src/models/user_filter.py`
- `src/repositories/user_filters.py`
- `src/services/user_filters.py`
- `src/bot/filters.py`
- `src/bot/pending_input.py`
- `migrations/versions/c41a9e327b60_add_persistent_user_filters.py`
- `tests/conftest.py`
- `tests/services/test_user_filters.py`
- `tests/bot/test_job_filter_menu.py`
- `tests/bot/test_pending_input.py`
- `tests/integration/test_persistent_filters_postgres.py`
- `docs/user-filters-report.md`

Modified:

- `src/models/__init__.py`: register/export the model.
- `src/services/default_filters.py`: provide a neutral profile for new users.
- `src/services/digests.py`: load recipient filters through UserFilterService.
- `src/bot/commands.py`: delegate /filters and /cancel; update public help.
- `src/bot/updates.py`: route filters callbacks and pending plain text.
- `src/scripts/telegram_polling.py`: share the Redis pending store and construct
  the filter service/handler for each update.
- `tests/services/test_digests.py`: provide a filter-service fake to existing
  delivery tests.
- `tests/bot/test_commands.py`: assert plan-independent filters and cancellation.
- `tests/integration/test_postgres_hardening.py`: update the expected Alembic head.
- `README.md`: document persistence, menus, defaults, commands and deployment.

## Model, migration and transactions

`UserFilterORM` maps `user_filters` with an integer primary key, unique `user_id`,
foreign key to `users.id`, and timezone-aware creation/update timestamps.
String arrays store keywords, required/preferred/excluded technologies, regions,
employment/experience selections, blacklisted words/companies and sources.
Nullable INTEGER minimum salary and string currency accompany Remote only,
Exclude US-only and integer timezone tolerance. Database checks enforce
nonnegative salary, tolerance 0..4 and at least one source. Notification timezone
is not duplicated.

Migration `c41a9e327b60` follows `49f75b591334`. Upgrade only creates the new table
and its constraints; it does not rewrite or remove existing data. Integration
testing migrated the preceding revision with existing users/preferences,
verified their preservation, and ran Alembic's metadata check successfully.
Downgrade refuses to drop a nonempty filter table without manual review.

Repository API:

```python
await UserFilterRepository(session).get_by_user_id(user_id)  # ORM or None
await UserFilterRepository(session).add(filters)  # ORM; flush only
```

Get-or-create orchestration belongs to the service, following the existing
transaction style. The service locks the parent user before bootstrap and
read-modify-write, then commits or rolls back. Concurrent first reads create
one row; concurrent list additions preserve all changes. Callers use a session
without unrelated pending writes.

Service API (all successful operations return the existing UserFilterDTO):

```python
await service.get_filters(user_id)
await service.get_or_create_filters(user_id)
await service.update_list(user_id, field, action, text="")  # add/remove/clear
await service.toggle(user_id, field, value=None)
await service.update_min_salary(user_id, amount)  # digit text or None
await service.update_currency(user_id, currency)  # any three-letter currency code or None
await service.update_timezone_tolerance(user_id, hours)  # integer 0..4
await service.reset(user_id)
```

`filters_to_dto(row, timezone)` copies arrays/scalars into UserFilterDTO and
uses allowed_regions as the single source of region preferences. An empty allowed_regions list
means any region; a vacancy marked worldwide is compatible with every specific
region. Timezone comes from the recipient's notification settings; the scheduler
default remains an operational default, not a global scoring bonus.
No duplicate DTO, scoring weights, new dependencies or handler ORM writes were
introduced. Active-user/private-chat checks apply to commands, callbacks and
text input.

## Defaults and owner bootstrap

New users receive empty keywords, skills, blacklist, employment and experience
lists; allowed_regions=[worldwide]; eight enabled sources (USAJOBS remains
opt-in); Remote only ON and Exclude US-only OFF; tolerance ±2h; no minimum salary or
currency restriction. Empty region preferences mean any region. ORM and service
defaults agree.

No owner-specific profession or geography profile is bootstrapped. Existing
saved rows are never overwritten, including custom owner rows. Reset uses the
neutral defaults and leaves notification settings and subscription unchanged.
The first /filters or digest lazily initializes a persisted active user.
Existing public /start onboarding behavior is preserved.

## Telegram UI and callbacks

The main /filters message shows all saved search fields, followed by buttons for
Keywords, Required skills, Preferred skills, Excluded skills, Regions, Employment,
Experience, Salary, Sources, Blacklist, Timezone tolerance and Reset filters.
Digest time, minimum score, notification timezone and plan are absent. All
menus, prompts and successful updates reuse editMessageText. Reset first asks
`Reset all job filters to defaults?` and requires Yes, reset; Cancel preserves
the values.

| Callback data | Behavior |
| --- | --- |
| `filters:back` | Main screen; also cancels pending input |
| `filters:keywords`, `filters:reqtech`, `filters:preftech`, `filters:extech` | List editors |
| `filters:<list>:add`, `filters:<list>:remove`, `filters:<list>:clear` | Add/remove text input or immediate clear |
| `filters:regions` | Region and remote restriction menu |
| `filters:regions:<region>` | Toggle a canonical allowed region |
| `filters:remote_only`, `filters:exclude_us_only` | Toggle booleans |
| `filters:employment`, `filters:employment:<type>` | Employment menu/toggle |
| `filters:experience`, `filters:experience:<level>` | Experience menu/toggle |
| `filters:salary`, `filters:min_salary`, `filters:salary:clear` | Salary menu, text amount, clear amount |
| `filters:currency`, `filters:currency:<code/Any/Other>` | Currency menu/selection |
| `filters:sources`, `filters:sources:<source>` | Active collector menu/toggle |
| `filters:blacklist` | Words/Companies menu |
| `filters:blacklist_words`, `filters:blacklist_companies` | Blacklist list editors; also use add/remove/clear |
| `filters:tz_tol`, `filters:tz_tol:<0..4>` | Tolerance menu/selection |
| `filters:reset`, `filters:reset:confirm` | Reset confirmation/commit |

Canonical region options: worldwide, americas, north_america, latam, south_america,
europe, eu, emea, apac, asia, africa, oceania. Specific countries supports names or
ISO codes through Add/Remove/Clear; Uruguay is an ordinary country. Employment: full_time, part_time,
contract, freelance, internship. Experience: junior, middle, senior, lead,
staff, principal. Sources: all nine registered collectors, with USAJOBS initially disabled.

Empty region, employment and experience preferences mean Any. The last source
cannot be disabled: `At least one source must be enabled.` Salary accepts ASCII
integer digits >=0 within PostgreSQL INTEGER range; `$2500`, `2500 USD`, `2.5k`
and negative amounts are rejected. Clear removes the amount while retaining
currency; Any currency stores None. No conversion is performed. Existing
treatment of missing vacancy metadata remains unchanged.

All basic job filters are available to Free, Trial and Premium users. Only the
already existing custom notification time/score remain subject to entitlements.
Feedback `save:`/`reject:` and notification `settings:`/`tz:`/`time:`/`score:`
callbacks retain their separate handlers.

## Pending input and validation

Redis key: `telegram:user:<telegram_id>:pending_input`. JSON stores the action,
add/remove operation and original menu message ID with a 600-second TTL.
Pending actions are filters:keywords, filters:reqtech, filters:preftech,
filters:extech, filters:min_salary, filters:blacklist_words and
filters:blacklist_companies. No raw input text is retained in Redis.

Plain messages are processed only for that authenticated user and a live state.
Slash commands take precedence, including commands addressed to another bot.
/cancel clears state and replies `Input cancelled.` Opening /filters and filter
menu navigation also clear pending input. Validation errors keep it active for
correction. Expired or corrupt state is ignored/cleared. Committed input clears
state before the menu edit, so an edit failure does not replay a list operation.

Lists trim, lowercase, remove empty values, deduplicate and preserve order.
Technologies reuse normalize_technology, including Postgres/Postgre SQL,
Fast API, JS, node.js, C++ and C#. Adding exclusions removes matching required
and preferred entries. Adding an excluded technology back to required/preferred
requires removing its exclusion first. Companies use exact case-insensitive
matching, without fuzzy matching. Input/list sizes are bounded, and menus fit
Telegram text/callback limits. Errors and logs do not expose raw inputs or
credentials.

## Saved example and local scenario

The local scenario used a fake Telegram client and real PostgreSQL in a unique
test schema. It opened /filters, entered the requested profile through callbacks
and pending text, tried an invalid salary then corrected it, used /cancel,
created fresh polling handlers/sessions and a new Redis store instance, and
verified this saved profile:

```json
{
  "keywords": ["python"],
  "required_technologies": ["python"],
  "preferred_technologies": ["fastapi", "postgresql", "redis"],
  "excluded_technologies": [],
  "allowed_regions": ["worldwide", "latam", "south_america", "uruguay"],
  "remote_only": true,
  "exclude_us_only": true,
  "employment_types": ["full_time", "contract"],
  "experience_levels": ["junior", "middle"],
  "min_salary": 2500,
  "currency": "USD",
  "sources": ["remoteok", "weworkremotely", "getonboard"],
  "blacklisted_words": [],
  "blacklisted_companies": [],
  "timezone_tolerance_hours": 2
}
```

The following reopened English screen was a historical saved custom profile,
not the new-user defaults. It used Python-related filters and four selected
regions. Existing saved profiles remain intact; new accounts receive neutral
lists and no region restriction.

The owner /digest command was tested with a fake dispatcher, then the actual
DailyDigestService processed a matching database vacancy using the saved row
and fake Telegram client. A second /digest reported `Digest already sent
today.` without dispatching again. In a separate next-day test, an already sent
vacancy remained excluded. Actual polling processes were not launched, and no
live Telegram or VPS calls were made during this stage; the scenario simulates
restart by reconstructing the polling state holders and database sessions.

## Per-user digest evidence

With one Python vacancy and persisted filters:

| User | Required technology | Accepted | Filter rejected | Job cards |
| --- | --- | ---: | ---: | ---: |
| A | python | 1 | 0 | 1 |
| B | javascript | 0 | 1 | 0 |

This test invokes the actual digest, filtering, scoring, reservation and
notification services against migrated PostgreSQL. Only fake Telegram receives
messages. Separate persistence testing confirms the saved preferred Redis technology and
keyword scoring bonuses increase the same vacancy's score by 7 (+4/+3) without
changing scoring rules. No sent-job or daily reservation uniqueness changed.

## Validation

- Ruff: `poetry run ruff check .` passed.
- Black: `poetry run black --check .` passed.
- Full pytest with TEST_DATABASE_URL set securely to the local dedicated test
  database: **855 passed**, including **26 PostgreSQL integration cases** and
  **829 unit cases**, with no skipped cases.
- Integration tests create/drop only their owned schemas, run actual migrations,
  test arrays/FK/unique/check constraints, concurrent bootstrap/list edits,
  rollback/reset, metadata parity, per-user digest delivery and restart behavior.
- Fake Redis tests cover set/read/clear, user isolation, corruption, restart
  and TTL configuration. Expiration is simulated without requiring real Redis.
- `git diff --check` passed; new project files and UI text are English.

## Deployment and Git

No commit, push, production deployment, production migration or `.env` change
was performed. Application migrations ran only inside isolated local integration
test schemas. HEAD remains `8544603` on main; the changes are available in the
working tree for review. The initialized VPS update command is:

```bash
./scripts/deploy.sh
```

The script synchronizes project files excluding `.env`, builds the production
image, keeps PostgreSQL/Redis volumes, stops application writers, runs
`docker compose -f docker-compose.production.yml run --rm --no-deps -T api poetry run alembic upgrade head`,
then starts all services. Do not use `down -v` or replace the server environment.
The command is prepared here and has not been executed for this change.

BotFather public menu, prepared for manual configuration:

```text
start - About the bot
help - Show available commands
status - Bot and collector status
saved - Saved jobs
filters - Job search filters
settings - Notification settings
cancel - Cancel current input
```

The owner-only collect/digest/stats commands remain outside the public menu.

Git diff --stat (tracked changes; new files appear in status below):

```text
 README.md                                    | 103 ++++++++++++++++++++++++---
 src/bot/commands.py                          |  60 +++++-----------
 src/bot/updates.py                           |  10 +++
 src/models/__init__.py                       |   2 +
 src/scripts/telegram_polling.py              |  24 +++++--
 src/services/default_filters.py              |   2 +-
 src/services/digests.py                      |   6 +-
 tests/bot/test_commands.py                   |  35 +++++----
 tests/integration/test_postgres_hardening.py |   2 +-
 tests/services/test_digests.py               |   6 ++
 10 files changed, 168 insertions(+), 82 deletions(-)
```

Git status --short --branch:

```text
## main...origin/main
 M README.md
 M src/bot/commands.py
 M src/bot/updates.py
 M src/models/__init__.py
 M src/scripts/telegram_polling.py
 M src/services/default_filters.py
 M src/services/digests.py
 M tests/bot/test_commands.py
 M tests/integration/test_postgres_hardening.py
 M tests/services/test_digests.py
?? docs/user-filters-report.md
?? migrations/versions/c41a9e327b60_add_persistent_user_filters.py
?? src/bot/filters.py
?? src/bot/pending_input.py
?? src/models/user_filter.py
?? src/repositories/user_filters.py
?? src/services/user_filters.py
?? tests/bot/test_job_filter_menu.py
?? tests/bot/test_pending_input.py
?? tests/conftest.py
?? tests/integration/test_persistent_filters_postgres.py
?? tests/services/test_user_filters.py
```

Global currency input accepts three ASCII letters (stored uppercase), with eight
presets, Other and Any. /settings includes global timezone presets plus custom
IANA input validated by ZoneInfo. Pending input now also includes countries,
custom currency and custom timezone. EN/ES labels are Skills/Habilidades; examples
include design, sales and accounting. See [the universal matching report](universal-matching-report.md).
