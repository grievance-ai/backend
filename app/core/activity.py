"""Audit-trail entry point.

Services call :func:`log_activity` to record a security-relevant event. It
resolves the actor's GeoIP country and enqueues the async ``activity.write``
task, so request handling never blocks on the audit write. Activity rows are
append-only — see the immutability guard in ``app/models/activity.py``.
"""

import uuid
from typing import Any

from fastapi import Request

from app.integrations import geoip
from app.workers.activity import write_activity


def request_meta(request: Request) -> tuple[str | None, str | None]:
    """Extract the (client IP, user-agent) pair from a request."""
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    return ip, user_agent


def log_activity(
    *,
    topic: str,
    action: str,
    result: str,
    category: str = "user",
    user_id: uuid.UUID | str | None = None,
    target_uid: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    data: dict[str, Any] | None = None,
    actor_role: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    """Enqueue an immutable audit record for ``topic``/``action``/``result``.

    ``target_type``/``target_id`` name the affected record (e.g. a grievance) and
    ``before``/``after`` hold the changed values, for the system-admin audit log.
    """
    write_activity.delay(
        topic=topic,
        action=action,
        result=result,
        category=category,
        user_id=str(user_id) if user_id else None,
        target_uid=target_uid,
        user_ip=ip,
        user_ip_country=geoip.resolve_country(ip),
        user_agent=user_agent[:255] if user_agent else None,
        data=data,
        actor_role=actor_role,
        target_type=target_type,
        target_id=target_id,
        before=before,
        after=after,
    )
