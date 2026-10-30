"""Alembic migration environment.

Migrations run through the synchronous MySQL driver (pymysql); the application
itself uses the async driver. The URL and target metadata come from the app so
there is a single source of truth.
"""

from logging.config import fileConfig

import app.models  # noqa: F401  (registers every model on Base.metadata)
from alembic import context
from app.core.config import settings
from app.core.encryption import EncryptedString
from app.db.base import GUID, Base
from sqlalchemy import engine_from_config, pool

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url_sync)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def render_item(type_, obj, autogen_context):
    """Render custom column types with plain SQLAlchemy types so migrations need no app imports."""
    if type_ == "type" and isinstance(obj, GUID):
        return "sa.CHAR(36)"
    if type_ == "type" and isinstance(obj, EncryptedString):
        return "sa.Text()"
    return False


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url_sync,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_item=render_item,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
