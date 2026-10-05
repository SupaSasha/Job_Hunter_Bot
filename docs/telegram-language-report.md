# Telegram interface language implementation

## Result and scope

English and Spanish are persisted per user and applied immediately to Telegram
commands, settings, all filter editors and pending input, validation errors,
feedback, saved jobs, status, digest summaries, job cards and subscription labels.
The original UI inventory is in [telegram-string-inventory.md](telegram-string-inventory.md).
Spanish uses modern Latin American wording, with restrained Uruguay-compatible
voseo and no regional slang. No translation service or new dependency was added.

Language selection is free on every plan. Premium capability checks, collector
control, scheduling, filtering, scoring, salary rules, daily reservations and
notification uniqueness are unchanged. Manual /digest, /collect and /stats
remain owner-only. Technical /stats body terminology remains English, as allowed
by the task; its command help and errors are localized.

## Storage and migration

- `src/models/user.py`: `UserORM.language`, stored as canonical `en` or `es`.
- Python/server default: `en`; column: `VARCHAR(2) NOT NULL`.
- Database constraint: `ck_users_language` accepts only `en` and `es`.
- Revision: `e93b6472a105`, following `c41a9e327b60`, in
  `migrations/versions/e93b6472a105_add_user_interface_language.py`.
- Upgrade adds the column with the English server default for existing users;
  it preserves user IDs, existing usernames, active state and related data.
- Downgrade refuses to discard a saved non-English preference before removing
  the column. Operators must deliberately reset those preferences first.

`UserLanguageService` performs registration and transactional preference writes.
Registration reuses `OwnerService.get_or_create` and missing-only delivery
bootstrap defaults. Repeated /start never overwrites notification preferences,
renews an expired trial or reactivates an inactive user.

New /start users receive a bilingual picker. Telegram `from.language_code`
starting with `es` (including `es-UY`) initializes Spanish on creation; otherwise
English is used. Existing users use their saved language, regardless of later
Telegram language changes. Existing users migrated from the previous schema
start in English. Unknown-user replies use the Telegram-language fallback.

## Translation API and files

- `src/i18n/translator.py`: `Language.EN`, `Language.ES`, default/supported
  locales, `translate` / `t`, persisted-user resolution, display/status labels
  and localized validation errors.
- `src/i18n/en.py`, `src/i18n/es.py`: lightweight Python dictionary catalogs.
- `src/i18n/scoring.py`: translates known score explanations for presentation;
  the original score result, rule evaluation and numeric score are unchanged.
- Builders and formatters accept `language`; handlers reuse the loaded user,
  without a separate language query for each label or button.

```python
from src.i18n import Language, t, translate

text = translate("language.menu", Language.ES, name="Español")
summary = t("digest.summary", Language.ES, count=1, matches="82 — Example job")
```

Interpolation belongs to the translator. A missing Spanish entry falls back to
English. A key absent from English raises `TranslationError`, a programming
error, rather than displaying the raw key. Unsupported locale input resolves
to English; database writes enforce the supported canonical codes.

There are **235 English keys and 235 Spanish keys**. Automated tests
require exact EN/ES key parity and matching interpolation fields, and separately
exercise the Spanish-to-English fallback.

## Callback and content contract

The language namespace is `settings:language`, `settings:language:en`,
`settings:language:es`. Selection persists first, calls `answerCallbackQuery`,
and then redraws settings in the chosen language. Restart is unnecessary.
The language menu also works if notification settings are unavailable.

Existing callback data is identical between locales, including
`filters:employment:full_time`, `filters:experience:middle`,
`filters:regions:worldwide`, `save:42` and `reject:42`. Slash command names,
job URLs and source identifiers also remain unchanged. Tests compare both
languages' complete settings/filter keyboards and callback sizes.

Employment, experience, region and subscription display labels are translated;
canonical database values are unchanged. Source brands remain Remote OK,
We Work Remotely and Get on Board. Vacancy title, company, description,
technology data and currency are not translated. Descriptions are not included
in the existing concise Telegram card. Existing technology display styling is
identical in both languages. No AI, LLM, Google Translate, DeepL or other
translation API is used. Unknown custom score explanations retain their original
text rather than changing job data.

An empty scheduled digest still sends no summary or card. A manual /digest
response for today's empty run now gives a localized no-matching-jobs message;
the daily attempt remains consumed, preserving existing reservation behavior.

## Actual builder examples

The following screens are generated from the application builders using safe
synthetic data, not copied from a live Telegram account.

### New-user /start (both locales)

```text
Choose your language / Elegí tu idioma

[🇬🇧 English]
[🇪🇸 Español]
```

### Existing-user /start — en

```text
Job Hunter Bot

I search for remote jobs, filter them based on your preferences, calculate a match score, and send the best matches in a daily digest.

Use /help to see available commands.
```

### /settings — en

```text
⚙️ Settings

🌐 Language:
English

Timezone:
America/Montevideo

Daily digest:
09:00

Minimum match score:
70%

Plan:
Free

🔔 Daily digest: Enabled

Custom digest time 🔒

Custom minimum score 🔒

[🌐 Language]
[🌎 Timezone]
[🕐 Digest time]
[🎯 Minimum score]
[← Back]
```

### Language menu — en

```text
🌐 Language

Current: English

[🇬🇧 English ✅]
[🇪🇸 Español]
[← Back]
```

### /filters — en

```text
🔎 Job filters

Keywords:
python
backend

Required technologies:
python

Preferred technologies:
fastapi
postgresql

Excluded technologies:
None

Blacklisted words:
None

Blacklisted companies:
None

Regions:
Worldwide
LATAM
South America
Uruguay

Employment:
Full-time
Contract

Experience:
Junior
Middle

Sources:
Remote OK
We Work Remotely
Get on Board

Remote only: ✅ Yes

Exclude US-only: ✅ Yes

Minimum salary:
USD 2500

Timezone tolerance: ±2h

[🔎 Keywords]
[🧰 Required tech]
[⭐ Preferred tech]
[🚫 Excluded tech]
[🌎 Regions]
[💼 Employment]
[📈 Experience]
[💰 Salary]
[📡 Sources]
[🚫 Blacklist]
[🕐 Timezone tolerance]
[Reset filters]
```

### Job notification — en

```text
🔥 Match: 82%

Backend Python Developer

Company: Example Labs

💰 Salary: 40,000–60,000 USD / year
🌎 Region: Remote · Worldwide, LATAM
🕐 Employment: Full-time

Technologies:
🐍 Python
⚡ FastAPI
🐘 PostgreSQL

Experience: Middle
Source: Remote OK

Matches:
✅ Remote job

[Open vacancy]
[Save] | [Not suitable]
```

### Existing-user /start — es

```text
Job Hunter Bot

Busco vacantes remotas, las filtro según tus preferencias, calculo su compatibilidad y te envío las mejores en un resumen diario de vacantes.

Usá /help para ver los comandos disponibles.
```

### /settings — es

```text
⚙️ Configuración

🌐 Idioma:
Español

Zona horaria:
America/Montevideo

Resumen diario:
09:00

Puntaje mínimo de compatibilidad:
70%

Plan:
Gratis

🔔 Resumen diario: Activado

Horario personalizado del resumen 🔒

Puntaje mínimo personalizado 🔒

[🌐 Idioma]
[🌎 Zona horaria]
[🕐 Resumen diario]
[🎯 Puntaje mínimo]
[← Volver]
```

### Language menu — es

```text
🌐 Idioma

Actual: Español

[🇬🇧 English]
[🇪🇸 Español ✅]
[← Volver]
```

### /filters — es

```text
🔎 Filtros de empleo

Palabras clave:
python
backend

Tecnologías requeridas:
python

Tecnologías preferidas:
fastapi
postgresql

Tecnologías excluidas:
Ninguna

Palabras excluidas:
Ninguna

Empresas excluidas:
Ninguna

Regiones:
Todo el mundo
Latinoamérica
Sudamérica
Uruguay

Tipo de empleo:
Tiempo completo
Contrato

Experiencia:
Junior
Intermedio

Fuentes:
Remote OK
We Work Remotely
Get on Board

Solo remoto: ✅ Sí

Excluir vacantes solo para EE. UU.: ✅ Sí

Salario mínimo:
USD 2500

Tolerancia horaria: ±2h

[🔎 Palabras clave]
[🧰 Tecnologías requeridas]
[⭐ Tecnologías preferidas]
[🚫 Tecnologías excluidas]
[🌎 Regiones]
[💼 Tipo de empleo]
[📈 Experiencia]
[💰 Salario]
[📡 Fuentes]
[🚫 Lista de exclusión]
[🕐 Tolerancia horaria]
[Restablecer filtros]
```

### Job notification — es

```text
🔥 Compatibilidad: 82%

Backend Python Developer

Empresa: Example Labs

💰 Salario: 40,000–60,000 USD / año
🌎 Región: Remoto · Todo el mundo, Latinoamérica
🕐 Tipo de empleo: Tiempo completo

Tecnologías:
🐍 Python
⚡ FastAPI
🐘 PostgreSQL

Experiencia: Intermedio
Fuente: Remote OK

Coincidencias:
✅ Remote job

[Ver vacante]
[Guardar] | [No me interesa]
```

## Validation

Final full suite: **912 passed in 34.46 seconds**, including **31 real PostgreSQL
integration cases** and **881 unit cases**. No integration test was skipped in
this run. Ruff, Black and whitespace validation are recorded below.

Translator tests cover both languages, interpolation, missing keys, fallback,
key/placeholder parity, locale initialization and score-explanation presentation.
UI tests cover /start, /settings, /filters, /help, /status, /saved, /digest,
/cancel, native language buttons, instant redraw, authorization, all filter
callbacks, pending-input prompts/errors, feedback and immutable job data.

The PostgreSQL tests run real Alembic upgrades in disposable, UUID-named schemas
of the dedicated `job_hunter_review_test` database. They cover existing-user
English backfill, database constraints, saved-language reload, safe repeated
registration, unchanged trial/preferences, two users receiving the same scored
job through real filtering/digest services with different presentation, and a
complete EN → ES → EN interaction scenario.

The interaction scenario uses fake Telegram clients: /start, language selection,
/settings, /filters, /help, /status, /saved, /digest, pending validation and
successful input. It then creates fresh handlers, repositories and database
sessions, verifies the saved choice and confirms Telegram `es` cannot overwrite
explicit English. This tests restart persistence without restarting a live
polling process. A live Telegram/manual polling-restart check was not performed.
No production service or production database was changed.

Checks used:

```bash
poetry run ruff check .
poetry run black --check .
poetry run pytest
```

The full pytest run had `TEST_DATABASE_URL` configured for the dedicated test
database. Without that variable the integration fixture intentionally skips
PostgreSQL cases. No credentials are included in this report.

## Deployment preparation and Git

No commit, push or deployment was performed. Changes remain local for review.
Migration must run before starting updated application processes. The existing
`scripts/deploy.sh` uses the `api` service for Alembic upgrades and preserves
production `.env` and persistent volumes. For a separately authorized deployment:

```bash
docker compose run --rm api poetry run alembic upgrade head
docker compose up -d
```

Both English and Spanish BotFather command-description lists are in the
[README language section](../README.md#telegram-interface-language). The application
does not update BotFather. Because /digest remains owner-only, its menu entry
belongs to an owner-scoped command list; omit it from a general-user menu.

Portuguese, vacancy translation, payments, collectors and analytics are outside
this change.

## Final check results and working tree

- `poetry run ruff check .`: all checks passed.
- `poetry run black --check .`: 145 files would be left unchanged.
- `git diff --check`: passed, no whitespace errors.
- Final `poetry run pytest`: 912 passed, including 31 PostgreSQL cases.
- HEAD remains `1af7215`; branch `main` tracks `origin/main` with no new commit.
- `.env` is absent from the changed/untracked file list.

`git diff --stat` (tracked files only; new files are shown in status below):

```text
 README.md                                          |  96 +++++-
 src/bot/callbacks.py                               |  22 +-
 src/bot/commands.py                                | 209 +++++++-----
 src/bot/filters.py                                 | 365 ++++++++++++---------
 src/bot/formatter.py                               |  94 +++---
 src/bot/settings.py                                | 303 +++++++++++------
 src/models/user.py                                 |  19 +-
 src/repositories/scheduling.py                     |  45 +--
 src/repositories/users.py                          |  18 +-
 src/scripts/telegram_polling.py                    |   3 +
 src/services/digests.py                            |  11 +-
 src/services/notification_settings.py              |   9 +-
 src/services/notifications.py                      |   6 +-
 src/services/user_filters.py                       |  27 +-
 src/services/users.py                              |  12 +-
 tests/bot/test_commands.py                         |  24 +-
 tests/bot/test_formatter.py                        |   4 +-
 .../test_persistent_filters_postgres.py            |  18 +-
 tests/integration/test_postgres_hardening.py       |   2 +-
 19 files changed, 832 insertions(+), 455 deletions(-)
```

`git status --short --branch`:

```text
## main...origin/main
 M README.md
 M src/bot/callbacks.py
 M src/bot/commands.py
 M src/bot/filters.py
 M src/bot/formatter.py
 M src/bot/settings.py
 M src/models/user.py
 M src/repositories/scheduling.py
 M src/repositories/users.py
 M src/scripts/telegram_polling.py
 M src/services/digests.py
 M src/services/notification_settings.py
 M src/services/notifications.py
 M src/services/user_filters.py
 M src/services/users.py
 M tests/bot/test_commands.py
 M tests/bot/test_formatter.py
 M tests/integration/test_persistent_filters_postgres.py
 M tests/integration/test_postgres_hardening.py
?? docs/telegram-language-report.md
?? docs/telegram-string-inventory.md
?? migrations/versions/e93b6472a105_add_user_interface_language.py
?? src/i18n/
?? src/services/user_language.py
?? tests/bot/test_localized_interface.py
?? tests/integration/test_user_language_postgres.py
?? tests/services/test_translator.py
```
