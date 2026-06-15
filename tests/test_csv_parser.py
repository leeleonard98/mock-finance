"""Tests for F2: CSV parser (pure function, no DB, no LLM)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.csv_parser import CSVParseError, parse_csv


def test_parses_simple_amount_csv() -> None:
    """Most-common shape: Date, Description, Amount (positive=outflow)."""
    raw = b"Date,Description,Amount\n2026-06-01,Coffee,4.50\n2026-06-02,Uber,12.00\n"
    rows = parse_csv(raw)
    assert len(rows) == 2
    assert rows[0].posted_at.isoformat() == "2026-06-01"
    assert rows[0].description == "Coffee"
    assert rows[0].amount == Decimal("4.50")
    assert rows[1].description == "Uber"


def test_drops_income_rows() -> None:
    """Rows with negative amount = income/credit; we track spend only."""
    raw = b"Date,Description,Amount\n2026-06-01,Salary,-3000.00\n2026-06-02,Coffee,4.50\n"
    rows = parse_csv(raw)
    assert len(rows) == 1
    assert rows[0].description == "Coffee"


def test_handles_separate_debit_credit_columns() -> None:
    """Some banks emit Debit and Credit as separate columns."""
    raw = (
        b"Date,Description,Debit,Credit\n"
        b"2026-06-01,Coffee,4.50,\n"
        b"2026-06-02,Salary,,3000.00\n"
    )
    rows = parse_csv(raw)
    assert len(rows) == 1
    assert rows[0].description == "Coffee"
    assert rows[0].amount == Decimal("4.50")


def test_malformed_amount_raises_with_row_message() -> None:
    """Bad amount → CSVParseError with the offending row number for debugging."""
    raw = b"Date,Description,Amount\n2026-06-01,Coffee,not-a-number\n"
    with pytest.raises(CSVParseError, match="row 2"):
        parse_csv(raw)


def test_missing_required_column_raises() -> None:
    """No date column at all → clear error at parse time, not silent skip."""
    raw = b"Description,Amount\nCoffee,4.50\n"
    with pytest.raises(CSVParseError, match="date"):
        parse_csv(raw)


def test_strips_utf8_bom_and_whitespace() -> None:
    """Excel often saves CSV with a UTF-8 BOM. Headers may have stray whitespace."""
    raw = "﻿Date, Description ,Amount\n2026-06-01,Coffee,4.50\n".encode()
    rows = parse_csv(raw)
    assert len(rows) == 1
    assert rows[0].description == "Coffee"


def test_row_count_cap_enforced() -> None:
    """Row cap (DoS protection) — we deliberately wire a small cap for the test."""
    raw = b"Date,Description,Amount\n" + b"".join(
        f"2026-06-01,X{i},1.00\n".encode() for i in range(20)
    )
    with pytest.raises(CSVParseError, match="too many rows"):
        parse_csv(raw, max_rows=10)


def test_dd_mm_format_detected_when_day_over_12() -> None:
    """DD/MM disambiguation: 13/06/2026 forces DD/MM (month=13 invalid)."""
    raw = (
        b"Date,Description,Amount\n"
        b"13/06/2026,Coffee,4.50\n"  # day=13 → must be DD/MM
        b"01/07/2026,Lunch,8.00\n"
    )
    rows = parse_csv(raw)
    # 13/06 = 13 June, 01/07 = 1 July under DD/MM
    assert rows[0].posted_at.isoformat() == "2026-06-13"
    assert rows[1].posted_at.isoformat() == "2026-07-01"


def test_ambiguous_dates_raise() -> None:
    """When MM/DD and DD/MM both fit and nothing disambiguates, raise."""
    raw = b"Date,Description,Amount\n06/07/2026,Coffee,4.50\n"
    with pytest.raises(CSVParseError, match="ambiguous"):
        parse_csv(raw)


def test_oversized_description_rejected() -> None:
    """Per-field DoS guard: a 5KB description is rejected, not silently stored."""
    huge_desc = "X" * 5000
    raw = f"Date,Description,Amount\n2026-06-01,{huge_desc},1.00\n".encode()
    with pytest.raises(CSVParseError, match="description too long"):
        parse_csv(raw)
