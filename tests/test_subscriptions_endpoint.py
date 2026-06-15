"""Tests for F6: subscription detection HTTP endpoint + is_recurring flagging.

The detection algorithm itself is unit-tested in tests/test_tools.py.
This file covers the user-facing wiring.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
from sqlalchemy.orm import Session

from app.models import Transaction


def _seed_subs(db: Session) -> None:
    """3 monthly Netflix charges + a one-off Amazon."""
    db.add_all(
        [
            Transaction(
                user_id="alice", posted_at=date(2026, 4, 5),
                description="Netflix Monthly", amount=Decimal("15.99"),
                category="entertainment",
            ),
            Transaction(
                user_id="alice", posted_at=date(2026, 5, 5),
                description="Netflix Monthly", amount=Decimal("15.99"),
                category="entertainment",
            ),
            Transaction(
                user_id="alice", posted_at=date(2026, 6, 5),
                description="Netflix Monthly", amount=Decimal("15.99"),
                category="entertainment",
            ),
            Transaction(
                user_id="alice", posted_at=date(2026, 6, 15),
                description="Amazon One-Off", amount=Decimal("42.99"),
                category="shopping",
            ),
        ]
    )
    db.commit()


async def test_subscriptions_endpoint_returns_recurring(
    client: httpx.AsyncClient, db
) -> None:
    """GET /users/{id}/transactions/subscriptions returns detected subs."""
    _seed_subs(db)
    r = await client.get("/users/alice/transactions/subscriptions")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["occurrences"] == 3
    assert Decimal(items[0]["monthly_amount"]) == Decimal("15.99")


async def test_subscriptions_endpoint_flips_is_recurring(
    client: httpx.AsyncClient, db
) -> None:
    """After hitting the endpoint, the matched rows have is_recurring=True;
    the one-off Amazon row is unchanged."""
    _seed_subs(db)
    await client.get("/users/alice/transactions/subscriptions")

    rows = (
        db.query(Transaction)
        .filter(Transaction.user_id == "alice")
        .order_by(Transaction.id)
        .all()
    )
    netflix = [t for t in rows if "Netflix" in t.description]
    amazon = [t for t in rows if "Amazon" in t.description]
    assert all(t.is_recurring for t in netflix)
    assert all(not t.is_recurring for t in amazon)


async def test_subscriptions_endpoint_empty_user_returns_empty_list(
    client: httpx.AsyncClient,
) -> None:
    r = await client.get("/users/nobody/transactions/subscriptions")
    assert r.status_code == 200
    assert r.json()["items"] == []
