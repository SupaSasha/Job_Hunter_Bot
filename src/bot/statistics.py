from src.schemas.statistics import BotStats
from src.services.collector_policy import source_display_name


def percent(value: float | None, *, fraction: bool = True) -> str:
    return "N/A" if value is None else f"{value * (100 if fraction else 1):.1f}%"


def format_statistics(stats: BotStats) -> list[str]:
    labels = {"24h": "24 hours", "7d": "7 days", "30d": "30 days"}
    lines = [
        f"Bot statistics — last {labels[stats.period]}",
        f"As of {stats.until:%Y-%m-%d %H:%M} UTC",
        "",
        "Collectors",
    ]
    for source in stats.collectors:
        efficiency = (
            "N/A"
            if source.new_jobs_per_run is None
            else f"{source.new_jobs_per_run:.1f}"
        )
        lines.extend(
            [
                source_display_name(source.source),
                f"Runs: {source.runs} | "
                f"Success: {source.successful_runs} | "
                f"Failed: {source.failed_runs} | "
                f"Skipped: {source.skipped_runs} | "
                f"Running: {source.running_runs}",
                f"Received: {source.received_count} | "
                f"New: {source.new_count} | "
                f"Duplicates: {source.duplicate_count}",
                f"Cross-source duplicates: {source.cross_source_duplicate_count} | "
                f"Failed jobs: {source.failed_count}",
                f"New/run: {efficiency} | "
                f"Duplicate rate: {percent(source.duplicate_rate)}",
                "",
            ]
        )
    digest = stats.digest

    def measured(value: int) -> str:
        if digest.unmeasured_runs and not digest.measured_runs:
            return "N/A"
        return str(value)

    lines.extend(
        [
            "Pipeline",
            f"Digest runs: {digest.runs} | "
            f"Measured: {digest.measured_runs} | "
            f"Unmeasured: {digest.unmeasured_runs}",
            f"Failed runs: {digest.failed_runs} | Pending: {digest.pending_runs}",
            f"Candidates: {measured(digest.candidate_count)}",
            f"Rejected by filters: {measured(digest.filter_rejected_count)}",
            f"Accepted: {measured(digest.accepted_count)}",
            f"Below threshold: {measured(digest.below_threshold_count)}",
            "",
            "Score (accepted jobs)",
        ]
    )
    for bucket in ["90_100", "80_89", "70_79", "60_69", "50_59", "0_49"]:
        count = getattr(digest, f"score_{bucket}_count")
        lines.append(f"{bucket.replace('_', '–')}: {measured(count)}")
    lines.extend(
        [
            "",
            "Delivery (digest runs)",
            f"Selected: {digest.selected_count} | "
            f"Sent: {digest.sent_count} | "
            f"Failed: {digest.failed_count} | "
            f"Skipped: {digest.skipped_count}",
            "Notifications (created in period)",
            f"Sent: {stats.notifications.sent_count} | "
            f"Failed: {stats.notifications.failed_count} | "
            f"Pending: {stats.notifications.pending_count}",
            "",
            "Feedback (latest updates in period)",
            f"Saved: {stats.feedback.saved_count} | "
            f"Rejected: {stats.feedback.rejected_count}",
            "",
            "Users (current)",
            f"Total: {stats.users.total_users} | Active: {stats.users.active_users}",
            f"Trial: {stats.users.trial_users} | "
            f"Premium: {stats.users.premium_users} | "
            f"Free: {stats.users.free_users}",
            "",
            "Quality indicators",
            f"Duplicate rate: {percent(stats.duplicate_rate)}",
            f"Filter rejection rate: {percent(stats.filter_rejection_rate)}",
            f"Notification success rate: {percent(stats.notification_success_rate)}",
            f"Save rate: {percent(stats.save_rate)} | "
            f"Reject rate: {percent(stats.reject_rate)}",
            "",
            f"Data quality ({stats.quality.job_count} jobs created in period)",
        ]
    )
    for field in ["salary", "region", "timezone", "technologies"]:
        value = percent(
            getattr(stats.quality, field + "_known_percent"), fraction=False
        )
        lines.append(f"{field.capitalize()} known: {value}")
    lines.extend(
        [
            "",
            "Selection metrics cover measured runs only. "
            "New/run excludes skipped/running runs. "
            "Feedback rates compare period totals, not a delivery cohort.",
        ]
    )
    messages, current = [], ""
    for line in lines:
        combined = current + ("\n" if current else "") + line
        if len(combined.encode("utf-16-le")) // 2 > 4096:
            messages.append(current)
            current = line
        else:
            current = combined
    if current:
        messages.append(current)
    return messages
