"""Celery task that persists an immutable audit record.

Kept deliberately thin: the caller (``app/core/activity.py``) has already
resolved GeoIP and assembled JSON-serialisable arguments, so the worker only
opens a synchronous session and inserts the row.
"""

import uuid
from typing import Any

from app.db.sync_session import worker_session
from app.models.activity import Activity
from app.workers.celery_app import celery_app


@celery_app.task(name="activity.write", max_retries=3, default_retry_delay=10)  # type: ignore[untyped-decorator]
def write_activity(
    *,
    topic: str,
    action: str,
    result: str,
    category: str,
    user_id: str | None = None,
    target_uid: str | None = None,
    user_ip: str | None = None,
    user_ip_country: str | None = None,
    user_agent: str | None = None,
    data: dict[str, Any] | None = None,
    actor_role: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    with worker_session() as session:
        session.add(
            Activity(
                user_id=uuid.UUID(user_id) if user_id else None,
                target_uid=target_uid,
                category=category,
                user_ip=user_ip,
                user_ip_country=user_ip_country,
                user_agent=user_agent,
                topic=topic,
                action=action,
                result=result,
                data=data,
                actor_role=actor_role,
                target_type=target_type,
                target_id=target_id,
                before=before,
                after=after,
            )
        )
