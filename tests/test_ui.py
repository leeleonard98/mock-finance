"""Tests for F8: chat UI + dashboard."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
from sqlalchemy.orm import Session

from app.models import Budget, Transaction


async def test_index_renders_all_panels(client: httpx.AsyncClient) -> None:
    """The index page contains every panel marker the JS hooks expect."""
    r = await client.get("/")
    assert r.status_code == 200
    body = r.text
    for marker in (
        'id="budget-panel"',
        'id="upload-form"',
        'id="dashboard"',
        'id="chat"',
        'id="composer"',
    ):
        assert marker in body, f"missing {marker}"


async def test_dashboard_returns_aggregated_numbers(
    client: httpx.AsyncClient, db: Session
) -> None:
    """GET /users/{id}/dashboard returns the snapshot the UI expects."""
    today = date.today()
    db.add(Budget(user_id="alice", monthly_cap=Decimal("1000.00"), currency="USD"))
    db.add_all(
        [
            Transaction(
                user_id="alice", posted_at=today, description="Groceries",
                amount=Decimal("120.00"), category="food",
            ),
            Transaction(
                user_id="alice", posted_at=today, description="Uber",
                amount=Decimal("30.00"), category="transport",
            ),
        ]
    )
    db.commit()

    r = await client.get("/users/alice/dashboard")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_id"] == "alice"
    assert Decimal(body["cap"]) == Decimal("1000.00")
    assert Decimal(body["spent"]) == Decimal("150.00")
    assert Decimal(body["remaining"]) == Decimal("850.00")
    cats = {t["category"] for t in body["top_3"]}
    assert {"food", "transport"} <= cats


async def test_dashboard_no_budget_returns_null_cap(
    client: httpx.AsyncClient, db: Session
) -> None:
    """User without a budget gets cap=null and remaining=null but spent still works."""
    today = date.today()
    db.add(
        Transaction(
            user_id="bob", posted_at=today, description="Coffee",
            amount=Decimal("5.00"), category="food",
        )
    )
    db.commit()

    r = await client.get("/users/bob/dashboard")
    assert r.status_code == 200
    body = r.json()
    assert body["cap"] is None
    assert body["remaining"] is None
    assert Decimal(body["spent"]) == Decimal("5.00")
