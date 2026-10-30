"""Idempotent seed data: default RBAC permissions and verification levels.

Run inside the container:  ``python -m app.db.seeds``
"""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.enums import PermissionAction
from app.models.level import Level
from app.models.permission import Permission

_NS = "/api/v2/xuanwu"

DEFAULT_PERMISSIONS: list[tuple[str, str, str, str]] = [
    # role, verb, path-prefix, action
    ("superadmin", "ALL", f"{_NS}/", PermissionAction.accept.value),
    ("admin", "ALL", f"{_NS}/admin/", PermissionAction.accept.value),
    ("admin", "ALL", f"{_NS}/resource/", PermissionAction.accept.value),
    ("member", "ALL", f"{_NS}/resource/", PermissionAction.accept.value),
    # Grievance & scheme assistant roles
    ("citizen", "ALL", f"{_NS}/resource/", PermissionAction.accept.value),
    ("officer", "ALL", f"{_NS}/resource/", PermissionAction.accept.value),
]

DEFAULT_LEVELS: list[tuple[int, str, str, str]] = [
    (1, "email", "verified", "Email address verified"),
    (2, "phone", "verified", "Phone number verified"),
    (3, "document", "verified", "Identity document verified"),
]


async def seed_permissions(db: AsyncSession) -> None:
    for role, verb, path, action in DEFAULT_PERMISSIONS:
        existing = await db.scalar(
            select(Permission).where(
                Permission.role == role, Permission.verb == verb, Permission.path == path
            )
        )
        if existing is None:
            db.add(Permission(role=role, verb=verb, path=path, action=action))
    await db.commit()


async def seed_levels(db: AsyncSession) -> None:
    for level_id, key, value, description in DEFAULT_LEVELS:
        if await db.get(Level, level_id) is None:
            db.add(Level(id=level_id, key=key, value=value, description=description))
    await db.commit()


async def main() -> None:
    async with AsyncSessionLocal() as db:
        await seed_permissions(db)
        await seed_levels(db)


if __name__ == "__main__":
    asyncio.run(main())
