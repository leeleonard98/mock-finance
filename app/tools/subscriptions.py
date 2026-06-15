"""detect_subscriptions tool — F4 wrapper around app/subscriptions.py."""

from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Transaction
from app.subscriptions import detect
from app.tools.registry import registry


class DetectSubscriptionsArgs(BaseModel):
    user_id: str = Field(min_length=1)
    lookback_months: int = Field(default=3, ge=1, le=24)


def detect_subscriptions(
    *, db: Session, user_id: str, lookback_months: int = 3
) -> list[dict]:
    today = date.today()
    cutoff = today - timedelta(days=31 * lookback_months)
    rows = (
        db.execute(
            select(Transaction)
            .where(Transaction.user_id == user_id)
            .where(Transaction.posted_at >= cutoff)
            .order_by(Transaction.posted_at)
        )
        .scalars()
        .all()
    )
    subs = detect(list(rows))
    return [
        {
            "merchant": s.merchant,
            "monthly_amount": str(s.monthly_amount),
            "occurrences": s.occurrences,
            "last_seen": s.last_seen.isoformat(),
        }
        for s in subs
    ]


registry.register(
    name="detect_subscriptions",
    description=(
        "Find recurring monthly payments for a user (e.g. Netflix, gym). "
        "Returns merchant, monthly amount, occurrences, last seen date."
    ),
    func=detect_subscriptions,
    args_model=DetectSubscriptionsArgs,
    needs_db=True,
)
