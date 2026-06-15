"""Tests for F4: tools layer (registry + 4 tools).

F6's subscription detection algorithm is tested here too since the tool
wrapper is in F4. F5's recommend tool wraps the LLM and lives in F5.
"""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.models import Budget, Transaction
from app.subscriptions import detect
from app.tools import registry
from app.tools.aggregate import aggregate_by_category
from app.tools.budget import calculate_remaining_budget, _month_bounds
from app.tools.transactions import get_transactions


# ---------------------------------------------------------------------------
# Pure-function tool tests
# ---------------------------------------------------------------------------


def _seed_user_with_transactions(db) -> None:
    db.add(Budget(user_id="alice", monthly_cap=Decimal("1000.00"), currency="USD"))
    txs = [
        Transaction(
            user_id="alice", posted_at=date(2026, 6, 1), description="Coffee",
            amount=Decimal("5.00"), category="food",
        ),
        Transaction(
            user_id="alice", posted_at=date(2026, 6, 5), description="Uber",
            amount=Decimal("12.50"), category="transport",
        ),
        Transaction(
            user_id="alice", posted_at=date(2026, 6, 10), description="Coffee 2",
            amount=Decimal("4.50"), category="food",
        ),
        Transaction(
            user_id="alice", posted_at=date(2026, 5, 30), description="Old",
            amount=Decimal("100.00"), category="other",
        ),
    ]
    for t in txs:
        db.add(t)
    db.commit()


def test_get_transactions_filters_by_category(db) -> None:
    _seed_user_with_transactions(db)
    rows = get_transactions(db=db, user_id="alice", category="food")
    assert len(rows) == 2
    assert all(r["category"] == "food" for r in rows)


def test_calculate_remaining_budget_math(db) -> None:
    _seed_user_with_transactions(db)
    out = calculate_remaining_budget(db=db, user_id="alice", month="2026-06")
    # June: 5 + 12.50 + 4.50 = 22.00 spent; cap 1000 → remaining 978
    assert Decimal(out["spent"]) == Decimal("22.00")
    assert Decimal(out["remaining"]) == Decimal("978.00")
    assert out["currency"] == "USD"


def test_calculate_remaining_budget_no_budget_returns_error(db) -> None:
    out = calculate_remaining_budget(db=db, user_id="nobody", month="2026-06")
    assert "error" in out


def test_aggregate_by_category_sums_match(db) -> None:
    _seed_user_with_transactions(db)
    out = aggregate_by_category(db=db, user_id="alice", month="2026-06")
    assert Decimal(out["by_category"]["food"]) == Decimal("9.50")
    assert Decimal(out["by_category"]["transport"]) == Decimal("12.50")
    # 'other' is in May, not June — must NOT appear
    assert "other" not in out["by_category"]


def test_month_bounds_year_rollover() -> None:
    """December rolls into January next year."""
    start, end = _month_bounds("2026-12")
    assert start == date(2026, 12, 1)
    assert end == date(2027, 1, 1)


# ---------------------------------------------------------------------------
# Subscription detection (F6 algorithm — pure function)
# ---------------------------------------------------------------------------


def _tx(id_: int, desc: str, amount: str, day: int) -> Transaction:
    return Transaction(
        id=id_, user_id="alice", posted_at=date(2026, day // 30 + 4, day % 30 or 1),
        description=desc, amount=Decimal(amount), category="other",
    )


def test_three_uniform_monthly_charges_detected() -> None:
    """Same merchant, three months → flagged."""
    txs = [
        _tx(1, "Netflix Monthly", "15.99", 5),
        _tx(2, "Netflix Monthly", "15.99", 35),
        _tx(3, "Netflix Monthly", "15.99", 65),
    ]
    subs = detect(txs)
    assert len(subs) == 1
    assert subs[0].occurrences == 3
    assert subs[0].monthly_amount == Decimal("15.99")


def test_one_off_amazon_not_flagged() -> None:
    """Single occurrence below min_occurrences → NOT flagged."""
    txs = [_tx(1, "Amazon.com", "42.99", 5)]
    assert detect(txs) == []


def test_amount_within_tolerance_flagged() -> None:
    """Gym charges with <10% variation pass."""
    txs = [
        _tx(1, "FitClub Gym", "50.00", 5),
        _tx(2, "FitClub Gym", "52.00", 35),
        _tx(3, "FitClub Gym", "48.00", 65),
    ]
    subs = detect(txs)
    assert len(subs) == 1


def test_amount_outside_tolerance_not_flagged() -> None:
    """Wildly different amounts → NOT flagged (it's not really recurring)."""
    txs = [
        _tx(1, "Random Merchant", "50.00", 5),
        _tx(2, "Random Merchant", "50.00", 35),
        _tx(3, "Random Merchant", "5000.00", 65),
    ]
    assert detect(txs) == []


# ---------------------------------------------------------------------------
# Registry / OpenAI schemas
# ---------------------------------------------------------------------------


def test_registry_lists_four_tools() -> None:
    """F4 wires four tools; F5 will add 'recommend'."""
    names = set(registry.names())
    assert {
        "get_transactions",
        "calculate_remaining_budget",
        "aggregate_by_category",
        "detect_subscriptions",
    } <= names


def test_openai_schemas_have_no_dangling_refs() -> None:
    """Every $ref in an emitted schema must resolve in that schema's $defs."""
    schemas = registry.openai_schemas()
    ref_pattern = re.compile(r'"\$ref"\s*:\s*"#/\$defs/([^"]+)"')
    for s in schemas:
        params = s["function"]["parameters"]
        blob = json.dumps(params)
        refs = ref_pattern.findall(blob)
        if not refs:
            continue
        assert "$defs" in params
        for ref in refs:
            assert ref in params["$defs"]


def test_db_kwarg_excluded_from_openai_schemas() -> None:
    """The runtime-injected `db` must NOT appear in any tool's parameters."""
    schemas = registry.openai_schemas()
    for s in schemas:
        props = s["function"]["parameters"]["properties"]
        assert "db" not in props, f"{s['function']['name']} leaked 'db' to OpenAI"


# ---------------------------------------------------------------------------
# HTTP route
# ---------------------------------------------------------------------------


async def test_tool_invoke_endpoint_dispatches(client: httpx.AsyncClient, db) -> None:
    """POST /tools/calculate_remaining_budget/invoke runs and returns the result."""
    db.add(Budget(user_id="alice", monthly_cap=Decimal("1000.00")))
    db.commit()
    r = await client.post(
        "/tools/calculate_remaining_budget/invoke",
        json={"args": {"user_id": "alice", "month": "2026-06"}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "calculate_remaining_budget"
    assert body["result"]["cap"] == "1000.00"


async def test_tool_invoke_unknown_returns_404(client: httpx.AsyncClient) -> None:
    r = await client.post("/tools/no_such_tool/invoke", json={"args": {}})
    assert r.status_code == 404


async def test_tool_invoke_bad_args_returns_422(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/tools/calculate_remaining_budget/invoke",
        json={"args": {"user_id": "alice", "month": "not-a-month"}},
    )
    assert r.status_code == 422
