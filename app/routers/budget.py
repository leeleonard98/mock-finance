"""F1: budget management.

Single monthly cap per user. PUT upserts (no auth — same user_id-as-string
convention as the rest of the app). GET returns 404 if no budget set, so
clients can distinguish 'not set' from 'cap is zero'.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Budget

router = APIRouter(prefix="/users/{user_id}/budget", tags=["budget"])


class BudgetIn(BaseModel):
    monthly_cap: Decimal = Field(ge=0, decimal_places=2, max_digits=12)
    currency: str = Field(default="USD", min_length=3, max_length=3)


class BudgetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    monthly_cap: Decimal
    currency: str
    updated_at: datetime


@router.put("", response_model=BudgetOut)
def upsert_budget(
    user_id: str, payload: BudgetIn, db: Session = Depends(get_db)
) -> BudgetOut:
    obj = db.get(Budget, user_id)
    if obj is None:
        obj = Budget(
            user_id=user_id,
            monthly_cap=payload.monthly_cap,
            currency=payload.currency,
        )
        db.add(obj)
    else:
        obj.monthly_cap = payload.monthly_cap
        obj.currency = payload.currency
    db.commit()
    db.refresh(obj)
    return BudgetOut.model_validate(obj)


@router.get("", response_model=BudgetOut)
def get_budget(user_id: str, db: Session = Depends(get_db)) -> BudgetOut:
    obj = db.get(Budget, user_id)
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no budget set for this user",
        )
    return BudgetOut.model_validate(obj)
