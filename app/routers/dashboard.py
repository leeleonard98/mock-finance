"""F8: dashboard endpoint — aggregated numbers for the chat UI panel."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Budget
from app.tools.aggregate import aggregate_by_category
from app.tools.budget import calculate_remaining_budget

router = APIRouter(prefix="/users/{user_id}/dashboard", tags=["dashboard"])


class TopCategory(BaseModel):
    category: str
    amount: Decimal


class DashboardOut(BaseModel):
    user_id: str
    month: str
    cap: Decimal | None
    spent: Decimal
    remaining: Decimal | None
    top_3: list[TopCategory]


@router.get("", response_model=DashboardOut)
def dashboard(user_id: str, db: Session = Depends(get_db)) -> DashboardOut:
    """Snapshot for the UI panel: budget, spent this month, top 3 categories."""
    today = date.today()
    month = f"{today.year:04d}-{today.month:02d}"
    budget = calculate_remaining_budget(db=db, user_id=user_id, month=month)
    aggr = aggregate_by_category(db=db, user_id=user_id, month=month)

    if "error" in budget:
        cap = remaining = None
    else:
        cap = Decimal(budget["cap"])
        remaining = Decimal(budget["remaining"])

    return DashboardOut(
        user_id=user_id,
        month=month,
        cap=cap,
        spent=Decimal(aggr["total_spent"]),
        remaining=remaining,
        top_3=[
            TopCategory(category=t["category"], amount=Decimal(t["amount"]))
            for t in aggr["top_3"]
        ],
    )
