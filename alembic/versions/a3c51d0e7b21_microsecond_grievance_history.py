"""microsecond grievance history timestamps

Revision ID: a3c51d0e7b21
Revises: f29fe17ca07a
Create Date: 2026-10-30 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op


revision: str = "a3c51d0e7b21"
down_revision: str | None = "f29fe17ca07a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # An officer's first action writes "assigned" and the status change in the
    # same second; keep the timeline in order.
    op.execute(
        "ALTER TABLE grievance_status_history "
        "MODIFY created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE grievance_status_history "
        "MODIFY created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
    )
