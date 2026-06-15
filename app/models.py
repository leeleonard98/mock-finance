"""SQLAlchemy declarative base + per-feature models.

Build order is in the spec
(docs/superpowers/specs/2026-06-15-financial-advisor-design.md, section 4).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Text, func
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


class Transaction(Base):
    """One outflow row from a parsed CSV (F2). category defaults to 'other'
    until F3's classifier runs at upload time. is_recurring is set by F6.
    """

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    posted_at: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    category: Mapped[str] = mapped_column(
        String(32), nullable=False, default="other", server_default="other"
    )
    is_recurring: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
