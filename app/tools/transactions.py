"""get_transactions tool — F4."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.classifier import CATEGORIES
from app.models import Transaction
from app.tools.registry import registry


class GetTransactionsArgs(BaseModel):
    user_id: str = Field(min_length=1)
    from_date: str | None = Field(default=None, description="Inclusive ISO date 'YYYY-MM-DD'")
    to_date: str | None = Field(default=None, description="Inclusive ISO date 'YYYY-MM-DD'")
    category: str | None = Field(default=None, description=f"One of: {', '.join(CATEGORIES)}")


def get_transactions(
    *,
    db: Session,
    user_id: str,
    from_date: str | None = None,
    to_date: str | None = None,
    category: str | None = None,
) -> list[dict[str, Any]]:
    stmt = select(Transaction).where(Transaction.user_id == user_id)
    if from_date:
        stmt = stmt.where(Transaction.posted_at >= date.fromisoformat(from_date))
    if to_date:
        stmt = stmt.where(Transaction.posted_at <= date.fromisoformat(to_date))
    if category:
        stmt = stmt.where(Transaction.category == category)
    rows = db.execute(stmt.order_by(Transaction.posted_at, Transaction.id)).scalars().all()
    return [
        {
            "id": r.id,
            "date": r.posted_at.isoformat(),
            "description": r.description,
            "amount": str(r.amount),
            "category": r.category,
        }
        for r in rows
    ]


registry.register(
    name="get_transactions",
    description="Filtered transaction query for a user. Optional date range and category.",
    func=get_transactions,
    args_model=GetTransactionsArgs,
    needs_db=True,
)
