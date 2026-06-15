"""Tests for F2: CSV upload HTTP endpoint."""

from __future__ import annotations

from decimal import Decimal

import httpx

from app.models import Transaction


async def test_upload_persists_rows(client: httpx.AsyncClient, db) -> None:
    """Happy path: upload a small CSV → 201, rows in DB with correct fields."""
    csv_bytes = (
        b"Date,Description,Amount\n"
        b"2026-06-01,Coffee,4.50\n"
        b"2026-06-02,Uber,12.00\n"
    )
    files = {"file": ("test.csv", csv_bytes, "text/csv")}
    r = await client.post("/users/alice/transactions/upload", files=files)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["count"] == 2
    assert body["filename"] == "test.csv"

    rows = (
        db.query(Transaction)
        .filter(Transaction.user_id == "alice")
        .order_by(Transaction.id)
        .all()
    )
    assert len(rows) == 2
    assert rows[0].description == "Coffee"
    assert rows[0].amount == Decimal("4.50")
    assert rows[0].category == "other"  # F3 will replace this
    assert rows[0].source_file == "test.csv"


async def test_upload_malformed_csv_returns_422(client: httpx.AsyncClient) -> None:
    """Garbage in → 422 with a row-level message, not a 500."""
    files = {"file": ("bad.csv", b"not-a-csv-at-all", "text/csv")}
    r = await client.post("/users/alice/transactions/upload", files=files)
    assert r.status_code == 422
    assert "detail" in r.json()


async def test_upload_too_large_returns_413(client: httpx.AsyncClient) -> None:
    """File over MAX_UPLOAD_BYTES → 413 (DoS protection)."""
    # Build a payload larger than 5 MB
    huge_lines = b"2026-06-01,X,1.00\n" * 350_000
    payload = b"Date,Description,Amount\n" + huge_lines
    files = {"file": ("big.csv", payload, "text/csv")}
    r = await client.post("/users/alice/transactions/upload", files=files)
    assert r.status_code == 413


async def test_get_transactions_filters_by_date_range(
    client: httpx.AsyncClient, db
) -> None:
    """After upload, GET supports date-range filtering."""
    csv_bytes = (
        b"Date,Description,Amount\n"
        b"2026-05-15,May Coffee,3.00\n"
        b"2026-06-01,June Coffee,4.00\n"
        b"2026-06-30,Late June,5.00\n"
    )
    files = {"file": ("t.csv", csv_bytes, "text/csv")}
    await client.post("/users/alice/transactions/upload", files=files)

    r = await client.get(
        "/users/alice/transactions",
        params={"from_date": "2026-06-01", "to_date": "2026-06-30"},
    )
    assert r.status_code == 200
    items = r.json()["items"]
    descriptions = [t["description"] for t in items]
    assert "June Coffee" in descriptions
    assert "Late June" in descriptions
    assert "May Coffee" not in descriptions
