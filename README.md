# Job Hunter Bot

A Telegram bot that finds remote jobs from **Remote OK**, **We Work Remotely**,
**Get on Board** and **Himalayas**. It filters jobs by your preferences and sends
daily digests.

- Personal filters for technologies, keywords, regions, salary and experience.
- Match scoring, saved vacancies and feedback buttons.
- English and Spanish interface, with a saved language preference.

Built with Python, FastAPI, PostgreSQL, Redis and Celery.

## Local setup

Requires Python 3.12+, Poetry and Docker Compose.

1. Install dependencies with `poetry install`.
2. Create `.env` from [`.env.example`](.env.example) if it does not exist.
   Set database credentials, `TELEGRAM_BOT_TOKEN` and the owner's
   `TELEGRAM_CHAT_ID`.
3. Start the databases and apply migrations:

```bash
docker compose up -d --wait postgres redis
poetry run alembic upgrade head
```

Run each process in a separate terminal:

```bash
poetry run celery -A src.tasks.celery_app:celery_app worker -l INFO
```

```bash
poetry run celery -A src.tasks.celery_app:celery_app beat -l INFO
```

```bash
poetry run python -m src.scripts.telegram_polling
```

Keep one Beat and one polling process per bot, including across local and VPS
instances. Open the bot in Telegram and send `/start`.

Optional API: `poetry run uvicorn src.main:app --reload` (`GET /health`).

## Telegram commands

| Command | Purpose |
| --- | --- |
| `/start` | Register and choose a language, or show an introduction |
| `/help` | List available commands |
| `/filters` | Edit your job search filters |
| `/settings` | Change language, timezone and digest settings |
| `/status` | View bot and delivery status |
| `/saved` | View saved vacancies |
| `/cancel` | Cancel pending input |
| `/digest` | Get new matching vacancies now — owner only |
| `/collect` | Run job collectors — owner only |
| `/stats [24h\|7d\|30d]` | View pipeline statistics — owner only |

Manual digests can run repeatedly in the same day. Already sent vacancies are
excluded; the bot replies when no new jobs match your filters.

## Telegram interface language

Choose **English** or **Español** through `/settings`. The selection is saved
and applied immediately. Existing accounts default to English; vacancy content
stays in its original language. [Language menus and BotFather lists](docs/project-guide.md#telegram-interface-language).

## Checks

```bash
poetry run ruff check .
poetry run black --check .
poetry run pytest
```

PostgreSQL integration tests require `TEST_DATABASE_URL` pointing to a dedicated
test database (`postgresql+asyncpg://...`). They are skipped when it is unset.

## Deployment

For an initialized VPS with its own `.env`, update from the local checkout:

```bash
./scripts/deploy.sh
```

The script transfers source, builds the image, applies migrations and restarts
services while preserving `.env` and persistent volumes.
[First deployment and configuration](docs/project-guide.md#vps-deployment).

## Documentation

- [Project guide](docs/project-guide.md): configuration, collectors, scheduling and deployment.
- [User filters](docs/user-filters-report.md) and [notification settings](docs/telegram-settings-report.md).
- [Interface languages](docs/telegram-language-report.md) and [manual digests](docs/manual-digest-report.md).
- [Reliability and delivery guarantees](docs/hardening-review-report.md).
