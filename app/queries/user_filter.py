"""Admin user-list query builder (ported from nebryx admin/users filtering)."""

from dataclasses import dataclass

from sqlalchemy import Select, select

from app.models.user import User


@dataclass(frozen=True)
class UserFilter:
    uid: str | None = None
    email: str | None = None
    role: str | None = None
    state: str | None = None
    level: int | None = None


def build_user_query(f: UserFilter) -> Select[tuple[User]]:
    stmt = select(User)
    if f.uid:
        stmt = stmt.where(User.uid == f.uid)
    if f.email:
        stmt = stmt.where(User.email == f.email)
    if f.role:
        stmt = stmt.where(User.role == f.role)
    if f.state:
        stmt = stmt.where(User.state == f.state)
    if f.level is not None:
        stmt = stmt.where(User.level == f.level)
    return stmt.order_by(User.created_at.asc())
