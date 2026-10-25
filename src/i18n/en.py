"""EN Telegram interface catalog."""

EN = {
    "common.back": "← Back",
    "common.cancel": "Cancel",
    "common.add": "Add",
    "common.remove": "Remove",
    "common.clear": "Clear",
    "common.any": "Any",
    "common.none": "None",
    "common.yes": "Yes",
    "common.no": "No",
    "common.unknown": "Unknown",
    "common.not_specified": "not specified",
    "common.enabled": "Enabled",
    "common.disabled": "Disabled",
    "common.current": "Current",
    "language.title": "🌐 Language",
    "language.choose": "Choose your language / Elegí tu idioma",
    "language.menu": "🌐 Language\n\nCurrent: {name}",
    "language.updated": "Language updated to {name}.",
    "start.welcome": (
        "Job Hunter Bot\n\nI search for remote jobs, filter them based on "
        "your preferences, calculate a match score, and send the best "
        "matches in a daily digest.\n\nUse /help to see available commands."
    ),
    "help.public": (
        "/start - About the bot\n/help - Show available commands\n/status - "
        "Show bot and collector status\n/saved - Show saved jobs\n/filters "
        "- Configure job search filters\n/settings - Notification settings\n"
        "/cancel - Cancel current input"
    ),
    "help.admin": (
        "\n\nAdmin commands:\n/collect - Run all job collectors now\n/digest "
        "- Send today's digest now\n/stats [24h|7d|30d] - Pipeline "
        "statistics"
    ),
    "command.unavailable": "This command is not available.",
    "command.unknown": "Unknown command. Use /help to see available commands.",
    "input.cancelled": "Input cancelled.",
    "saved.empty": "You don't have any saved jobs yet.",
    "saved.title": "Saved jobs:",
    "saved.continued": "Saved jobs (continued):",
    "status.never": "Never",
    "status.not_scheduled": "Not scheduled",
    "status.today": "Today",
    "status.collector": (
        "{name}\nLast success: {last_success}\nNext run: {next_run}\nLast "
        "status: {status}"
    ),
    "status.body": (
        "Bot status: running\n\n{collectors}\n\nJobs in database: {count}\n\n"
        "Daily digest:\nTime: {time}\nTimezone: {timezone}\nLast digest: "
        "{last_digest}\nEnabled: {enabled}\n\nTimes shown in {zone}."
    ),
    "command.stats_usage": "Usage: /stats [24h|7d|30d]",
    "command.stats_unavailable": "Statistics are unavailable.",
    "command.stats_failed": "Statistics are temporarily unavailable.",
    "command.collect_started": "Collection started.",
    "command.collect_failed": "Failed to start collection.",
    "digest.queued": "Digest queued.",
    "digest.failed": "Failed to start digest.",
    "digest.already_sent": "Digest already sent today.",
    "digest.in_progress": "Digest is already in progress.",
    "digest.attempted": "Digest already attempted today.",
    "digest.empty": "No new jobs match your filters.",
    "digest.summary": "🔥 {count} new job matches\n\nTop matches:\n{matches}",
    "settings.title": "⚙️ Settings",
    "settings.timezone": "Timezone",
    "settings.digest_time": "Daily digest",
    "settings.min_score": "Minimum match score",
    "settings.plan": "Plan",
    "settings.trial_ends": "Trial ends",
    "settings.custom_time": "Custom digest time 🔒",
    "settings.custom_score": "Custom minimum score 🔒",
    "settings.timezone_button": "🌎 Timezone",
    "settings.time_button": "🕐 Digest time",
    "settings.score_button": "🎯 Minimum score",
    "settings.unavailable": "Notification settings are not available yet.",
    "settings.invalid": "Invalid setting.",
    "settings.not_available": "This setting is not available.",
    "settings.choose_timezone": "Choose your timezone.",
    "settings.choose_time": "Choose your daily digest time.",
    "settings.choose_score": "Choose your minimum match score.",
    "settings.timezone_updated": "Timezone updated to {value}.",
    "settings.time_updated": "Digest time updated to {value}.",
    "settings.score_updated": "Minimum score updated to {value}%.",
    "settings.premium_required": "This setting requires Trial or Premium.",
    "settings.edit_failed": (
        "Could not update the menu. Open /settings to check your settings."
    ),
    "settings.locked_time": (
        "Custom digest time is available during the trial or with "
        "Premium.\n\nYour current delivery time is {value}."
    ),
    "settings.locked_score": (
        "Custom minimum score is available during the trial or with "
        "Premium.\n\nYour current minimum score is {value}%."
    ),
    "filters.title": "🔎 Job filters",
    "filters.updated": "✅ Job filters updated.",
    "filters.unavailable": "Job filters are not available yet.",
    "filters.not_available": "This filter is not available.",
    "filters.edit_failed": (
        "Could not update the menu. Open /filters to check your filters."
    ),
    "filters.any_amount": "Any amount",
    "filters.any_currency": "Any currency",
    "filters.tolerance": "Timezone tolerance: ±{hours}h",
    "filters.any_selections": "No selections means Any.",
    "filters.regions_help": (
        "Select allowed regions. With no selections, any region is allowed. "
        "Worldwide jobs are compatible with every region."
    ),
    "filters.source_minimum": "At least one source must be enabled.",
    "filters.salary_screen": (
        "Minimum salary\n\nCurrent:\n{salary}\n\nNo currency conversion is applied."
    ),
    "filters.set_amount": "Set amount",
    "filters.currency": "Currency",
    "filters.choose_currency": "Choose a salary currency.",
    "filters.blacklist_title": "🚫 Blacklist",
    "filters.words": "Words",
    "filters.companies": "Companies",
    "filters.timezone_hint": "Timezone is configured in /settings.",
    "filters.reset": "Reset filters",
    "filters.reset_confirm": "Reset all job filters to defaults?",
    "filters.reset_yes": "Yes, reset",
    "input.salary": "Send a whole number without currency symbols.\n\nExample:\n2500",
    "input.add_keywords": "Send keywords separated by commas.",
    "input.remove_keywords": "Send keywords to remove separated by commas.",
    "input.add_tech": "Enter skills separated by commas.",
    "input.remove_tech": "Send skills or tags to remove separated by commas.",
    "input.add_words": "Send blacklisted words separated by commas.",
    "input.remove_words": "Send blacklisted words to remove separated by commas.",
    "input.add_companies": "Send blacklisted companies separated by commas.",
    "input.remove_companies": (
        "Send blacklisted companies to remove separated by commas."
    ),
    "input.keywords_example": "\n\nExample:\naccountant, sales, designer, python",
    "input.expiry": "\n\nUse /cancel to cancel. Input expires in 10 minutes.",
    "input.retry": "{error}\n\nTry again, or use /cancel.",
    "error.invalid_list": "Invalid list input.",
    "error.empty_list": "Send at least one value separated by commas.",
    "error.list_size": "Use at most 50 values, each up to 100 characters.",
    "error.list_limit": "Use at most 50 values.",
    "error.list_action": "Invalid list action.",
    "error.tech_conflict": "Remove these skills from excluded skills first.",
    "error.filter_option": "Invalid filter option.",
    "error.filter_screen": "Invalid filter screen.",
    "error.salary": (
        "Send a whole number from 0 to 2147483647, without currency symbols."
    ),
    "error.currency": "Invalid currency.",
    "error.tolerance": "Timezone tolerance must be between 0 and 4 hours.",
    "error.language": "Invalid language.",
    "error.timezone": "Invalid timezone",
    "error.digest_time": "Digest time must be a local time with minute precision",
    "error.score": "Minimum score must be an integer from 0 to 100",
    "job.match": "🔥 Match: {score}%",
    "job.company": "Company",
    "job.company_missing": "Company not specified",
    "job.salary": "Salary",
    "job.salary_missing": "Salary not specified",
    "job.salary_from": "From {amount}",
    "job.salary_up_to": "Up to {amount}",
    "job.remote": "Remote",
    "job.region": "Region",
    "job.region_missing": "Region not specified",
    "job.employment": "Employment",
    "job.employment_missing": "Employment type not specified",
    "job.technologies": "Skills",
    "job.technologies_missing": "Skills not specified",
    "job.experience": "Experience",
    "job.source": "Source",
    "job.matches": "Matches",
    "job.penalties": "Penalties",
    "job.warnings": "Warnings",
    "job.open": "Open vacancy",
    "job.save": "Save",
    "job.reject": "Not suitable",
    "feedback.invalid": "Invalid callback",
    "feedback.unregistered": "User is not registered",
    "feedback.inactive": "User is inactive",
    "feedback.not_found": "Vacancy not found",
    "feedback.saved": "Job saved",
    "feedback.rejected": "Marked as not suitable",
    "score.base": "Base score: +50",
    "score.preferred": "Preferred skills matched ({matched}): +{points}",
    "score.required": "Required skills matched ({matched}): +{points}",
    "score.keyword": "Keywords matched ({matched}): +{points}",
    "score.region": "Region matches user preferences: +{points}",
    "score.timezone_compatible": "Timezone compatible: +{points}",
    "score.timezone_distance": "Timezone within {distance} hours: +{points}",
    "score.timezone_no_adjustment": (
        "Timezone difference: {distance} hours: no adjustment"
    ),
    "score.timezone_far": "Timezone differs by {distance} hours: {points}",
    "score.region_penalty": "Region is not specified: -2",
    "score.region_unknown": "Remote region is unknown",
    "score.timezone_penalty": "Timezone is not specified: -2",
    "score.timezone_missing": "Timezone is not specified",
    "score.experience_unknown": "Experience level is unknown: -2",
    "score.experience_missing": "Experience level is not specified",
    "score.experience_match": "Experience matches user preferences: +{points}",
    "score.experience_mismatch": (
        "Inferred experience differs from user preferences: {points}"
    ),
    "score.salary_penalty": "Salary is not specified: -2",
    "score.salary_missing": "Salary is not specified",
    "score.salary_currency_unknown": "Salary currency is unknown: -2",
    "score.salary_currency_missing": "Salary currency is not specified",
    "score.salary_match": "Salary meets user minimum: +{points}",
    "score.employment_unknown": "Employment type is unknown: -2",
    "score.employment_missing": "Employment type is not specified",
    "score.employment_match": "Employment matches user preferences: +{points}",
    "score.remote_match": "Remote matches user preference: +{points}",
    "label.keywords": "Keywords",
    "label.required_technologies": "Required skills",
    "label.preferred_technologies": "Preferred skills",
    "label.excluded_technologies": "Excluded skills",
    "label.blacklisted_words": "Blacklisted words",
    "label.blacklisted_companies": "Blacklisted companies",
    "label.allowed_regions": "Regions",
    "label.employment_types": "Employment",
    "label.experience_levels": "Experience",
    "label.sources": "Sources",
    "label.remote_only": "Remote only",
    "label.exclude_us_only": "Exclude US-only",
    "label.full_time": "Full-time",
    "label.part_time": "Part-time",
    "label.contract": "Contract",
    "label.freelance": "Freelance",
    "label.internship": "Internship",
    "label.junior": "Junior",
    "label.middle": "Middle",
    "label.senior": "Senior",
    "label.lead": "Lead",
    "label.staff": "Staff",
    "label.principal": "Principal",
    "label.architect": "Architect",
    "label.engineering manager": "Engineering Manager",
    "label.worldwide": "Worldwide",
    "label.latam": "Latin America",
    "label.south_america": "South America",
    "label.uruguay": "Uruguay",
    "label.americas": "Americas",
    "label.north_america": "North America",
    "label.europe": "Europe",
    "label.eu": "EU",
    "label.emea": "EMEA",
    "label.apac": "APAC",
    "label.us_only": "US only",
    "label.month": "month",
    "label.year": "year",
    "label.hour": "hour",
    "label.Trial": "Trial",
    "label.Free": "Free",
    "label.Premium": "Premium",
    "status.success": "success",
    "status.failed": "failed",
    "status.configuration_required": "configuration required",
    "status.skipped": "skipped",
    "status.running": "running",
    "status.scheduled": "scheduled",
    "status.sent": "sent",
    "status.pending": "pending",
    "status.empty": "empty",
    "status.partial": "partial",
    "status.abandoned": "abandoned",
    "status.unknown": "unknown",
    "status.retryable": "retryable",
    "status.active": "active",
    "status.expired": "expired",
    "status.trial": "trial",
    "filters.button_keywords": "🔎 Keywords",
    "filters.button_reqtech": "🧰 Required skills",
    "filters.button_preftech": "⭐ Preferred skills",
    "filters.button_extech": "🚫 Excluded skills",
    "filters.button_regions": "🌎 Regions",
    "filters.button_employment": "💼 Employment",
    "filters.button_experience": "📈 Experience",
    "filters.button_salary": "💰 Salary",
    "filters.button_sources": "📡 Sources",
    "filters.button_blacklist": "🚫 Blacklist",
    "filters.button_tz_tol": "🕐 Timezone tolerance",
    "filters.button_reset": "Reset filters",
    "filters.minimum_salary": "Minimum salary",
    "common.other": "Other",
    "filters.countries": "Specific countries",
    "input.countries": (
        "Send country names or ISO codes separated by commas.\n"
        "\n"
        "Example:\n"
        "Uruguay, Spain, Canada\n"
        "UY, ES, CA"
    ),
    "input.currency": (
        "Send a 3-letter currency code.\n" "\n" "Examples: JPY, CHF, NZD, COP, ARS"
    ),
    "input.timezone": (
        "Send an IANA timezone.\n"
        "\n"
        "Examples:\n"
        "Europe/Berlin\n"
        "Asia/Tokyo\n"
        "America/Mexico_City"
    ),
    "input.skills_example": (
        "\n"
        "\n"
        "Examples:\n"
        "Python, FastAPI\n"
        "Figma, UX Research\n"
        "Salesforce, B2B Sales\n"
        "Excel, Accounting"
    ),
    "settings.custom_timezone": "Other / Custom timezone",
    "error.country": (
        "Unknown country. Use a country name or ISO code, for " "example Spain or ES."
    ),
    "label.asia": "Asia",
    "label.africa": "Africa",
    "label.oceania": "Oceania",
}
