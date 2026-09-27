# Результат этапа: scheduling и daily digest

Проверено 27 сентября 2026 года. Реализована архитектура из последнего задания:
collection сохраняет вакансии, delivery формирует отдельный ежедневный digest.
Commit и push не выполнялись. Файл `.env` не изменялся.

## Зависимости и инфраструктура

- Celery 5.6.3: `celery >=5.6.3,<6.0.0`.
- redis-py 8.1.0: `redis >=8.1.0,<9.0.0`.
- Обновлены pyproject.toml и poetry.lock. RabbitMQ не добавлялся.
- Redis 7 в Compose, loopback 6379, healthcheck, AOF и persistent volume.
- PostgreSQL 16: loopback 5433 → внутренний 5432.
- Worker, Beat, polling и FastAPI остаются локальными Poetry-процессами.

Redis PING: **PONG**.

Результат `docker compose ps`:

```text
NAME                        IMAGE         SERVICE    STATUS             PORTS
job-hunter-bot-postgres-1   postgres:16   postgres   Up (healthy)       127.0.0.1:5433->5432/tcp
job-hunter-bot-redis-1      redis:7       redis      Up (healthy)       127.0.0.1:6379->6379/tcp
```

## Модели и миграция

Модели собраны в `src/models/scheduling.py` и зарегистрированы в metadata:

| Модель / таблица | Данные |
| --- | --- |
| CollectorStateORM / collector_states | unique source, last_started_at, last_success_at, last_finished_at, next_run_at, last_status, last_error, created_at, updated_at |
| UserNotificationSettingsORM / user_notification_settings | unique user_id FK, timezone IANA, digest_time TIME без timezone, min_score, digest_enabled, max_jobs_per_digest, created_at, updated_at |
| UserSubscriptionORM / user_subscriptions | unique user_id FK, trial/active/expired, trial_started_at, trial_ends_at, subscription_started_at, subscription_ends_at, created_at, updated_at |
| DigestRunORM / digest_runs | unique (user_id, local_date), pending/empty/sent/partial/failed, started_at, finished_at, summary_message_id, selected/sent/failed/skipped, last_error, created_at, updated_at |

Все timestamps timezone-aware; расчёты и сохранение используют UTC.
Local digest time и local calendar date имеют отдельные типы TIME и DATE.
NotificationORM с UNIQUE(user_id, job_id) сохранена без изменения семантики.

Миграция `54383f510932` следует за `664c622669e5`.
Автогенерация прочитана, upgrade выполнен, `alembic current`:
**54383f510932 (head)**. `alembic check`: **No new upgrade operations detected**.

## Collection и сохранённый jitter

Реально зарегистрирован только Remote OK. Окна в application timezone
America/Montevideo: **02:00–04:00, 10:00–12:00, 18:00–20:00**.
Пользовательская timezone и подписка не влияют на сбор.

Stdlib random.randrange выбирает секунду внутри следующего окна, исключая
правую границу. Первый запуск допускает остаток текущего окна. После успешного
сбора выбирается следующее окно. Результат сохраняется в next_run_at один раз;
обычные ticks и restart его не пересчитывают.

Диспетчер выбирает next_run_at <= now и только публикует задачу. Задача получает
expected_next_run, поэтому старый дубликат очереди пропускается после изменения
расписания. При ошибке следующая попытка назначается через час, без немедленных
повторов; retry может находиться вне обычных окон.

Redis lock `collector:remoteok:lock` имеет ownership token и TTL 660 секунд;
освобождение выполняется атомарным сравнением токена через redis-py.
Основная async-работа ограничена 510 секундами, полная service call — 600.
Celery soft/hard limits: 540/600 секунд.

API:

```python
await JobPipeline(save_service).run(jobs)
# CollectionResult(received, new, duplicates, failed)

await CollectionService(sessions, redis, timezone).collect_remoteok(
    expected_next_run=None,
)
```

Collection не вызывает FilterService, ScoringService и Telegram.
HTTP/JSON ошибки больше не выглядят как успешный пустой ответ.

## Celery и Beat

Celery timezone — UTC; broker и result backend — вычисляемый REDIS_URL.
JSON serializers, UTC timestamps, отдельные async engine/Redis client на каждый
asyncio.run, корректное закрытие ресурсов.

| Task name | Запуск |
| --- | --- |
| scheduler.dispatch_collectors | Beat каждые 15 минут |
| scheduler.dispatch_digests | Beat каждые 5 минут |
| jobs.collect_remoteok | Только по due state или ручному запросу |
| notifications.send_daily_digest | Для конкретного due user_id |

Все четыре задачи зарегистрированы и проверены у живого worker.
Отдельных Beat-записей на пользователей нет. Polling остаётся отдельным процессом.
Из-за частоты dispatcher фактический collector может стартовать примерно до
15 минут после next_run_at, digest — обычно в течение 5–10 минут после времени,
с учётом нагрузки очереди.

## Digest API и гарантии

```python
await DailyDigestService(sessions, client, entitlements).send(
    user_id, expected_date=None,
)
```

Candidates выбираются через NOT EXISTS NotificationORM(user_id, job_id),
а не только по created_at. Поэтому старые не показанные вакансии и остаток
подборки после лимита остаются доступны позже.

JobORM → JobDTO → прежний FilterService → прежний ScoringService →
score DESC с устойчивым порядком ID при равенстве → effective threshold и limit.
Scoring алгоритм не изменён. `default_user_filters(timezone)` сохраняет прежний
профиль Python/remote/Worldwide/LATAM/South America/Uruguay, исключая US-only.
Настройки фильтров пока общие, без новой filter persistence системы.

До первого HTTP-запроса PostgreSQL фиксирует digest_runs с уникальной
(user_id, local_date). Это защищает summary и карточки от повторного запуска
за день, в том числе при конкурирующих Celery tasks.
Пустой digest получает empty и ничего не отправляет.
Непустой: короткий summary с top-5, затем существующие карточки через
NotificationService. Лимит относится к карточкам, summary добавляет одно сообщение.

Индивидуальные уведомления сохраняют прежние pending/sent/failed записи.
Успешные сообщения не повторяются; ambiguous timeout не запускает автоповтор.
При частичном успехе daily run получает partial, при неуспехе — failed.
После аварийной остановки он может остаться pending; этот статус тоже закрывает
попытку текущего дня. Гарантия — максимум одна попытка digest за локальную дату,
а не гарантированная доставка всех сообщений: Telegram и БД не имеют общей
транзакции. Не начатые индивидуальные отправки остаются кандидатами на другой день.

## Preferences, trial и effective settings

Новые Settings и .env.example:

```dotenv
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
SCHEDULER_TIMEZONE=America/Montevideo
TRIAL_DAYS=7
FREE_DIGEST_TIME=09:00
FREE_MIN_SCORE=70
FREE_MAX_JOBS_PER_DIGEST=10
```

Вычисляемый REDIS_URL: redis://localhost:6379/0.
FREE_DIGEST_TIME валидируется как локальный Python time.
Прежние MIN_NOTIFICATION_SCORE/MAX_NOTIFICATIONS_PER_RUN принимаются для
совместимости, но больше не управляют pipeline/digest.

Bootstrap в polling startup и digest dispatcher создаёт отсутствующие настройки
и семидневный trial существующим пользователям, включая owner.
ON CONFLICT DO NOTHING сохраняет пользовательские значения и не продлевает trial.

EntitlementService централизует premium capabilities: custom_digest_time и
custom_min_score. Trial premium при now < trial_ends_at; active premium при
отсутствии subscription_ends_at либо now < subscription_ends_at.
Иначе применяются free 09:00 / 70, без удаления пользовательских значений.
Timezone и сохранённый max_jobs_per_digest не являются premium.

| Пример | Сохранено | Effective |
| --- | --- | --- |
| Активный trial | 11:30 / score 42 | 11:30 / 42 |
| Истёкший trial | 11:30 / score 42 | 09:00 / 70 |
| Активная подписка | 11:30 / score 42 | 11:30 / 42 |
| Free Madrid | timezone Europe/Madrid | 09:00 Europe/Madrid |
| Free Uruguay | timezone America/Montevideo | 09:00 America/Montevideo |

Реальные платежи, preference commands, дополнительные collectors, LLM и ML не
добавлялись.

## Живые проверки

1. Подняты PostgreSQL и Redis, применена миграция, запущены worker и Beat.
2. Collection task `7fb3a2cd-bbc4-4bfd-bda7-bc1da8033ad0` через Redis:
   **received=99, new=1, duplicates=98, failed=0**.
3. Количество jobs выросло **102 → 103**. После collection:
   **notifications=0, digest_runs=0**. Telegram из collection не отправлялся.
4. Collector state: success; назначено next_run_at
   **2026-09-27 21:31:25 UTC**, то есть **18:31:25 America/Montevideo**.
5. Из имеющихся вакансий одна проходила прежний фильтр с score 66. Для проверки
   active trial временно установлены **18:03:01, min_score=66, max_jobs=1**.
6. До пользовательского времени dispatcher возвращал 0.
7. После времени два параллельных dispatcher вернули по 1. Первая digest task
   выполнила отправку, другая вернула `already_attempted_today`.
8. Реальный результат: **digest_runs id=1, date=2026-09-27, status=sent,
   selected=1, sent=1, failed=0**. Telegram принял summary **message_id=8**
   и карточку job_id=47 **message_id=9**. Это подтверждение Telegram API,
   а не утверждение о прочтении сообщений пользователем.
9. Последующий dispatcher вернул **0**; прямой повтор digest task:
   **skipped / already_attempted_today**.
10. Trial временно истёк в реальной БД. При повторном чтении effective settings
    стали **09:00 / 70**, а сохранённые custom **18:03:01 / 66** не изменились.
11. Восстановлены исходные настройки: **09:00 / 70 / max 10**, active trial до
    **2026-10-04 21:01:01.802746 UTC**. Дневная reservation и notification сохранены.

Процессы оставлены запущенными для дальнейшей проверки в Telegram:
worker PID 321738, Beat PID 316543, polling PID 317045.
Логи: /tmp/job-hunter-worker.log, /tmp/job-hunter-beat.log,
 /tmp/job-hunter-polling.log. PID-файлы — /tmp/job-hunter-{worker,beat,polling}.pid.
Worker мягко перезапущен после последней правки; повторный poller не создавался.

Во вспомогательном одноразовом скрипте ожидания результатов возникло сообщение
redis-py/Celery при завершении интерпретатора (AsyncResult.__del__).
Последующие проверки явно освобождали AsyncResult до закрытия приложения и
завершились без этой ошибки; worker и отправка digest не пострадали.

## Проверки качества

- Ruff: **All checks passed**.
- Black --check: **85 files would be left unchanged**.
- pytest: **235 passed** (полный финальный прогон).
- alembic current: **54383f510932 (head)**.
- alembic check: **No new upgrade operations detected**.
- git diff --check: без ошибок.
- Unit tests не требуют настоящих PostgreSQL/Redis/Telegram.

README содержит реальные команды запуска, ручного collection, dispatcher и
проверки зарегистрированных задач, модель гарантий и ограничения доставки.

Использованные официальные справочники:
[Celery periodic tasks](https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html),
[redis-py locks](https://redis.readthedocs.io/en/stable/lock.html),
[SQLAlchemy async engines и event loops](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html#using-multiple-asyncio-event-loops).

## Созданные файлы

```text
docs/scheduling-stage-report.md
migrations/versions/54383f510932_collector_scheduling_daily_digests_and_.py
src/models/scheduling.py
src/repositories/digests.py
src/repositories/scheduling.py
src/services/collection.py
src/services/collector_policy.py
src/services/default_filters.py
src/services/digests.py
src/services/entitlements.py
src/services/locks.py
src/services/scheduler.py
src/tasks/__init__.py
src/tasks/celery_app.py
src/tasks/jobs.py
src/tasks/notifications.py
src/tasks/runtime.py
src/tasks/scheduler.py
tests/collectors/test_remoteok_errors.py
tests/repositories/test_scheduling_repositories.py
tests/services/test_collection.py
tests/services/test_digests.py
tests/services/test_scheduling.py
tests/tasks/test_tasks.py
```

## Изменённые файлы

```text
.env.example
.gitignore
README.md
docker-compose.yml
poetry.lock
pyproject.toml
src/collectors/remoteok.py
src/config.py
src/models/__init__.py
src/scripts/collect_remoteok.py
src/scripts/telegram_polling.py
src/services/pipeline.py
tests/services/test_pipeline.py
tests/test_config.py
```

## git diff --stat

Новые untracked-файлы не включаются Git в эту статистику; они перечислены выше.

```text
 .env.example                    |   9 +
 .gitignore                      |   1 +
 README.md                       | 433 ++++++++++++++++++++++------------------
 docker-compose.yml              |  14 ++
 poetry.lock                     | 314 ++++++++++++++++++++++++++++-
 pyproject.toml                  |   4 +-
 src/collectors/remoteok.py      |  14 +-
 src/config.py                   |  31 +++
 src/models/__init__.py          |  17 +-
 src/scripts/collect_remoteok.py |  65 +-----
 src/scripts/telegram_polling.py |   3 +
 src/services/pipeline.py        |  77 ++-----
 tests/services/test_pipeline.py | 119 +++--------
 tests/test_config.py            |  27 +++
 14 files changed, 709 insertions(+), 419 deletions(-)
```

## git status

```text
## main...origin/main
 M .env.example
 M .gitignore
 M README.md
 M docker-compose.yml
 M poetry.lock
 M pyproject.toml
 M src/collectors/remoteok.py
 M src/config.py
 M src/models/__init__.py
 M src/scripts/collect_remoteok.py
 M src/scripts/telegram_polling.py
 M src/services/pipeline.py
 M tests/services/test_pipeline.py
 M tests/test_config.py
?? docs/scheduling-stage-report.md
?? migrations/versions/54383f510932_collector_scheduling_daily_digests_and_.py
?? src/models/scheduling.py
?? src/repositories/digests.py
?? src/repositories/scheduling.py
?? src/services/collection.py
?? src/services/collector_policy.py
?? src/services/default_filters.py
?? src/services/digests.py
?? src/services/entitlements.py
?? src/services/locks.py
?? src/services/scheduler.py
?? src/tasks/__init__.py
?? src/tasks/celery_app.py
?? src/tasks/jobs.py
?? src/tasks/notifications.py
?? src/tasks/runtime.py
?? src/tasks/scheduler.py
?? tests/collectors/test_remoteok_errors.py
?? tests/repositories/test_scheduling_repositories.py
?? tests/services/test_collection.py
?? tests/services/test_digests.py
?? tests/services/test_scheduling.py
?? tests/tasks/test_tasks.py
```
