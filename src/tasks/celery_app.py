from celery import Celery

from src.config import settings

celery_app = Celery(
    "job_hunter",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["src.tasks.scheduler", "src.tasks.jobs", "src.tasks.notifications"],
)
celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_soft_time_limit=540,
    task_time_limit=600,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    result_expires=86400,
    beat_schedule={
        "dispatch-collectors": {
            "task": "scheduler.dispatch_collectors",
            "schedule": 15 * 60,
        },
        "dispatch-digests": {
            "task": "scheduler.dispatch_digests",
            "schedule": 5 * 60,
        },
    },
)
