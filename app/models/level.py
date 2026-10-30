"""Level — progressive-verification definition.

The primary key *is* the level number (0 → 3): a user reaches a level when they
hold the label whose ``(key, value)`` matches that level's row. This lookup
table is the one place an integer PK is intentional.
"""

from sqlalchemy import Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Level(Base, TimestampMixin):
    __tablename__ = "levels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    key: Mapped[str] = mapped_column(String(255))
    value: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(255), default=None)

    __table_args__ = (UniqueConstraint("key", "value", name="uq_levels_key_value"),)
