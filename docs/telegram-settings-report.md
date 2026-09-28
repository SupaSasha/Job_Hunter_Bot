# Telegram settings stage report

## Result

/settings now shows effective notification settings and edits them through an
inline menu. The UI, source, tests and documentation are in English.
No migration, dependency, payment integration, collector, or scoring change was
needed. No commit or push was made.

## Files

Created:

- src/bot/settings.py
- src/repositories/notification_settings.py
- src/services/notification_settings.py
- tests/bot/test_settings.py
- tests/services/test_notification_settings.py
- docs/telegram-settings-report.md

Modified:

- README.md
- src/bot/client.py
- src/bot/commands.py
- src/bot/updates.py
- src/repositories/bot_queries.py
- src/scripts/telegram_polling.py
- src/services/entitlements.py
- tests/bot/test_client.py
- tests/bot/test_commands.py
- tests/bot/test_updates.py

## Menu and access

The command is available to any registered active user in a private chat.
Unknown/inactive users and mismatched sender/chat IDs cannot read or change
settings. Each callback resolves the user from its sender; callback data never
contains a target user ID.

Root buttons:

```text
[ 🌎 Timezone ]
[ 🕐 Digest time ]
[ 🎯 Minimum score ]
[ ← Back ]
```

Child Back returns to settings; root Back opens public help.
Navigation and confirmations edit the existing message. A successful selection
prepends a confirmation such as "Digest time updated to 08:00." to the refreshed
menu, and also answers the callback. Every callback with a valid query ID is
acknowledged, including denied, invalid, and failed operations.
Repeated edits with unchanged content are treated as a successful no-op only
for Telegram's specific editMessageText "message is not modified" response.
Other API failures remain sanitized errors.

| Setting | Free | Trial / Premium |
| --- | --- | --- |
| Timezone | Editable | Editable |
| Digest time | Effective FREE_DIGEST_TIME, locked | Stored custom value, editable |
| Minimum score | Effective FREE_MIN_SCORE, locked | Stored custom value, editable |

EntitlementService owns both effective values and human plan labels.
An expired trial is Free even when its DB status is still trial.
A missing subscription is also Free. Existing startup bootstrap remains
responsible for creating missing trial rows; it never renews an expired trial.
Custom values are not overwritten on expiry and apply again after reactivation.
The service rechecks current entitlement on every write, so old buttons do not
bypass expiration. /filters and /status continue using effective settings.

## Options and callback data

Timezone options:

```text
America/Montevideo
America/Sao_Paulo
America/Argentina/Buenos_Aires
America/New_York
America/Los_Angeles
Europe/London
Europe/Madrid
UTC
```

Time presets, stored as local datetime.time / SQL TIME:

```text
[07:00] [08:00]
[09:00] [10:00]
[12:00] [18:00]
[20:00]
[← Back]
```

Score presets: 50%, 60%, 70%, 75%, 80%, 85%, 90%.
Free-text settings input is not accepted.

Callback formats:

```text
settings:timezone
settings:time
settings:score
settings:back
settings:close
tz:America/Montevideo
time:0700
score:80
```

All offered IANA names fit directly within the 64-byte callback limit.
Settings callbacks have their own handler and route. Existing save:<job_id>
and reject:<job_id> feedback routing remains independent.

## Public service and repository APIs

NotificationSettingsService(session, entitlements, clock=...) exposes:

- get(user_id) -> NotificationSettingsView
- update_timezone(user_id, timezone: str) -> None
- update_digest_time(user_id, digest_time: time) -> None
- update_min_score(user_id, min_score: int) -> None

The view contains effective settings, a human plan label, and an active trial end.
Validation uses ZoneInfo for IANA zones, a naive time with minute precision,
and a strict integer score in 0..100 (bool is rejected).
SettingsUnavailable and PremiumRequired distinguish missing preferences and
denied custom changes. The service owns write commit/rollback.

NotificationSettingsRepository exposes get_by_user_id and the same three
update methods. Updates affect only the requested user's selected field and
use the model's updated_at behavior; they do not commit. The subscription query
refreshes an already loaded row before entitlement evaluation.

TelegramClient adds edit_message_text(chat_id, message_id, text, reply_markup=None).
CommandHandler receives a SettingsHandler; route_update routes settings prefixes
separately from feedback. Polling creates all handlers with a fresh session for
each incoming update.

## Example Trial menu

The final live menu after restoring the original development data:

```text
⚙️ Settings

Timezone:
America/Montevideo

Daily digest:
09:00

Minimum match score:
70%

Plan:
Trial

Trial ends:
2026-10-04
```

## Example Free menu

With the current development defaults:

```text
⚙️ Settings

Timezone:
America/Montevideo

Daily digest:
09:00

Minimum match score:
70%

Plan:
Free

Custom digest time 🔒
Custom minimum score 🔒
```

A Free time selection displays:

```text
Custom digest time is available during the trial or with Premium.

Your current delivery time is 09:00.
```

A Free score selection displays:

```text
Custom minimum score is available during the trial or with Premium.

Your current minimum score is 70%.
```

These values come from configuration, not handler literals. Tests also use
10:15 and 65% to verify that configured values appear correctly.

## Help and BotFather

Public /help:

```text
/start - About the bot
/help - Show available commands
/status - Show bot and collector status
/saved - Show saved jobs
/filters - Show current filters
/settings - Notification settings
```

Only the configured owner additionally sees:

```text
Admin commands:
/collect - Run job collection now
/digest - Send today's digest now
```

Public BotFather list, prepared for manual configuration:

```text
start - About the bot
help - Show available commands
status - Bot and collector status
saved - Saved jobs
filters - Current job filters
settings - Notification settings
```

The BotFather menu was not changed automatically.

## Verification

- poetry run ruff check .: passed.
- poetry run black --check .: passed; 98 files unchanged.
- poetry run pytest -q: 411 passed.
- git diff --check: passed.
- Unit tests use fake repositories/clients and httpx.MockTransport, with no
  real Telegram calls.
- Coverage includes plan boundaries, missing subscriptions, preserved and
  reactivated custom values, validation, transaction failures, sender scoping,
  exact presets, callbacks and acknowledgments, stale buttons, private-chat
  restrictions, feedback routing, and narrow unchanged-message handling.

Live integration check on 2026-09-28:

- Real PostgreSQL and Telegram Bot API were used; 20 send/edit operations completed.
- Incoming command and callback payloads were constructed locally and routed
  through the production handlers. These were not taps made in a Telegram client.
  Callback acknowledgment was recorded locally for synthetic query IDs; its API
  payload/error behavior is covered by unit tests.
- Trial changes to America/Sao_Paulo, 08:00 and 80% were saved and appeared in
  /filters and /status.
- Repeated unchanged-menu edits succeeded.
- Temporarily expired trial showed Free defaults and blocked forged/stale custom
  selections while preserving 08:00 and 80% in PostgreSQL.
- Timezone remained editable under Free.
- Activating Premium restored the saved custom time and score.
- Original preferences and subscription, including their timestamps, were restored
  in a finally block. Polling and Beat were paused during temporary data changes
  and resumed afterward.
- The updated polling process was started using
  poetry run python -m src.scripts.telegram_polling.
  Startup was confirmed with no recent warning/error lines. Polling, worker and
  Beat remain running; the restored settings menu was sent to @remotejobhunterbot.
- A human tap-through on a phone remains unverified.

Runtime check: polling PID 441700, worker PID 412396, Beat PID 349832.
The temporary integration script and records are under /tmp and are not part
of the repository.

## Git snapshot

git diff --stat (tracked files only; newly created files are listed by status):

```text
 README.md                       | 52 ++++++++++++++++++++++++++++---
 src/bot/client.py               | 32 +++++++++++++++++++
 src/bot/commands.py             | 30 ++++++++++++++++--
 src/bot/updates.py              | 18 +++++++++--
 src/repositories/bot_queries.py |  4 ++-
 src/scripts/telegram_polling.py | 18 +++++++++--
 src/services/entitlements.py    |  9 ++++++
 tests/bot/test_client.py        | 68 +++++++++++++++++++++++++++++++++++++++++
 tests/bot/test_commands.py      | 33 ++++++++++++++++++--
 tests/bot/test_updates.py       | 30 ++++++++++++++++++
 10 files changed, 279 insertions(+), 15 deletions(-)
```

git status --short --branch:

```text
## main...origin/main
 M README.md
 M src/bot/client.py
 M src/bot/commands.py
 M src/bot/updates.py
 M src/repositories/bot_queries.py
 M src/scripts/telegram_polling.py
 M src/services/entitlements.py
 M tests/bot/test_client.py
 M tests/bot/test_commands.py
 M tests/bot/test_updates.py
?? docs/telegram-settings-report.md
?? src/bot/settings.py
?? src/repositories/notification_settings.py
?? src/services/notification_settings.py
?? tests/bot/test_settings.py
?? tests/services/test_notification_settings.py
```
