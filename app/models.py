"""SQLAlchemy declarative base + per-feature models.

Build order is in the spec
(docs/superpowers/specs/2026-06-15-financial-advisor-design.md, section 4).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Budget(Base):
    """One row per user. Single monthly cap (no per-category yet — F1)."""

    __tablename__ = "budgets"

    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    monthly_cap: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
