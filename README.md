# Job Hunter Bot

Minimal FastAPI project foundation for a Telegram job search bot.

## Local persistence

Install dependencies with `poetry install`. Copy `.env.example` to `.env` on a
fresh checkout, preserving any existing settings. PostgreSQL credentials are
read from `DB_USER`, `DB_PASS`, and `DB_NAME`; the Compose service maps these to
`POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB`.
The example password is for local development only.

```bash
docker compose up -d postgres --wait
docker compose ps
poetry run alembic upgrade head
poetry run alembic current
poetry run python -m src.scripts.collect_remoteok
```

Run the collection command again to verify that known jobs are reported as
`duplicates`. The output contains `received`, `saved`, and `duplicates`; an empty
source response logs a warning because it does not verify persistence.
If port 5432 is occupied, set `DB_PORT=5433` (or another free port) in `.env`.
The database port inside the container remains 5432. Data lives in the named
`job-hunter-bot_postgres_data` volume. Changing credentials in `.env` does not
change credentials in an already initialized PostgreSQL volume.

The application still runs locally:

```bash
poetry run uvicorn src.main:app --reload
```

`GET /health` returns `{"status": "ok"}` without a database query.

## Persistence contract

The script runs `RemoteOKCollector -> NormalizationService -> JobSaveService ->
PostgreSQL`. Filtering and scoring remain separate, subsequent business steps.
`JobDTO` stays independent of the ORM. `job_to_orm` copies DTO fields and converts
aware timestamps to UTC; naive timestamps are rejected.

- `JobRepository(session)` exposes async `get_by_source_external_id(source,
  external_id)`, `get_by_fingerprint(fingerprint)`, and `add(job)`. It flushes
  inserts but never commits. Fingerprint lookup returns the first row by ID.
- `DeduplicationService(repository).check(job)` checks source/external ID first,
  then fingerprint. Its result includes `is_duplicate`, `reason`,
  `existing_job_id`, and the fingerprint when calculated.
- `DeduplicationService.calculate_fingerprint(job)` hashes a UTF-8 JSON pair of
  canonical company and title with SHA-256. Canonicalization lowercases, removes
  dots/commas/apostrophes, converts simple punctuation and underscores to spaces,
  converts `&` to `and`, and collapses whitespace. `+` and `#` remain meaningful.
  Company suffixes and seniority words stay intact. A missing company becomes an
  empty string. Displayed DTO fields are unchanged.
- `JobSaveService(session).save_if_new(job)` returns `JobSaveResult` with
  `status` (`saved` or `duplicate`), `job_id`, and optional `reason`.
  It owns one transaction per call: commit on insert, rollback on a duplicate or
  error. Use a dedicated session without unrelated pending work, and a separate
  session per concurrent task. A conflict on `uq_jobs_source_external_id` is
  rolled back and resolved to the existing row; other integrity errors propagate.

The `jobs` table has a primary key, `UNIQUE(source, external_id)`, and a
non-unique `ix_jobs_fingerprint` index. Fingerprint matching is an MVP heuristic:
identical company/title pairs (especially missing companies) can suppress
separate openings. Concurrent inserts with different source IDs and identical
fingerprints can both succeed; only source identity has a database uniqueness
guarantee. No fuzzy matching or distributed locking is used.

`remote_regions` and `technologies` use PostgreSQL string arrays. All timestamps
use `TIMESTAMP WITH TIME ZONE`. `created_at` and `updated_at` default to database
`now()`; SQLAlchemy updates `updated_at` on updates through the mapped table.
Raw SQL updates must set `updated_at` explicitly. Publication, collection, and
persistence timestamps retain separate meanings. There is no vacancy score.

## Checks

```bash
poetry run ruff check .
poetry run black --check .
poetry run pytest
poetry run alembic check
```

Unit tests use standard-library mocks and do not require PostgreSQL. Migration
application, repeated collection, and a manual concurrent insert exercise the
real database; there is no separate integration database stack at this stage.
