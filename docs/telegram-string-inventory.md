# Telegram string inventory before localization

Inventory captured before implementation. Literal fragments of interpolated messages are included so dynamic labels and validation errors are covered. Canonical identifiers, callback values and diagnostic-only strings are retained in this audit where needed for context; they are not translated. Vacancy titles, companies, descriptions, URLs, currencies, technology names, IANA timezones and source brands remain source data.

User-facing surfaces: welcome/help; private-chat authorization and unknown-command replies; saved jobs; collector/user status; owner collection/digest/statistics replies; settings and entitlement locks; filter summary/navigation/prompts/errors/reset; salary, region, experience and employment labels; digest summary; job cards/scoring explanations; feedback keyboards and acknowledgments. Admin statistics can retain technical English terminology as allowed by the task.

## src/bot/commands.py

| Original line | Literal or interpolated fragment |
| --- | --- |
| 23 | `Job Hunter Bot\n\nI search for remote jobs, filter them based on your preferences, calculate a match score, and send the best matches in a daily digest.\n\nUse /help to see available commands.` |
| 29 | `/start - About the bot\n/help - Show available commands\n/status - Show bot and collector status\n/saved - Show saved jobs\n/filters - Configure job search filters\n/settings - Notification settings\n/cancel - Cancel current input` |
| 38 | `\n\nAdmin commands:\n/collect - Run all job collectors now\n/digest - Send today's digest now\n/stats [24h\|7d\|30d] - Pipeline statistics` |
| 43 | `This command is not available.` |
| 44 | `Unknown command. Use /help to see available commands.` |
| 46 | `start` |
| 47 | `help` |
| 48 | `status` |
| 49 | `saved` |
| 50 | `filters` |
| 51 | `settings` |
| 52 | `cancel` |
| 53 | `collect` |
| 54 | `digest` |
| 55 | `stats` |
| 66 | `[A-Za-z0-9_]{1,32}` |
| 73 | `You don't have any saved jobs yet.` |
| 75 | `Saved jobs:` |
| 79 | `Company not specified` |
| 83 | `utf-16-le` |
| 85 | `Saved jobs (continued):\n\n` |
| 127 | `Command reply failed` |
| 138 | `UTC` |
| 147 | `%Y-%m-%d %H:%M` |
| 158 | `Not scheduled` |
| 162 | `\nLast success: ` |
| 162 | `\nNext run: ` |
| 162 | `\nLast status: ` |
| 166 | `Never` |
| 169 | `Today` |
| 175 | `Unknown` |
| 175 | `%H:%M` |
| 178 | `Yes` |
| 178 | `No` |
| 181 | `Bot status: running\n\n` |
| 181 | `\n\nJobs in database: ` |
| 182 | `\n\nDaily digest:\nTime: ` |
| 183 | `\nTimezone: ` |
| 184 | `\nLast digest: ` |
| 185 | `\nEnabled: ` |
| 185 | `\n\nTimes shown in ` |
| 192 | `text` |
| 195 | `from` |
| 195 | `chat` |
| 198 | `id` |
| 204 | `is_bot` |
| 209 | `Command received: %s` |
| 209 | `unknown` |
| 211 | `private` |
| 211 | `type` |
| 221 | `Unknown command` |
| 228 | `Unauthorized admin command` |
| 246 | `Notification settings are not available yet.` |
| 258 | `Job filters are not available yet.` |
| 263 | `Input cancelled.` |
| 268 | `24h` |
| 268 | `7d` |
| 268 | `30d` |
| 270 | `Usage: /stats [24h\|7d\|30d]` |
| 273 | `Statistics are unavailable.` |
| 278 | `Statistics failed: %s` |
| 279 | `Statistics are temporarily unavailable.` |
| 297 | `abandoned` |
| 300 | `pending` |
| 307 | `sent` |
| 307 | `Digest already sent today.` |
| 308 | `Digest is already in progress.` |
| 309 | `Digest already attempted today.` |
| 312 | `collection` |
| 313 | `Admin %s requested` |
| 320 | `Failed to dispatch %s (%s)` |
| 321 | `Failed to start ` |
| 325 | `Collection started.` |
| 325 | `Digest queued.` |

## src/bot/settings.py

| Original line | Literal or interpolated fragment |
| --- | --- |
| 17 | `America/Montevideo` |
| 18 | `America/Sao_Paulo` |
| 19 | `America/Argentina/Buenos_Aires` |
| 20 | `America/New_York` |
| 21 | `America/Los_Angeles` |
| 22 | `Europe/London` |
| 23 | `Europe/Madrid` |
| 24 | `UTC` |
| 26 | `02d` |
| 31 | `text` |
| 31 | `callback_data` |
| 34 | `← Back` |
| 34 | `settings:back` |
| 36 | `inline_keyboard` |
| 37 | `🌎 Timezone` |
| 37 | `settings:timezone` |
| 38 | `🕐 Digest time` |
| 38 | `settings:time` |
| 39 | `🎯 Minimum score` |
| 39 | `settings:score` |
| 40 | `settings:close` |
| 48 | `⚙️ Settings\n\nTimezone:\n` |
| 48 | `\n\nDaily digest:\n` |
| 49 | `\n\nMinimum match score:\n` |
| 49 | `%H:%M` |
| 50 | `%\n\nPlan:\n` |
| 54 | `\n\nTrial ends:\n` |
| 54 | `%Y-%m-%d` |
| 56 | `\n\nCustom digest time 🔒\nCustom minimum score 🔒` |
| 62 | `time` |
| 64 | `digest time` |
| 65 | `delivery time is ` |
| 68 | `minimum score` |
| 68 | `minimum score is ` |
| 70 | `Custom ` |
| 70 | ` is available during the trial or with Premium.\n\nYour current ` |
| 100 | `Settings reply failed` |
| 105 | `id` |
| 108 | `This setting is not available.` |
| 110 | `from` |
| 111 | `message` |
| 114 | `chat` |
| 115 | `message_id` |
| 119 | `is_bot` |
| 121 | `private` |
| 121 | `type` |
| 133 | `data` |
| 143 | `Choose your timezone.` |
| 146 | `tz:` |
| 156 | `Choose your daily digest time.` |
| 158 | `Choose your minimum match score.` |
| 162 | `time:` |
| 166 | `score:` |
| 177 | `tz` |
| 179 | `Timezone updated to ` |
| 182 | `Digest time updated to ` |
| 183 | `score` |
| 185 | `Minimum score updated to ` |
| 192 | `This setting requires Trial or Premium.` |
| 200 | `Notification settings are not available yet.` |
| 202 | `Invalid setting.` |
| 205 | `Settings callback failed` |
| 206 | `Could not update the menu. Open /settings to check your settings.` |
| 211 | `Settings callback acknowledgment failed` |

## src/bot/filters.py

| Original line | Literal or interpolated fragment |
| --- | --- |
| 22 | `keywords` |
| 22 | `Keywords` |
| 23 | `reqtech` |
| 23 | `required_technologies` |
| 23 | `Required technologies` |
| 24 | `preftech` |
| 24 | `preferred_technologies` |
| 24 | `Preferred technologies` |
| 25 | `extech` |
| 25 | `excluded_technologies` |
| 25 | `Excluded technologies` |
| 26 | `blacklist_words` |
| 26 | `blacklisted_words` |
| 26 | `Blacklisted words` |
| 27 | `blacklist_companies` |
| 27 | `blacklisted_companies` |
| 27 | `Blacklisted companies` |
| 30 | `regions` |
| 30 | `allowed_regions` |
| 30 | `Regions` |
| 31 | `employment` |
| 31 | `employment_types` |
| 31 | `Employment` |
| 32 | `experience` |
| 32 | `experience_levels` |
| 32 | `Experience` |
| 33 | `sources` |
| 33 | `Sources` |
| 33 | `remoteok` |
| 33 | `weworkremotely` |
| 33 | `getonboard` |
| 36 | `🔎 Keywords` |
| 37 | `🧰 Required tech` |
| 38 | `⭐ Preferred tech` |
| 39 | `🚫 Excluded tech` |
| 40 | `🌎 Regions` |
| 41 | `💼 Employment` |
| 42 | `📈 Experience` |
| 43 | `💰 Salary` |
| 43 | `salary` |
| 44 | `📡 Sources` |
| 45 | `🚫 Blacklist` |
| 45 | `blacklist` |
| 46 | `🕐 Timezone tolerance` |
| 46 | `tz_tol` |
| 47 | `Reset filters` |
| 47 | `reset` |
| 53 | `worldwide` |
| 53 | `Worldwide` |
| 54 | `latam` |
| 54 | `LATAM` |
| 55 | `eu` |
| 55 | `EU` |
| 56 | `emea` |
| 56 | `EMEA` |
| 57 | `apac` |
| 57 | `APAC` |
| 58 | `full_time` |
| 58 | `Full-time` |
| 59 | `part_time` |
| 59 | `Part-time` |
| 67 | `inline_keyboard` |
| 70 | `back` |
| 71 | `← Back` |
| 71 | `filters:` |
| 74 | `Any` |
| 79 | `Any amount` |
| 80 | `Any currency` |
| 84 | `🔎 Job filters` |
| 89 | `Regions:\n` |
| 91 | `Remote only: ` |
| 91 | `✅ Yes` |
| 91 | `❌ No` |
| 92 | `Exclude US-only: ` |
| 93 | `Employment:\n` |
| 95 | `Experience:\n` |
| 97 | `Minimum salary:\n` |
| 98 | `Sources:\n` |
| 99 | `Timezone tolerance: ±` |
| 99 | `h` |
| 112 | `None` |
| 120 | `blacklist_` |
| 127 | `No selections means Any.` |
| 129 | `At least one source must stay enabled.` |
| 133 | `Regions\n\nSelect allowed regions. With no selections, jobs with a known region are excluded.` |
| 155 | `remote_only` |
| 155 | `Remote only` |
| 156 | `exclude_us_only` |
| 156 | `Exclude US-only` |
| 163 | `Minimum salary\n\nCurrent:\n` |
| 163 | `\n\nNo currency conversion is applied.` |
| 167 | `Set amount` |
| 167 | `filters:min_salary` |
| 168 | `Currency` |
| 168 | `filters:currency` |
| 169 | `Clear` |
| 169 | `filters:salary:clear` |
| 174 | `currency` |
| 175 | `Choose a salary currency.` |
| 178 | `filters:currency:` |
| 187 | `Words` |
| 187 | `filters:blacklist_words` |
| 188 | `Companies` |
| 188 | `filters:blacklist_companies` |
| 194 | `h\n\nTimezone is configured in /settings.` |
| 199 | `filters:tz_tol:` |
| 207 | `Reset all job filters to defaults?` |
| 209 | `Yes, reset` |
| 209 | `filters:reset:confirm` |
| 210 | `Cancel` |
| 210 | `filters:back` |
| 213 | `Invalid filter screen.` |
| 243 | `Filters reply failed` |
| 248 | `Input cancelled.` |
| 250 | `Input cancellation reply failed` |
| 253 | `from` |
| 253 | `chat` |
| 256 | `id` |
| 260 | `is_bot` |
| 261 | `private` |
| 261 | `type` |
| 272 | `min_salary` |
| 273 | `Send a whole number without currency symbols.\n\nExample:\n2500` |
| 278 | `technologies` |
| 282 | ` to remove` |
| 282 | `remove` |
| 283 | `Send ` |
| 283 | ` separated by commas.` |
| 285 | `\n\nExample:\npython, backend, api` |
| 288 | `\n\nUse /cancel to cancel. Input expires in 10 minutes.` |
| 299 | `This filter is not available.` |
| 301 | `message` |
| 307 | `message_id` |
| 307 | `data` |
| 316 | `filters` |
| 322 | `add` |
| 328 | `clear` |
| 354 | `confirm` |
| 358 | `Invalid filter option.` |
| 365 | `Job filters are not available yet.` |
| 369 | `Filters callback failed` |
| 370 | `Could not update the menu. Open /filters to check your filters.` |
| 375 | `Filters callback acknowledgment failed` |
| 378 | `text` |
| 402 | `\n\nTry again, or use /cancel.` |
| 406 | `Filter validation reply failed` |
| 415 | `✅ Job filters updated.\n\n` |
| 419 | `Filter input menu edit failed` |

## src/bot/formatter.py

| Original line | Literal or interpolated fragment |
| --- | --- |
| 8 | `python` |
| 8 | `🐍 Python` |
| 9 | `fastapi` |
| 9 | `⚡ FastAPI` |
| 10 | `postgresql` |
| 10 | `🐘 PostgreSQL` |
| 11 | `docker` |
| 11 | `🐳 Docker` |
| 12 | `redis` |
| 12 | `Redis` |
| 13 | `celery` |
| 13 | `Celery` |
| 16 | `worldwide` |
| 16 | `Worldwide` |
| 17 | `latam` |
| 17 | `LATAM` |
| 18 | `south_america` |
| 18 | `South America` |
| 19 | `us_only` |
| 19 | `US only` |
| 20 | `uruguay` |
| 20 | `Uruguay` |
| 22 | `full_time` |
| 22 | `part_time` |
| 22 | `Full-time` |
| 22 | `Part-time` |
| 23 | `month` |
| 23 | `year` |
| 23 | `hour` |
| 28 | `utf-16-le` |
| 31 | `ignore` |
| 36 | `Salary not specified` |
| 40 | `From ` |
| 42 | `Up to ` |
| 54 | `Region not specified` |
| 56 | `Remote · ` |
| 58 | `Employment type not specified` |
| 62 | `Technologies not specified` |
| 65 | `🔥 Match: ` |
| 67 | `Company not specified` |
| 70 | `Experience: ` |
| 70 | `\nSource: ` |
| 70 | `not specified` |
| 74 | `Matches` |
| 75 | `Penalties` |
| 76 | `Warnings` |
| 86 | `https` |
| 86 | `http` |
| 87 | `Job URL must be an absolute HTTP(S) URL` |
| 88 | `save:` |
| 88 | `reject:` |
| 89 | `utf-8` |
| 90 | `Job ID does not fit Telegram callback_data` |
| 92 | `inline_keyboard` |
| 93 | `text` |
| 93 | `url` |
| 93 | `View job` |
| 95 | `callback_data` |
| 95 | `Save` |
| 96 | `Not suitable` |

## src/bot/callbacks.py

| Original line | Literal or interpolated fragment |
| --- | --- |
| 17 | `saved` |
| 17 | `rejected` |
| 23 | `(save\|reject):([1-9][0-9]{0,9})` |
| 32 | `save` |
| 55 | `Telegram callback acknowledgement failed: %s` |
| 58 | `Callback received` |
| 60 | `Invalid callback` |
| 62 | `id` |
| 64 | `Invalid callback: missing query ID` |
| 66 | `data` |
| 67 | `from` |
| 80 | `Unknown user in callback` |
| 81 | `User is not registered` |
| 84 | `Inactive user in callback` |
| 85 | `User is inactive` |
| 89 | `Job not found: job_id=%s` |
| 90 | `Vacancy not found` |
| 95 | `Feedback saved: user_id=%s job_id=%s type=%s` |
| 101 | `Job saved` |
| 101 | `Marked as not suitable` |

## src/bot/statistics.py

| Original line | Literal or interpolated fragment |
| --- | --- |
| 6 | `N/A` |
| 6 | `.1f` |
| 10 | `24h` |
| 10 | `7d` |
| 10 | `30d` |
| 10 | `24 hours` |
| 10 | `7 days` |
| 10 | `30 days` |
| 12 | `Bot statistics — last ` |
| 13 | `As of ` |
| 13 | ` UTC` |
| 13 | `%Y-%m-%d %H:%M` |
| 15 | `Collectors` |
| 26 | `Runs: ` |
| 26 | ` \| Success: ` |
| 29 | ` \| Running: ` |
| 31 | `Received: ` |
| 31 | ` \| New: ` |
| 32 | ` \| Duplicates: ` |
| 34 | `Cross-source duplicates: ` |
| 34 | ` \| Failed jobs: ` |
| 36 | `New/run: ` |
| 36 | ` \| Duplicate rate: ` |
| 50 | `Pipeline` |
| 51 | `Digest runs: ` |
| 51 | ` \| Measured: ` |
| 52 | ` \| Unmeasured: ` |
| 54 | `Failed runs: ` |
| 54 | ` \| Pending: ` |
| 55 | `Abandoned runs: ` |
| 56 | `Candidates: ` |
| 57 | `Rejected by filters: ` |
| 58 | `Accepted: ` |
| 59 | `Below threshold: ` |
| 61 | `Score (accepted jobs)` |
| 65 | `score_` |
| 65 | `_count` |
| 70 | `Delivery (digest runs)` |
| 71 | `Selected: ` |
| 71 | ` \| Sent: ` |
| 72 | ` \| Failed: ` |
| 73 | ` \| Skipped: ` |
| 75 | `Notifications (created in period)` |
| 76 | `Sent: ` |
| 79 | `Retryable: ` |
| 79 | ` \| Unknown: ` |
| 82 | `Feedback (latest updates in period)` |
| 83 | `Saved: ` |
| 83 | ` \| Rejected: ` |
| 86 | `Users (current)` |
| 87 | `Total: ` |
| 87 | ` \| Active: ` |
| 88 | `Trial: ` |
| 88 | ` \| Premium: ` |
| 89 | ` \| Free: ` |
| 92 | `Quality indicators` |
| 93 | `Duplicate rate: ` |
| 94 | `Filter rejection rate: ` |
| 95 | `Notification success rate: ` |
| 96 | `Save rate: ` |
| 96 | ` \| Reject rate: ` |
| 99 | `Data quality (` |
| 99 | ` jobs created in period)` |
| 102 | `salary` |
| 102 | `region` |
| 102 | `timezone` |
| 102 | `technologies` |
| 104 | `_known_percent` |
| 106 | ` known: ` |
| 110 | `Selection metrics cover measured runs only. New/run excludes skipped/running runs. Feedback rates compare period totals, not a delivery cohort.` |
| 118 | `utf-16-le` |

## src/services/digests.py

| Original line | Literal or interpolated fragment |
| --- | --- |
| 47 | `score_` |
| 47 | `_count` |
| 60 | `Top matches:` |
| 60 | ` new job matches` |
| 95 | `status` |
| 95 | `reason` |
| 95 | `skipped` |
| 95 | `inactive_or_disabled` |
| 102 | `stale_date` |
| 106 | `not_due` |
| 108 | `telegram_not_configured` |
| 111 | `already_attempted_today` |
| 133 | `empty` |
| 154 | `sent` |
| 154 | `partial` |
| 160 | `selected` |
| 162 | `failed` |
| 177 | `Digest user=%s failed: %s` |
| 180 | `error` |

## src/services/scoring.py

| Original line | Literal or interpolated fragment |
| --- | --- |
| 15 | `python` |
| 16 | `fastapi` |
| 17 | `postgresql` |
| 18 | `redis` |
| 19 | `celery` |
| 20 | `docker` |
| 24 | `Python` |
| 25 | `FastAPI` |
| 26 | `PostgreSQL` |
| 27 | `Redis` |
| 28 | `Celery` |
| 29 | `Docker` |
| 30 | `kubernetes` |
| 30 | `Kubernetes` |
| 31 | `nodejs` |
| 31 | `Node.js` |
| 32 | `javascript` |
| 32 | `JavaScript` |
| 33 | `typescript` |
| 33 | `TypeScript` |
| 37 | `worldwide` |
| 38 | `latam` |
| 39 | `uruguay` |
| 40 | `south_america` |
| 41 | `americas` |
| 45 | `junior` |
| 46 | `middle` |
| 50 | `senior` |
| 51 | `lead` |
| 52 | `staff` |
| 53 | `principal` |
| 61 | `architect` |
| 62 | `engineering manager` |
| 71 | `Rank jobs for user interest using explainable score rules.` |
| 84 | `\\s+` |
| 102 | `(?<![\\w.])(?P<years>\\d+)\\+?\\s*(?:years?\|yrs?)[’']?\\s+(?:of\\s+)?(?:[a-z+#]+(?:[-‑–][a-z+#]+)*\\s+){0,3}experience\\b` |
| 106 | `years` |
| 120 | `sr.` |
| 173 | `Preferred technology ` |
| 216 | `Keyword: ` |
| 229 | `Region is not specified: -2` |
| 230 | `Remote region is unknown` |
| 251 | `Worldwide` |
| 252 | `LATAM` |
| 253 | `Uruguay` |
| 254 | `South America` |
| 255 | `Americas` |
| 258 | ` region: +` |
| 275 | `Timezone is not specified: -2` |
| 276 | `Timezone is not specified` |
| 284 | `Timezone compatible: +10` |
| 293 | `Timezone distance: ` |
| 293 | ` hour(s): +7` |
| 293 | `g` |
| 298 | ` hours: +4` |
| 303 | ` hours: 0` |
| 308 | ` hours: -10` |
| 311 | `Timezone distance: 5+ hours: -20` |
| 331 | ` level: +` |
| 335 | ` level: ` |
| 344 | `Title seniority: ` |
| 348 | `Experience level is not specified` |
| 374 | `Requires ` |
| 374 | `+ years of experience: ` |
| 386 | `Salary is not specified: -2` |
| 387 | `Salary is not specified` |
| 399 | `Employment type is not specified` |
| 401 | `full_time` |
| 402 | `Full-time: +3` |
| 407 | `Base score: +50` |
| 415 | `Remote: +10` |

## src/services/user_filters.py

| Original line | Literal or interpolated fragment |
| --- | --- |
| 18 | `americas` |
| 19 | `north_america` |
| 20 | `europe` |
| 21 | `eu` |
| 22 | `emea` |
| 23 | `apac` |
| 25 | `full_time` |
| 25 | `part_time` |
| 25 | `contract` |
| 25 | `freelance` |
| 25 | `internship` |
| 26 | `junior` |
| 26 | `middle` |
| 26 | `senior` |
| 26 | `lead` |
| 26 | `staff` |
| 26 | `principal` |
| 27 | `USD` |
| 27 | `EUR` |
| 27 | `UYU` |
| 29 | `keywords` |
| 30 | `required_technologies` |
| 31 | `preferred_technologies` |
| 32 | `excluded_technologies` |
| 33 | `blacklisted_words` |
| 34 | `blacklisted_companies` |
| 37 | `allowed_regions` |
| 38 | `employment_types` |
| 39 | `experience_levels` |
| 40 | `sources` |
| 54 | `remote_only` |
| 55 | `exclude_us_only` |
| 56 | `min_salary` |
| 57 | `currency` |
| 58 | `timezone_tolerance_hours` |
| 63 | `Derive region flags from storage; use the notification timezone.` |
| 80 | `worldwide` |
| 81 | `latam` |
| 82 | `south_america` |
| 83 | `uruguay` |
| 89 | `Invalid list input.` |
| 90 | `technologies` |
| 97 | `Send at least one value separated by commas.` |
| 99 | `Use at most 50 values, each up to 100 characters.` |
| 104 | `Own filter transactions, using a session without unrelated pending writes.\n\n    Lock the parent user before bootstrap/read-modify-write so concurrent first\n    reads and menu updates cannot create duplicates or lose list changes.\n    ` |
| 163 | `add` |
| 163 | `remove` |
| 164 | `Invalid list action.` |
| 165 | `clear` |
| 179 | `Use at most 50 values.` |
| 184 | `Remove these technologies from excluded technologies first.` |
| 205 | `Invalid filter option.` |
| 215 | `At least one source must be enabled.` |
| 231 | `Send a whole number from 0 to 2147483647, without currency symbols.` |
| 244 | `Invalid currency.` |
| 251 | `Timezone tolerance must be between 0 and 4 hours.` |

## src/services/notification_settings.py

| Original line | Literal or interpolated fragment |
| --- | --- |
| 29 | `Own settings transactions; use a session without unrelated pending writes.` |
| 57 | `Invalid timezone` |
| 62 | `timezone` |
| 71 | `Digest time must be a local time with minute precision` |
| 72 | `digest_time` |
| 76 | `Minimum score must be an integer from 0 to 100` |
| 77 | `min_score` |
| 85 | `update_` |

## src/services/entitlements.py

| Original line | Literal or interpolated fragment |
| --- | --- |
| 27 | `trial` |
| 32 | `active` |
| 43 | `Free` |
| 45 | `Trial` |
| 46 | `Premium` |
| 70 | `now must be timezone-aware` |
