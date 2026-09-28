# Telegram commands: implementation and validation

Implemented on September 28, 2026. No commit or push was performed.
All project text remains in English. No dependencies, models or migrations were added.

## Commands and access

| Command | Behavior | Access |
| --- | --- | --- |
| /start | Send the requested introduction | Private chat |
| /help | List all seven commands | Private chat |
| /status | Read collector state, job count and effective daily-delivery settings from PostgreSQL | Existing active user |
| /saved | Show up to ten most recently saved jobs, without descriptions | Existing active user |
| /filters | Show current filters and effective digest time/minimum score | Existing active user |
| /collect | Publish a Remote OK collection task | Configured owner only |
| /digest | Publish today's digest task with immediate execution requested | Configured owner only |

Commands require a private chat whose ID matches the sender ID.
Admin commands compare the sender against Settings.TELEGRAM_CHAT_ID and require
an active database user. Unknown/inactive users cannot read private data.
Unauthorized commands reply `This command is not available.`.
No numeric owner ID is hardcoded. Missing owner configuration disables admin commands.

Startup retains OwnerService.get_or_create for the configured owner and the
existing delivery bootstrap. Public /start and /help do not create arbitrary users.
The callback implementation and the long-polling offset/retry loop are unchanged.

## Public API and routing

```python
handler = CommandHandler(
    users, queries, feedback, client, dispatcher, entitlements,
    owner_telegram_id=owner_id,
    bot_username=bot_username,
)
await handler.handle(message)

await route_update(update, commands=handler, callbacks=callback_handler)
```

CommandHandler lives in src/bot/commands.py. It accepts an injectable clock.
BotQueryRepository contains read-only queries for collector state, total job
count, preferences, subscription and the user's latest digest attempt.

FeedbackRepository.get_saved_jobs_for_user(user_id, limit=10) filters by user and
feedback_type="saved", then sorts by updated_at and ID descending.
Output contains title, company and link only; long lists are split to respect
Telegram's message size limit.

TelegramClient requests both message and callback_query updates.
get_bot_username() uses getMe once at startup to route /command@BotUsername
correctly. Commands addressed to another bot are ignored. Normal text, edited
messages and unrelated updates are ignored. Unknown commands receive:
`Unknown command. Use /help to see available commands.`

## Celery dispatch and delivery behavior

CeleryCommandDispatcher publishes existing tasks in a worker thread:

```python
collect_remoteok.delay()
send_daily_digest.delay(user.id, run_now=True)
```

The handler waits for publication only, never for completion or AsyncResult.get().
It responds with Collection started. or Digest started.
Publication failures are logged by exception type and produce
Failed to start collection. or Failed to start digest.
Raw command arguments, secrets and broker exception text are not logged.
A failed Telegram acknowledgement does not cause the command handler to replay
an already published task.

The optional run_now flag was added to the existing digest task/service. It only
bypasses the scheduled local-time check. It preserves active/enabled-user checks,
effective thresholds, filters, individual notification reservations and the
unique user/local-date digest reservation. Scheduled tasks retain run_now=False.

A successful /digest acknowledgement means the task was published. The worker
may still skip it if today's digest was already attempted or delivery is disabled,
and an empty selection sends no vacancy cards. /status shows the latest attempt
status rather than claiming every attempt was a successful delivery.

## Validation

- Ruff: All checks passed.
- Black --check: 93 files would be left unchanged.
- pytest: 312 passed in the complete suite.
- git diff --check: passed.
- Source, tests and documentation language scan: no Cyrillic found.
- Unit tests use fake Telegram clients and dispatchers. No live Telegram requests
  or Celery workers are needed for pytest.

Tests cover every requested command, effective trial/free settings, owner and
non-owner dispatch, inactive/missing users, private-chat restrictions, malformed
and addressed commands, safe logs, broker failures, reply timeouts, saved-job
ordering/limits, message sizing, existing callbacks and manual digest daily limits.

## Live checks

Updated polling and worker processes were started through Poetry after stopping
their previous managed instances. Worker ping succeeded.
Processes left running: polling PID 412334, worker PID 412396, Beat PID 349832.
Logs remain in /tmp/job-hunter-{polling,worker,beat}.log.

A separate smoke script routed locally constructed owner messages through the
real command handler with real PostgreSQL, Telegram and Celery. This verifies
the handler and outgoing API path; it does not impersonate an inbound Telegram
update from the user's account.

Telegram accepted these command responses from @remotejobhunterbot:

| Command | Telegram message ID |
| --- | --- |
| /start | 11 |
| /help | 12 |
| /status | 13 |
| /saved | 14 |
| /filters | 15 |
| /collect | 16 |
| /digest | 19 |

The actual polling process also logged incoming /help, /start, /filters, /status
and /digest commands, including an unauthorized admin-command rejection.

Collection task 399faa7f-0ac8-4410-9971-c576b3fcc814 completed successfully in about
two seconds: received=99, new=0, duplicates=99, failed=0.
The smoke script's result waiter timed out after 45 seconds despite worker
success. Reading the stored backend result directly confirmed SUCCESS; collection
was not repeated to work around the test harness timeout.

Digest task a12e122a-8c6a-4cfd-810c-82b9f06901e9 completed successfully with
skipped / already_attempted_today. The database already contained today's empty
digest attempt, so no additional summary or vacancy cards were sent.

## Real /status example

The following snapshot was read from the local database after the checks.

```text
Bot status: running

Remote OK
Last success: 2026-09-28 12:15
Next run: 2026-09-28 18:39
Last status: success

Jobs in database: 103

Daily digest:
Time: 09:00
Timezone: America/Montevideo
Last digest: Today (empty)
Enabled: Yes

Times shown in America/Montevideo.
```

## Real /filters example

```text
Current filters

Required technologies:
Python

Preferred:
FastAPI
PostgreSQL
Redis
Celery
Docker

Remote only: Yes
Worldwide: Yes
LATAM: Yes
South America: Yes
Uruguay: Yes

Timezone: America/Montevideo
Timezone tolerance: ±2h

Excluded US-only: Yes

Minimum score: 70
Digest time: 09:00
```

## BotFather command menu

Configure manually; the application does not modify BotFather settings.

```text
start - About the bot
help - Show available commands
status - Bot and collector status
saved - Saved jobs
filters - Current job filters
collect - Run collection now
digest - Send digest now
```

## Files and Git snapshot

### Created files

```text
docs/telegram-commands-report.md
src/bot/commands.py
src/bot/dispatch.py
src/bot/updates.py
src/repositories/bot_queries.py
tests/bot/test_commands.py
tests/bot/test_dispatch.py
tests/bot/test_updates.py
tests/repositories/test_bot_queries.py
```

### Modified files

```text
README.md
src/bot/client.py
src/repositories/feedback.py
src/scripts/telegram_polling.py
src/services/digests.py
src/tasks/notifications.py
tests/bot/test_client.py
tests/services/test_digests.py
tests/tasks/test_tasks.py
```

### git diff --stat (tracked files only)

```text
 README.md                       | 78 +++++++++++++++++++++++++++++++++++++++++
 src/bot/client.py               | 13 ++++++-
 src/repositories/feedback.py    | 13 +++++++
 src/scripts/telegram_polling.py | 34 ++++++++++++++----
 src/services/digests.py         |  8 +++--
 src/tasks/notifications.py      | 10 +++---
 tests/bot/test_client.py        | 47 +++++++++++++++++++++++--
 tests/services/test_digests.py  | 18 ++++++++++
 tests/tasks/test_tasks.py       | 12 ++++++-
 9 files changed, 217 insertions(+), 16 deletions(-)
```

### git status

```text
## main...origin/main
 M README.md
 M src/bot/client.py
 M src/repositories/feedback.py
 M src/scripts/telegram_polling.py
 M src/services/digests.py
 M src/tasks/notifications.py
 M tests/bot/test_client.py
 M tests/services/test_digests.py
 M tests/tasks/test_tasks.py
?? docs/telegram-commands-report.md
?? src/bot/commands.py
?? src/bot/dispatch.py
?? src/bot/updates.py
?? src/repositories/bot_queries.py
?? tests/bot/test_commands.py
?? tests/bot/test_dispatch.py
?? tests/bot/test_updates.py
?? tests/repositories/test_bot_queries.py
```
