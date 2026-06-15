"""Tests for F7: Monthly Financial Review."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
from sqlalchemy.orm import Session

from app.agents.reviewer import REVIEWER_PROMPT, ReviewerAgent
from app.models import ChatSession, Transaction


def _seed(db: Session) -> ChatSession:
    db.add_all(
        [
            Transaction(
                user_id="alice", posted_at=date(2026, 6, 1),
                description="Groceries", amount=Decimal("80.00"), category="food",
            ),
            Transaction(
                user_id="alice", posted_at=date(2026, 6, 5),
                description="Uber", amount=Decimal("12.50"), category="transport",
            ),
            Transaction(
                user_id="alice", posted_at=date(2026, 6, 8),
                description="Coffee", amount=Decimal("4.50"), category="food",
            ),
        ]
    )
    sess = ChatSession(user_id="alice", title="June review")
    db.add(sess)
    db.commit()
    db.refresh(sess)
    return sess


def test_reviewer_uses_distinct_system_prompt(db, script_llm) -> None:
    """The reviewer's system prompt is the REVIEWER_PROMPT, not advisor's."""
    sess = _seed(db)
    script_llm.script = [{"content": "ok", "tool_calls": []}]

    ReviewerAgent(db).review(sess.id, month="2026-06")
    sys_msg = script_llm.calls[0]["messages"][0]
    assert sys_msg["role"] == "system"
    assert sys_msg["content"] == REVIEWER_PROMPT


def test_reviewer_default_month_is_current(db, script_llm) -> None:
    """No month → uses today's YYYY-MM."""
    from datetime import date

    sess = _seed(db)
    script_llm.script = [{"content": "ok", "tool_calls": []}]

    ReviewerAgent(db).review(sess.id)
    today = date.today()
    expected_month = f"{today.year:04d}-{today.month:02d}"
    user_msg = script_llm.calls[0]["messages"][1]
    assert expected_month in user_msg["content"]


async def test_review_endpoint_runs_with_explicit_month(
    client: httpx.AsyncClient, script_llm, db
) -> None:
    """End-to-end: POST /review with a month → 200, response has the final."""
    _seed(db)
    r = await client.post("/sessions", json={"user_id": "alice"})
    sid = r.json()["id"]

    script_llm.script = [
        {
            "content": "",
            "tool_calls": [
                {
                    "name": "aggregate_by_category",
                    "arguments": {"user_id": "alice", "month": "2026-06"},
                }
            ],
        },
        {"content": "You spent the most on food this month.", "tool_calls": []},
    ]

    r = await client.post(f"/sessions/{sid}/review", json={"month": "2026-06"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["final"] == "You spent the most on food this month."
    # The aggregate tool was actually called and got real data
    assert len(body["tool_calls"]) == 1
    result = body["tool_calls"][0]["result"]
    assert Decimal(result["by_category"]["food"]) == Decimal("84.50")  # 80 + 4.50


async def test_review_endpoint_invalid_month_returns_422(
    client: httpx.AsyncClient,
) -> None:
    """Pattern validation: '2026-6' (single digit) → 422."""
    r = await client.post("/sessions", json={"user_id": "alice"})
    sid = r.json()["id"]
    r = await client.post(f"/sessions/{sid}/review", json={"month": "2026-6"})
    assert r.status_code == 422
