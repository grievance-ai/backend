"""Operator console — the small set of commands you run to bootstrap an install.

Run inside the container, e.g.::

    python -m app.console generate-keys
    python -m app.console seed
    python -m app.console create-superadmin --email admin@example.com

These mirror nebryx's ``console.js`` / ``npm run seed`` helpers, recast as a
plain argparse CLI so each command is scriptable and CI-friendly.
"""

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import select

from app.core import security
from app.db.seeds import main as seed_main
from app.db.session import AsyncSessionLocal
from app.models.enums import UserState
from app.models.user import User


def cmd_generate_keys(args: argparse.Namespace) -> int:
    """Write the RS256 JWT keypair to the configured paths."""
    try:
        private_path, public_path = security.write_keypair(force=args.force)
    except FileExistsError as exc:
        print(f"{exc} (use --force to overwrite)", file=sys.stderr)
        return 1
    print(f"Wrote private key → {private_path}")
    print(f"Wrote public key  → {public_path}")
    return 0


def cmd_seed(_args: argparse.Namespace) -> int:
    """Seed the default RBAC permissions and verification levels (idempotent)."""
    asyncio.run(seed_main())
    print("Seeded default permissions and levels.")
    return 0


def cmd_seed_knowledge(_args: argparse.Namespace) -> int:
    """Load config/knowledge/schemes.yml into the database (idempotent)."""
    from app.db.knowledge import seed_geography, seed_grievance_categories, seed_knowledge
    from app.db.session import AsyncSessionLocal

    async def run() -> tuple[int, int, int, int]:
        async with AsyncSessionLocal() as db:
            districts = await seed_geography(db)
            departments, schemes = await seed_knowledge(db)
            categories = await seed_grievance_categories(db)
            return districts, departments, schemes, categories

    districts, departments, schemes, categories = asyncio.run(run())
    print(
        f"Loaded {districts} districts, {departments} scheme departments, {schemes} schemes "
        f"and {categories} grievance categories."
    )
    return 0


def cmd_seed_demo_staff(_args: argparse.Namespace) -> int:
    """Create the demo officer/administrator accounts (idempotent; not in production)."""
    from app.core.config import settings
    from app.db.demo_staff import seed_demo_staff

    if settings.is_production:
        print("Skipped demo staff: APP_ENV is production.")
        return 0

    async def run() -> tuple[int, list[str]]:
        async with AsyncSessionLocal() as db:
            return await seed_demo_staff(db)

    count, skipped = asyncio.run(run())
    print(f"Demo staff ready: {count} accounts (log in with the mobile number and OTP).")
    for mobile in skipped:
        print(f"  skipped {mobile}: already a citizen account", file=sys.stderr)
    return 0


async def _create_superadmin(email: str, username: str | None, password: str) -> str:
    async with AsyncSessionLocal() as db:
        existing = await db.scalar(select(User).where(User.email == email))
        if existing is not None:
            raise ValueError(f"A user with email {email!r} already exists.")
        user = User(
            email=email,
            username=username,
            password_digest=security.hash_password(password),
            role="superadmin",
            state=UserState.active.value,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user.uid


def cmd_create_superadmin(args: argparse.Namespace) -> int:
    """Create an active superadmin account (bootstrap; bypasses registration)."""
    password = args.password or getpass.getpass("Password: ")
    if not password:
        print("A password is required.", file=sys.stderr)
        return 1
    try:
        uid = asyncio.run(_create_superadmin(args.email, args.username, password))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Created superadmin {args.email} (uid={uid}).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.console", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_keys = sub.add_parser("generate-keys", help="write the RS256 JWT keypair")
    p_keys.add_argument("--force", action="store_true", help="overwrite existing keys")
    p_keys.set_defaults(func=cmd_generate_keys)

    p_seed = sub.add_parser("seed", help="seed default permissions and levels")
    p_seed.set_defaults(func=cmd_seed)

    p_knowledge = sub.add_parser(
        "seed-knowledge", help="load districts and the scheme knowledge base (config/knowledge/)"
    )
    p_knowledge.set_defaults(func=cmd_seed_knowledge)

    p_staff = sub.add_parser(
        "seed-demo-staff", help="create demo officer/admin accounts (config/knowledge/)"
    )
    p_staff.set_defaults(func=cmd_seed_demo_staff)

    p_admin = sub.add_parser("create-superadmin", help="create an active superadmin")
    p_admin.add_argument("--email", required=True)
    p_admin.add_argument("--username", default=None)
    p_admin.add_argument("--password", default=None, help="prompted if omitted")
    p_admin.set_defaults(func=cmd_create_superadmin)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
