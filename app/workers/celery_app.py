"""Celery application — the async task runner shared by every worker.

Backed by Redis (broker + result backend). Task modules are listed in
``include`` so they register on import. Set ``CELERY_TASK_ALWAYS_EAGER=true`` to
run tasks inline in the calling process (used by tests and worker-less dev).
"""

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "xuanwu",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.workers.activity",
        "app.workers.email",
        "app.workers.sms",
        "app.workers.maintenance",
    ],
)

celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    timezone="UTC",
    enable_utc=True,
    # Periodic jobs run by the dedicated `beat` container. Domain schedules
    # — monthly storage invoicing, daily sitemap — bolt on here in Phase 17.
    beat_schedule={
        "clean-expired-tokens": {
            "task": "maintenance.clean_expired_tokens",
            "schedule": crontab(hour=3, minute=0),  # daily at 03:00 UTC
        },
    },
)
