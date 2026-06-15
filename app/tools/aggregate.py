"""aggregate_by_category tool — F4."""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Transaction
from app.tools.budget import _month_bounds
from app.tools.registry import registry


class AggregateByCategoryArgs(BaseModel):
    user_id: str = Field(min_length=1)
    month: str = Field(pattern=r"^\d{4}-\d{2}$", description="Month in YYYY-MM")


def aggregate_by_category(*, db: Session, user_id: str, month: str) -> dict:
    """Returns per-category totals for the month."""
    start, end = _month_bounds(month)
    rows = db.execute(
        select(Transaction.category, func.sum(Transaction.amount))
        .where(Transaction.user_id == user_id)
        .where(Transaction.posted_at >= start)
        .where(Transaction.posted_at < end)
        .group_by(Transaction.category)
    ).all()
    by_category = {cat: str(total) for cat, total in rows}
    total = sum((float(v) for v in by_category.values()), 0.0)
    top = sorted(rows, key=lambda r: r[1], reverse=True)[:3]
    return {
        "month": month,
        "by_category": by_category,
        "total_spent": str(round(total, 2)),
        "top_3": [{"category": cat, "amount": str(amt)} for cat, amt in top],
    }


registry.register(
    name="aggregate_by_category",
    description=(
        "Aggregate transactions for a user in a month, grouped by category. "
        "Returns per-category totals, the overall total, and the top 3."
    ),
    func=aggregate_by_category,
    args_model=AggregateByCategoryArgs,
    needs_db=True,
)
