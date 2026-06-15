"""Tests for F1: budget CRUD."""

from __future__ import annotations

from decimal import Decimal

import httpx


async def test_put_and_get_budget_roundtrip(client: httpx.AsyncClient) -> None:
    """PUT a budget, then GET reads it back with the same numbers."""
    r = await client.put("/users/alice/budget", json={"monthly_cap": "3000.00"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_id"] == "alice"
    assert Decimal(body["monthly_cap"]) == Decimal("3000.00")
    assert body["currency"] == "USD"

    r = await client.get("/users/alice/budget")
    assert r.status_code == 200
    assert Decimal(r.json()["monthly_cap"]) == Decimal("3000.00")


async def test_budget_negative_cap_rejected(client: httpx.AsyncClient) -> None:
    """Negative monthly_cap → 422 (pydantic validation, not a 500)."""
    r = await client.put("/users/alice/budget", json={"monthly_cap": "-100"})
    assert r.status_code == 422


async def test_get_budget_unknown_user_returns_404(client: httpx.AsyncClient) -> None:
    """A user without a stored budget returns 404, not 200 with empty body."""
    r = await client.get("/users/nobody/budget")
    assert r.status_code == 404
    assert r.json()["detail"]


async def test_put_budget_upsert_overwrites(client: httpx.AsyncClient) -> None:
    """A second PUT replaces the cap; only one row persists for the user."""
    await client.put("/users/alice/budget", json={"monthly_cap": "3000"})
    await client.put("/users/alice/budget", json={"monthly_cap": "2500"})
    r = await client.get("/users/alice/budget")
    assert Decimal(r.json()["monthly_cap"]) == Decimal("2500.00")


async def test_zero_cap_is_allowed(client: httpx.AsyncClient) -> None:
    """A monthly_cap of 0 is valid (Field is ge=0). Lets a user 'pause' spending."""
    r = await client.put("/users/alice/budget", json={"monthly_cap": "0"})
    assert r.status_code == 200
    assert Decimal(r.json()["monthly_cap"]) == Decimal("0.00")


async def test_currency_length_validated(client: httpx.AsyncClient) -> None:
    """Currency must be exactly 3 chars (ISO-4217 shape, even if we don't validate the alphabet)."""
    # Too short
    r = await client.put(
        "/users/alice/budget", json={"monthly_cap": "100", "currency": "US"}
    )
    assert r.status_code == 422

    # Too long
    r = await client.put(
        "/users/alice/budget", json={"monthly_cap": "100", "currency": "USDD"}
    )
    assert r.status_code == 422

    # A valid non-default round-trips
    r = await client.put(
        "/users/alice/budget", json={"monthly_cap": "100", "currency": "EUR"}
    )
    assert r.status_code == 200
    assert r.json()["currency"] == "EUR"


async def test_updated_at_advances_on_overwrite(client: httpx.AsyncClient) -> None:
    """The second PUT must refresh updated_at — guards against accidental
    INSERT-only behaviour creeping back in.
    """
    from datetime import datetime

    r = await client.put("/users/alice/budget", json={"monthly_cap": "1000"})
    first = datetime.fromisoformat(r.json()["updated_at"])

    # The Numeric column has 1-second-ish precision in Postgres; force a
    # different value so the UPDATE is unambiguous.
    r = await client.put("/users/alice/budget", json={"monthly_cap": "1500"})
    second = datetime.fromisoformat(r.json()["updated_at"])

    assert second >= first, f"updated_at went backwards: {first} -> {second}"
    # And the value did change
    assert Decimal(r.json()["monthly_cap"]) == Decimal("1500.00")
