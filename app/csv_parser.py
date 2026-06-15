"""F2: bank-statement CSV parser.

Pure function over bytes → list of ParsedRow. No DB, no LLM, no FastAPI
import — easy to test in isolation.

Three CSV shapes are supported (heuristic column detection by header name):
  1. single Amount column     — positive=outflow, negative=income (most banks)
  2. separate Debit/Credit    — Debit positive, Credit positive (income); we
                                 keep only Debit rows
  3. Amount + Type column     — Amount always positive; Type='debit'|'credit'

Income rows (credit / negative amount) are dropped. We track spend, not income.

Date parsing tries ISO 8601 first, then MM/DD/YYYY. We pick the format that
parses every row in the file; ambiguous dates raise a clear error.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import StringIO

from app.config import get_settings


@dataclass(frozen=True)
class ParsedRow:
    """One outflow row. amount is always positive."""

    posted_at: date
    description: str
    amount: Decimal


class CSVParseError(ValueError):
    """Raised with a row-level message when parsing fails."""


# Header aliases. Lowercased before lookup; first match wins.
_DATE_KEYS = ("date", "posted date", "transaction date", "posting date")
_DESC_KEYS = ("description", "memo", "details", "narrative", "name")
_AMOUNT_KEYS = ("amount",)
_DEBIT_KEYS = ("debit", "debit amount")
_CREDIT_KEYS = ("credit", "credit amount")
_TYPE_KEYS = ("type", "transaction type")

_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y")

# Per-field length caps — defends against single-row DoS (4.9 MB description
# under the 5 MB byte cap, etc.). Generous but bounded.
_MAX_DESC_LEN = 1024
_MAX_AMOUNT_LEN = 32
_MAX_DATE_LEN = 32


def _normalise_headers(reader_fields: list[str]) -> dict[str, str]:
    """Map lowercased+stripped header → original header."""
    return {h.strip().lower(): h for h in reader_fields}


def _pick(header_map: dict[str, str], candidates: tuple[str, ...]) -> str | None:
    for c in candidates:
        if c in header_map:
            return header_map[c]
    return None


def _parse_date_with_format(raw: str, fmt: str) -> date | None:
    try:
        return datetime.strptime(raw.strip(), fmt).date()
    except ValueError:
        return None


def _detect_date_format(samples: list[str]) -> str:
    """Pick a single date format that parses every non-empty sample.

    If multiple formats fit (e.g. 06/07/2026 is ambiguous as MM/DD or DD/MM),
    we look for a sample that disambiguates — first component > 12 forces
    DD/MM; second component > 12 forces MM/DD. If nothing disambiguates,
    raise CSVParseError so we don't silently mis-date.
    """
    non_empty = [s.strip() for s in samples if s.strip()]
    if not non_empty:
        raise CSVParseError("no dates found in CSV")

    survivors: list[str] = []
    for fmt in _DATE_FORMATS:
        if all(_parse_date_with_format(s, fmt) is not None for s in non_empty):
            survivors.append(fmt)

    if not survivors:
        raise CSVParseError(f"unrecognised date format (sample: {non_empty[0]!r})")
    if len(survivors) == 1:
        return survivors[0]

    # Multiple survivors — try to disambiguate MM/DD vs DD/MM by inspecting
    # numeric components. We only care when both slash-formats survive.
    if "%m/%d/%Y" in survivors and "%d/%m/%Y" in survivors:
        for s in non_empty:
            parts = s.split("/")
            if len(parts) != 3:
                continue
            try:
                a, b = int(parts[0]), int(parts[1])
            except ValueError:
                continue
            if a > 12:
                return "%d/%m/%Y"
            if b > 12:
                return "%m/%d/%Y"
        raise CSVParseError(
            "ambiguous date format — could be MM/DD/YYYY or DD/MM/YYYY"
        )

    # ISO + something else both worked? Prefer ISO (it's unambiguous).
    return "%Y-%m-%d"


def _parse_decimal(raw: str, row_no: int, field: str) -> Decimal:
    if len(raw) > _MAX_AMOUNT_LEN:
        raise CSVParseError(f"row {row_no}: {field} value too long")
    cleaned = raw.strip().replace(",", "").replace("$", "")
    if not cleaned:
        return Decimal("0")
    try:
        return Decimal(cleaned)
    except InvalidOperation as e:
        raise CSVParseError(
            f"row {row_no}: invalid {field} value {raw!r}"
        ) from e


def parse_csv(raw: bytes, *, max_rows: int | None = None) -> list[ParsedRow]:
    """Parse a bank-statement CSV into a list of outflow rows."""
    settings = get_settings()
    cap = max_rows if max_rows is not None else settings.MAX_UPLOAD_ROWS

    text = raw.decode("utf-8-sig")  # tolerate BOM
    reader = csv.DictReader(StringIO(text))
    if reader.fieldnames is None:
        raise CSVParseError("CSV has no header row")

    headers = _normalise_headers(list(reader.fieldnames))
    date_col = _pick(headers, _DATE_KEYS)
    desc_col = _pick(headers, _DESC_KEYS)
    amount_col = _pick(headers, _AMOUNT_KEYS)
    debit_col = _pick(headers, _DEBIT_KEYS)
    credit_col = _pick(headers, _CREDIT_KEYS)
    type_col = _pick(headers, _TYPE_KEYS)

    if date_col is None:
        raise CSVParseError("missing required column: date")
    if desc_col is None:
        raise CSVParseError("missing required column: description")
    if amount_col is None and not (debit_col or credit_col):
        raise CSVParseError("missing required column: amount (or debit/credit)")

    # Detect date format file-wide (one pass, then one parse pass) — fixes the
    # silent MM/DD vs DD/MM mis-parsing the per-row first-match-wins loop had.
    all_rows = list(reader)
    if len(all_rows) > cap:
        raise CSVParseError(f"too many rows (cap={cap})")
    date_fmt = _detect_date_format([r.get(date_col, "") for r in all_rows])

    rows: list[ParsedRow] = []
    for i, raw_row in enumerate(all_rows, start=2):  # row 1 is the header
        date_raw = (raw_row.get(date_col, "") or "")[:_MAX_DATE_LEN]
        d = _parse_date_with_format(date_raw, date_fmt)
        if d is None:
            raise CSVParseError(f"row {i}: invalid date {date_raw!r}")

        description = (raw_row.get(desc_col) or "").strip()
        if len(description) > _MAX_DESC_LEN:
            raise CSVParseError(f"row {i}: description too long")
        if not description:
            description = "(no description)"

        amount: Decimal
        if amount_col is not None:
            amount = _parse_decimal(raw_row.get(amount_col, ""), i, "amount")
            if type_col is not None:
                tval = (raw_row.get(type_col) or "").strip().lower()
                if tval in ("credit", "cr"):
                    amount = -abs(amount)
                elif tval in ("debit", "dr"):
                    amount = abs(amount)
        else:
            debit_raw = raw_row.get(debit_col, "") if debit_col else ""
            credit_raw = raw_row.get(credit_col, "") if credit_col else ""
            if debit_raw.strip():
                amount = _parse_decimal(debit_raw, i, "debit")
            elif credit_raw.strip():
                amount = -_parse_decimal(credit_raw, i, "credit")
            else:
                continue

        if amount <= 0:
            continue

        rows.append(ParsedRow(posted_at=d, description=description, amount=amount))

    return rows
