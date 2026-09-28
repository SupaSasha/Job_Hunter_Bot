import importlib
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def app(monkeypatch):
    for key in ("DB_HOST", "DB_USER", "DB_PASS", "DB_NAME"):
        monkeypatch.setenv(key, "test")
    from src.tasks.celery_app import celery_app

    celery_app.loader.import_default_modules()
    return celery_app


def test_stable_task_registration_and_beat_intervals(app):
    assert {
        "scheduler.dispatch_collectors",
        "scheduler.dispatch_digests",
        "jobs.collect_remoteok",
        "notifications.send_daily_digest",
    }.issubset(app.tasks)
    schedule = app.conf.beat_schedule
    assert len(schedule) == 2
    assert schedule["dispatch-collectors"]["schedule"] == 900
    assert schedule["dispatch-digests"]["schedule"] == 300
    assert app.conf.timezone == "UTC"
    assert app.conf.task_time_limit < 660
    assert app.conf.accept_content == ["json"]


@pytest.mark.parametrize(
    "module,name,arguments",
    [
        ("jobs", "collect_remoteok", ["2026-09-27T00:00:00+00:00"]),
        ("notifications", "send_daily_digest", [17, "2026-09-27"]),
        ("scheduler", "dispatch_collectors", []),
        ("scheduler", "dispatch_digests", []),
    ],
)
def test_task_is_thin_async_wrapper(app, monkeypatch, module, name, arguments):
    target = importlib.import_module(f"src.tasks.{module}")
    implementation = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(target, f"{name}_async", implementation)
    assert getattr(target, name).run(*arguments) == {"ok": True}
    kwargs = {"run_now": False} if name == "send_daily_digest" else {}
    implementation.assert_awaited_once_with(*arguments, **kwargs)


def test_manual_digest_flag_reaches_async_service(app, monkeypatch):
    from src.tasks import notifications

    implementation = AsyncMock(return_value={"status": "sent"})
    monkeypatch.setattr(notifications, "send_daily_digest_async", implementation)
    assert notifications.send_daily_digest.run(17, run_now=True) == {"status": "sent"}
    implementation.assert_awaited_once_with(17, None, run_now=True)
