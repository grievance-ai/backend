"""microsecond message timestamps

Revision ID: eca8c2181da5
Revises: 518c90f78339
Create Date: 2026-10-28 12:31:12.247179
"""

from collections.abc import Sequence

from alembic import op


revision: str = 'eca8c2181da5'
down_revision: str | None = '518c90f78339'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Message and reply are written in the same second; keep their order.
    op.execute(
        "ALTER TABLE conversation_messages "
        "MODIFY created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE conversation_messages "
        "MODIFY created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
    )
