"""calculate_remaining_budget tool — F4."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Budget, Transaction
from app.tools.registry import registry


class CalculateRemainingBudgetArgs(BaseModel):
    user_id: str = Field(min_length=1)
    month: str = Field(pattern=r"^\d{4}-\d{2}$", description="Month in YYYY-MM")


def _month_bounds(month: str) -> tuple[date, date]:
    """Return (start_inclusive, end_exclusive) for the YYYY-MM string."""
    year, m = (int(x) for x in month.split("-"))
    start = date(year, m, 1)
    if m == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, m + 1, 1)
    return start, end


def calculate_remaining_budget(*, db: Session, user_id: str, month: str) -> dict:
    budget = db.get(Budget, user_id)
    if budget is None:
        return {"error": "no budget set for this user"}
    start, end = _month_bounds(month)
    spent = db.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0))
        .where(Transaction.user_id == user_id)
        .where(Transaction.posted_at >= start)
        .where(Transaction.posted_at < end)
    ).scalar_one()
    cap = Decimal(budget.monthly_cap)
    spent = Decimal(spent)
    return {
        "month": month,
        "cap": str(cap),
        "spent": str(spent),
        "remaining": str(cap - spent),
        "currency": budget.currency,
    }


registry.register(
    name="calculate_remaining_budget",
    description=(
        "Compute remaining budget for a user in a given month: cap minus "
        "the sum of transactions in that month."
    ),
    func=calculate_remaining_budget,
    args_model=CalculateRemainingBudgetArgs,
    needs_db=True,
)
