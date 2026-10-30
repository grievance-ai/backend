"""Admin activity-list query builder (ported from nebryx admin/activities)."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, select

from app.models.activity import Activity
from app.models.user import User


@dataclass(frozen=True)
class ActivityFilter:
    action: str | None = None
    topic: str | None = None
    uid: str | None = None
    email: str | None = None
    user_ids: list[object] | None = None  # resolved from uid/email by the service
    date_from: datetime | None = None
    date_to: datetime | None = None


def build_activity_query(f: ActivityFilter) -> Select[tuple[Activity]]:
    stmt = select(Activity)
    if f.action:
        stmt = stmt.where(Activity.action == f.action)
    if f.topic:
        stmt = stmt.where(Activity.topic == f.topic)
    if f.user_ids is not None:
        stmt = stmt.where(Activity.user_id.in_(f.user_ids))
    if f.date_from is not None:
        stmt = stmt.where(Activity.created_at >= f.date_from)
    if f.date_to is not None:
        stmt = stmt.where(Activity.created_at <= f.date_to)
    return stmt.order_by(Activity.created_at.desc())


def user_lookup_query(uid: str | None, email: str | None) -> Select[tuple[User]]:
    stmt = select(User)
    if uid:
        stmt = stmt.where(User.uid == uid)
    if email:
        stmt = stmt.where(User.email == email)
    return stmt
