"""F2: CSV upload + filtered transaction read."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.classifier import classify_transactions, coerce_category
from app.csv_parser import CSVParseError, parse_csv
from app.db import get_db
from app.models import Transaction
from app.subscriptions import mark_recurring

router = APIRouter(prefix="/users/{user_id}/transactions", tags=["transactions"])


class UploadResponse(BaseModel):
    count: int
    filename: str


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: str
    posted_at: date
    description: str
    amount: Decimal
    category: str
    is_recurring: bool
    source_file: str | None
    created_at: datetime


class TransactionList(BaseModel):
    user_id: str
    items: list[TransactionOut]


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_transactions(
    user_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> UploadResponse:
    """Parse a bank-statement CSV and persist each outflow row."""
    settings = get_settings()
    raw = await file.read()
    if len(raw) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"file too large (>{settings.MAX_UPLOAD_BYTES} bytes)",
        )
    try:
        rows = parse_csv(raw)
    except CSVParseError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        ) from e

    new_txs: list[Transaction] = []
    for r in rows:
        tx = Transaction(
            user_id=user_id,
            posted_at=r.posted_at,
            description=r.description,
            amount=r.amount,
            category="other",  # F3 replaces this below
            source_file=file.filename,
        )
        db.add(tx)
        new_txs.append(tx)
    # F3: ask the LLM to categorise all rows in one batched call.
    if new_txs:
        cats = classify_transactions([r.description for r in rows])
        # Defence in depth: even if the seam returns junk, coerce to known set.
        for tx, cat in zip(new_txs, cats, strict=False):
            tx.category = coerce_category(cat)
    db.commit()
    return UploadResponse(count=len(rows), filename=file.filename or "")


@router.get("", response_model=TransactionList)
def list_transactions(
    user_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    category: str | None = None,
    db: Session = Depends(get_db),
) -> TransactionList:
    """Filtered read: optional date range and/or category."""
    stmt = select(Transaction).where(Transaction.user_id == user_id)
    if from_date is not None:
        stmt = stmt.where(Transaction.posted_at >= from_date)
    if to_date is not None:
        stmt = stmt.where(Transaction.posted_at <= to_date)
    if category is not None:
        stmt = stmt.where(Transaction.category == category)
    stmt = stmt.order_by(Transaction.posted_at, Transaction.id)
    rows = db.execute(stmt).scalars().all()
    return TransactionList(
        user_id=user_id,
        items=[TransactionOut.model_validate(r) for r in rows],
    )


class SubscriptionOut(BaseModel):
    merchant: str
    monthly_amount: Decimal
    occurrences: int
    last_seen: date


class SubscriptionList(BaseModel):
    user_id: str
    items: list[SubscriptionOut]


@router.get("/subscriptions", response_model=SubscriptionList, tags=["subscriptions"])
def list_subscriptions(user_id: str, db: Session = Depends(get_db)) -> SubscriptionList:
    """Detect subscriptions and (idempotently) flip is_recurring on matched rows."""
    subs = mark_recurring(db, user_id)
    return SubscriptionList(
        user_id=user_id,
        items=[
            SubscriptionOut(
                merchant=s.merchant,
                monthly_amount=s.monthly_amount,
                occurrences=s.occurrences,
                last_seen=s.last_seen,
            )
            for s in subs
        ],
    )
