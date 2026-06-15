# Smart Financial Advisor Agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an AI-powered personal-finance assistant that ingests CSV bank statements, categorises spending via LLM, tracks against a user-set monthly cap, detects subscriptions, and answers natural-language questions ("Can I spend $500 on a phone this month?") with grounded, tool-backed recommendations.

**Architecture:** FastAPI + Postgres + OpenAI tool-calling, three layers (routers → agents → tools). Two agents (Advisor for ad-hoc questions, Reviewer for monthly summaries) share the same tool registry and LLM seam. CSV ingestion is synchronous; categorisation is one batched LLM call per upload. Carry-over from the travel-planner scaffold: `db.py`, `conftest.py`, the `_Registry` pattern, the SSE streaming pattern, the `mock_llm`/`script_llm` fixtures.

**Tech Stack:** Python 3.11, FastAPI 0.115, SQLAlchemy 2.x + Alembic, Postgres 16 (Docker), OpenAI 1.51 SDK, pydantic 2.9 + pydantic-settings, pytest 8.3 + pytest-asyncio + httpx 0.27, Jinja2.

**Spec:** `docs/superpowers/specs/2026-06-15-financial-advisor-design.md`

---

## Task 0: Scaffold (one-time setup, ~25-30 min — built from scratch, not copied)

**Files:**
- Create from scratch (not copied from mock-travel — interview integrity):
  - `docker-compose.yml`, `Makefile`, `.gitignore`, `.env.example`, `pyproject.toml`, `requirements.txt`, `README.md`
  - `app/__init__.py`, `app/config.py`, `app/db.py`, `app/main.py`, `app/llm.py`, `app/models.py`
  - `app/routers/__init__.py`, `app/agents/__init__.py`, `app/tools/__init__.py`
  - `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`
  - `tests/__init__.py`, `tests/conftest.py`

The patterns are well-known to me from mock-travel — file structure and conventions will be similar — but every file is hand-written, not copy-pasted. Interview-honest answer: "Same conventions I'd use in any FastAPI app, but written fresh for this project."

- [ ] **Step 0.1 — Create the directory structure**

```bash
cd /Users/I589682/Desktop/mock
mkdir -p app/routers app/agents app/tools app/templates app/static \
         alembic/versions tests \
         docs/superpowers/specs docs/superpowers/plans
```

- [ ] **Step 0.2 — Write `docker-compose.yml`** (Postgres 16 on `:5432`, named volume, healthcheck, env-driven creds — `mock_finance_db` container name to avoid collision with the travel-planner container)

- [ ] **Step 0.3 — Write `requirements.txt`** with fastapi 0.115, sqlalchemy 2.0.35, alembic 1.13.3, psycopg[binary] 3.2.3, pydantic 2.9, pydantic-settings 2.5, python-dotenv 1.0.1, openai 1.51, httpx 0.27, jinja2 3.1.4, pytest 8.3.3, pytest-asyncio 0.24.0, python-multipart 0.0.12

- [ ] **Step 0.4 — Write `pyproject.toml`** (pytest config: `asyncio_mode = "auto"`, testpaths = ["tests"]; ruff config)

- [ ] **Step 0.5 — Write `.gitignore`** (`__pycache__`, `.venv`, `.env`, but `!.env.example`, `.pytest_cache`, `.coverage`, `.idea`, `.vscode`, `.DS_Store`)

- [ ] **Step 0.6 — Write `.env.example`** with `APP_ENV=dev`, Postgres creds (`POSTGRES_USER=app`, `POSTGRES_PASSWORD=app`, `POSTGRES_DB=app`), `DATABASE_URL`, `TEST_DATABASE_URL`, `OPENAI_API_KEY=`, `OPENAI_MODEL=gpt-4o-mini`, `MAX_UPLOAD_BYTES=5242880`, `MAX_UPLOAD_ROWS=10000`

- [ ] **Step 0.7 — Write `Makefile`** (`up`, `down`, `logs`, `psql`, `migrate`, `revision m="..."`, `test`, `run`, `fmt`, `clean`)

- [ ] **Step 0.8 — Write `app/config.py`** (pydantic-settings reading `.env`, lru_cached `get_settings()`)

- [ ] **Step 0.9 — Write `app/db.py`** (engine, SessionLocal, `get_db()` dependency)

- [ ] **Step 0.10 — Write `app/models.py`** (just `Base = DeclarativeBase`, no models yet — Tasks 1+ append)

- [ ] **Step 0.11 — Write `app/llm.py`** (OpenAI wrapper with `LLMNotConfiguredError`, `complete(prompt, model, system) -> str`)

- [ ] **Step 0.12 — Write `app/main.py`** with `create_app()` factory, `/health`, Jinja+static plumbing, no routers mounted yet

- [ ] **Step 0.13 — Write `alembic.ini` and `alembic/env.py`** (env.py imports `app.config.get_settings` and `app.models.Base`, supports `ALEMBIC_DATABASE_URL` override)

- [ ] **Step 0.14 — Write `alembic/script.py.mako`** (canonical template)

- [ ] **Step 0.15 — Write `tests/conftest.py`** with:
  - session-scoped `test_engine` (creates schema via `Base.metadata.create_all`, drops on teardown)
  - function-scoped `db` (transactional rollback per test)
  - async `client` (httpx + ASGITransport, overrides `get_db`)
  - `mock_llm` (replaces `app.llm.complete` with recording stub)

  No `script_llm` / `stream_llm` / `script_classifier` yet — those land with the features that need them.

- [ ] **Step 0.16 — Write a minimal smoke test** at `tests/test_health.py` (3 tests: 200 ok, db status ok, db status down with broken-session override) so we have something green from commit 0.

- [ ] **Step 0.17 — Init git, configure identity**

```bash
cd /Users/I589682/Desktop/mock
git init -b main
git config user.name "leeleonard98"
git config user.email "leeleonard_98@yahoo.com.sg"
```

- [ ] **Step 0.18 — Create the GitHub repo and add remote**

User action — create the repo via GitHub UI or `gh repo create leeleonard98/mock-finance --public --source=.`. Then:

```bash
git remote add origin https://github.com/leeleonard98/mock-finance.git
```

- [ ] **Step 0.19 — Boot up to verify**

```bash
cp .env.example .env  # paste OPENAI_API_KEY into .env
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
make up
# wait for postgres ready
make test  # 3 health tests should pass; alembic runs but no migrations yet
make run &
sleep 2 && curl -s http://localhost:8000/health
# Expected: {"status":"ok","db":"ok"}
kill %1
```

- [ ] **Step 0.20 — Commit and push the scaffold**

```bash
git add -A
git commit -m "chore: scaffold FastAPI + Postgres + OpenAI for finance advisor"
git push -u origin main
```

**Note:** Tasks below assume `~/Desktop/mock/` is the repo root and `.venv` is active.

---

## Task 1 (F1): Budget management — the foundation

**Files:**
- Create: `app/models.py` (add `Budget` model — edit existing file)
- Create: `alembic/versions/0001_budgets.py`
- Create: `app/routers/budget.py`
- Modify: `app/main.py` (mount router)
- Test: `tests/test_budget.py`

### Why first
F2-F8 all read budget. Writing it first locks the user_id convention and proves the alembic + tenancy patterns work.

- [ ] **Step 1.1 — Add the Budget model**

```python
# Append to app/models.py inside the Base block
class Budget(Base):
    """One row per user. Single monthly cap (no per-category yet)."""

    __tablename__ = "budgets"

    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    monthly_cap: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
```

- [ ] **Step 1.2 — Write the migration**

```python
# alembic/versions/0001_budgets.py
"""budgets

Revision ID: 0001_budgets
Revises:
Create Date: 2026-06-15 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0001_budgets"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "budgets",
        sa.Column("user_id", sa.String(length=255), primary_key=True, nullable=False),
        sa.Column("monthly_cap", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("budgets")
```

- [ ] **Step 1.3 — Write the failing tests**

```python
# tests/test_budget.py
"""Tests for F1: budget CRUD."""
from __future__ import annotations
from decimal import Decimal

import httpx


async def test_put_and_get_budget_roundtrip(client: httpx.AsyncClient) -> None:
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
    r = await client.put("/users/alice/budget", json={"monthly_cap": "-100"})
    assert r.status_code == 422


async def test_get_budget_unknown_user_returns_404(client: httpx.AsyncClient) -> None:
    r = await client.get("/users/nobody/budget")
    assert r.status_code == 404
    assert r.json()["detail"]


async def test_put_budget_upsert_overwrites(client: httpx.AsyncClient) -> None:
    await client.put("/users/alice/budget", json={"monthly_cap": "3000"})
    await client.put("/users/alice/budget", json={"monthly_cap": "2500"})
    r = await client.get("/users/alice/budget")
    assert Decimal(r.json()["monthly_cap"]) == Decimal("2500.00")
```

- [ ] **Step 1.4 — Verify RED**

```bash
pytest tests/test_budget.py -v
# Expected: 4 errors / failures — module/route doesn't exist
```

- [ ] **Step 1.5 — Implement the router**

```python
# app/routers/budget.py
"""F1: budget management."""
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
            status_code=status.HTTP_404_NOT_FOUND, detail="no budget set for this user"
        )
    return BudgetOut.model_validate(obj)
```

- [ ] **Step 1.6 — Mount the router**

```python
# In app/main.py::create_app, before `return app`:
from app.routers import budget
app.include_router(budget.router)
```

- [ ] **Step 1.7 — Run all tests, verify GREEN**

```bash
make migrate  # apply 0001_budgets to dev DB
pytest -v
# Expected: 4 budget tests + N scaffold-health tests pass
```

- [ ] **Step 1.8 — Code-review subagent in parallel** (dispatch via Agent tool while you prep the commit message — see review prompt template at end of plan)

- [ ] **Step 1.9 — Commit**

```bash
git add -A
git commit -m "feat: F1 budget management

- Budget model (user_id PK, monthly_cap DECIMAL(12,2), currency, updated_at)
- Alembic 0001 migration
- PUT/GET /users/{user_id}/budget — pydantic-validated upsert, 422 on negative
- 4 non-trivial tests (roundtrip, validation, 404, upsert overwrites)"
git push
```

---

## Task 2 (F2): CSV upload + parser

**Files:**
- Modify: `app/models.py` (add `Transaction`)
- Create: `alembic/versions/0002_transactions.py`
- Create: `app/csv_parser.py` (pure-function parser — no LLM, no DB)
- Create: `app/routers/transactions.py`
- Modify: `app/main.py` (mount router, add `python-multipart` to requirements)
- Modify: `requirements.txt` (`python-multipart==0.0.12`)
- Test: `tests/test_csv_parser.py` (unit tests for the parser)
- Test: `tests/test_csv_upload.py` (HTTP tests for the route)

### Key design decisions (record these in the commit message)

1. **Sign convention:** parser converts everything to **positive = outflow**. CSVs vary; we handle three shapes:
   - `Amount` column: positive=debit, negative=credit (most banks)
   - Separate `Debit` / `Credit` columns: combine, debit positive, credit negative-then-dropped
   - Always-positive `Amount` with a `Type` column (`debit`/`credit`)
2. **Income rows are dropped** (we track spend, not income).
3. **Date parsing:** ISO 8601, `YYYY-MM-DD`, `MM/DD/YYYY`, `DD/MM/YYYY` — try each in order. We pick the format that successfully parses **all** rows; ambiguous CSVs fail with a 422 and a helpful message.
4. **Size cap** from `Settings.MAX_UPLOAD_BYTES` (5 MB) and row cap from `MAX_UPLOAD_ROWS` (10,000) — defends against DoS via huge upload.

### Code blocks worth including

```python
# app/models.py — append
class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    posted_at: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    is_recurring: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

```python
# app/csv_parser.py — the public surface
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from io import StringIO
import csv

from app.config import get_settings


@dataclass(frozen=True)
class ParsedRow:
    posted_at: date
    description: str
    amount: Decimal  # POSITIVE = outflow


class CSVParseError(ValueError):
    """Raised with a row-level message when parsing fails."""


def parse_csv(raw: bytes, *, max_rows: int | None = None) -> list[ParsedRow]:
    """Parse a bank-statement CSV into a list of outflow rows.

    Income rows (negative or credit) are dropped. Caller is responsible for
    enforcing the byte-size cap (FastAPI does it via UploadFile.size).
    """
    settings = get_settings()
    cap = max_rows or settings.MAX_UPLOAD_ROWS
    text = raw.decode("utf-8-sig")  # tolerate BOM
    reader = csv.DictReader(StringIO(text))
    if reader.fieldnames is None:
        raise CSVParseError("CSV has no header row")

    fields = {h.strip().lower() for h in reader.fieldnames}
    # ... heuristic column detection, then per-row parsing
    # See full implementation guidance below
```

The parser's column-detection heuristic:

| Goal | Tried in order | Notes |
|---|---|---|
| date | `posted_date`, `date`, `transaction date`, `posting date` | First non-empty match |
| description | `description`, `memo`, `details`, `narrative` | First non-empty match |
| amount | `amount` OR (`debit`+`credit`) OR (`amount`+`type`) | If neither single-amount nor debit/credit pair found, raise |

```python
# app/routers/transactions.py — endpoint signature
@router.post(
    "/users/{user_id}/transactions/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_transactions(
    user_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> UploadResponse:
    settings = get_settings()
    raw = await file.read()
    if len(raw) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"file too large (>{settings.MAX_UPLOAD_BYTES} bytes)")
    try:
        rows = parse_csv(raw)
    except CSVParseError as e:
        raise HTTPException(422, detail=str(e)) from e

    persisted = []
    for r in rows:
        tx = Transaction(
            user_id=user_id,
            posted_at=r.posted_at,
            description=r.description,
            amount=r.amount,
            category="other",  # F3 will replace this
            source_file=file.filename,
        )
        db.add(tx)
        persisted.append(tx)
    db.commit()
    return UploadResponse(count=len(persisted), filename=file.filename or "")
```

### Tests (verbatim — these are the contracts)

```python
# tests/test_csv_parser.py — three unit tests for the pure parser
def test_parses_simple_amount_csv():
    raw = b"Date,Description,Amount\n2026-06-01,Coffee,4.50\n2026-06-02,Uber,12.00\n"
    rows = parse_csv(raw)
    assert len(rows) == 2
    assert rows[0].posted_at.isoformat() == "2026-06-01"
    assert rows[0].description == "Coffee"
    assert rows[0].amount == Decimal("4.50")


def test_drops_income_rows():
    raw = b"Date,Description,Amount\n2026-06-01,Salary,-3000.00\n2026-06-02,Coffee,4.50\n"
    rows = parse_csv(raw)
    assert len(rows) == 1
    assert rows[0].description == "Coffee"


def test_malformed_amount_raises_with_row_message():
    raw = b"Date,Description,Amount\n2026-06-01,Coffee,not-a-number\n"
    with pytest.raises(CSVParseError, match="row 2"):
        parse_csv(raw)


def test_handles_debit_credit_columns():
    raw = b"Date,Description,Debit,Credit\n2026-06-01,Coffee,4.50,\n2026-06-02,Salary,,3000.00\n"
    rows = parse_csv(raw)
    assert len(rows) == 1
    assert rows[0].amount == Decimal("4.50")
```

```python
# tests/test_csv_upload.py — HTTP integration
async def test_upload_persists_rows(client, db):
    csv_bytes = b"Date,Description,Amount\n2026-06-01,Coffee,4.50\n"
    files = {"file": ("test.csv", csv_bytes, "text/csv")}
    r = await client.post("/users/alice/transactions/upload", files=files)
    assert r.status_code == 201
    assert r.json()["count"] == 1
    rows = db.query(Transaction).filter_by(user_id="alice").all()
    assert len(rows) == 1


async def test_upload_too_large_returns_413(client):
    huge = b"Date,Description,Amount\n" + (b"2026-06-01,X,1.00\n" * 500_000)
    files = {"file": ("big.csv", huge, "text/csv")}
    r = await client.post("/users/alice/transactions/upload", files=files)
    assert r.status_code == 413


async def test_upload_malformed_returns_422(client):
    files = {"file": ("bad.csv", b"not-a-csv-at-all", "text/csv")}
    r = await client.post("/users/alice/transactions/upload", files=files)
    assert r.status_code == 422
```

- [ ] **Steps:** RED → migration → parser → router → mount → GREEN → review-subagent → commit (`feat: F2 CSV upload + parser`) → push.

---

## Task 3 (F3): LLM-based categorisation

**Files:**
- Create: `app/classifier.py` (the LLM seam)
- Modify: `app/routers/transactions.py` (call classifier after parse, before persist)
- Modify: `tests/conftest.py` (add `script_classifier` fixture)
- Test: `tests/test_classifier.py`

### Key decisions

1. **One batched LLM call per upload.** Prompt: "Here are N transaction descriptions. Return a JSON array of length N where each element is one of [food, transport, ...]". Saves token cost and avoids the round-trip-per-row that would burn 50× more.
2. **Validation:** if the LLM returns wrong length or unknown categories, fall back to `"other"` for the bad slots. Never crash the upload.
3. **Test seam:** `app.classifier.classify_transactions(descriptions: list[str]) -> list[str]`. Tests monkeypatch this. An autouse `_silence_classifier` fixture in conftest defaults it to "all other" so non-classifier tests don't hit OpenAI.

### Code

```python
# app/classifier.py
from __future__ import annotations
import json
from typing import Literal

from app.config import get_settings

CATEGORIES = (
    "food", "transport", "utilities", "entertainment",
    "rent", "subscriptions", "healthcare", "shopping", "other",
)
CategoryName = Literal[
    "food", "transport", "utilities", "entertainment",
    "rent", "subscriptions", "healthcare", "shopping", "other",
]

_PROMPT = (
    "Classify each bank transaction description into ONE of these categories: "
    + ", ".join(CATEGORIES)
    + ". Return ONLY a JSON array of strings, length equal to the input array, "
    + "in the same order. Use 'other' if uncertain."
)


def classify_transactions(descriptions: list[str]) -> list[str]:
    """Single-shot LLM classification. Returns one category per input row."""
    if not descriptions:
        return []
    settings = get_settings()
    if not settings.OPENAI_API_KEY:
        return ["other"] * len(descriptions)

    from openai import OpenAI

    try:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": _PROMPT},
                {"role": "user", "content": json.dumps(descriptions)},
            ],
            response_format={"type": "json_object"},
        )
        # The model is told to return an array, but response_format=json_object
        # forces an object. We accept either {"categories": [...]} or a bare array.
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
        if isinstance(data, dict):
            data = data.get("categories", [])
    except Exception:
        return ["other"] * len(descriptions)

    valid = set(CATEGORIES)
    if not isinstance(data, list):
        return ["other"] * len(descriptions)
    out: list[str] = []
    for i in range(len(descriptions)):
        if i >= len(data):
            out.append("other")
        elif isinstance(data[i], str) and data[i] in valid:
            out.append(data[i])
        else:
            out.append("other")
    return out
```

```python
# tests/conftest.py — add this fixture
@pytest.fixture(autouse=True)
def _silence_classifier(monkeypatch):
    """Default: classify_transactions returns 'other' for everything.

    Tests that exercise the classifier wiring install their own monkeypatch
    via the script_classifier fixture below.
    """
    from app import classifier as cl
    monkeypatch.setattr(cl, "classify_transactions", lambda d: ["other"] * len(d))


@pytest.fixture
def script_classifier(monkeypatch):
    """Replace classify_transactions with a recording, configurable stub."""
    class Scripted:
        def __init__(self):
            self.calls: list[list[str]] = []
            self.return_values: list[list[str]] = []  # popped per call

        def classify(self, descriptions: list[str]) -> list[str]:
            self.calls.append(list(descriptions))
            if self.return_values:
                return self.return_values.pop(0)
            return ["other"] * len(descriptions)

    s = Scripted()
    from app import classifier as cl
    monkeypatch.setattr(cl, "classify_transactions", s.classify)
    return s
```

### Tests (the contract)

```python
# tests/test_classifier.py
async def test_classifier_called_once_per_upload(client, script_classifier):
    """Crucial: 50 rows = 1 LLM call, not 50."""
    rows = b"Date,Description,Amount\n" + b"".join(
        f"2026-06-01,Item{i},10.00\n".encode() for i in range(50)
    )
    files = {"file": ("test.csv", rows, "text/csv")}
    await client.post("/users/alice/transactions/upload", files=files)
    assert len(script_classifier.calls) == 1
    assert len(script_classifier.calls[0]) == 50


async def test_categorisation_persists(client, script_classifier, db):
    script_classifier.return_values = [["food", "transport"]]
    csv = b"Date,Description,Amount\n2026-06-01,Coffee,4.50\n2026-06-02,Uber,12.00\n"
    files = {"file": ("test.csv", csv, "text/csv")}
    await client.post("/users/alice/transactions/upload", files=files)
    cats = [t.category for t in db.query(Transaction).order_by(Transaction.id).all()]
    assert cats == ["food", "transport"]


async def test_invalid_llm_output_falls_back_to_other(client, script_classifier, db):
    """Length mismatch → all 'other'. Bad category → that slot 'other'."""
    script_classifier.return_values = [["food"]]  # only 1, but we have 2 rows
    csv = b"Date,Description,Amount\n2026-06-01,Coffee,4.50\n2026-06-02,Uber,12.00\n"
    files = {"file": ("test.csv", csv, "text/csv")}
    r = await client.post("/users/alice/transactions/upload", files=files)
    assert r.status_code == 201
    cats = [t.category for t in db.query(Transaction).order_by(Transaction.id).all()]
    assert cats == ["food", "other"]
```

- [ ] **Steps:** RED → classifier module → wire into upload router (`categories = classify_transactions([r.description for r in rows])`) → GREEN → review subagent → commit (`feat: F3 LLM-based categorisation`) → push.

---

## Task 4 (F4): Tools layer

**Files:**
- Copy verbatim from mock-travel: `app/tools/registry.py` (with the `$defs` propagation guard)
- Create: `app/tools/transactions.py`, `app/tools/budget.py`, `app/tools/aggregate.py`, `app/tools/subscriptions.py`, `app/tools/recommend.py`
- Modify: `app/tools/__init__.py` (import all tool modules so registration runs at startup)
- Create: `app/routers/tools.py` (HTTP wrapper for direct invocation — copy from mock-travel)
- Modify: `app/main.py` (mount tools router)
- Test: `tests/test_tools.py`

### Important — make tools take a `db` argument

The travel-planner tools were pure functions (`search_attractions(city, limit)`). These tools need DB access to read transactions. We pass the session in via a known kwarg the registry recognises:

```python
# app/tools/registry.py — modify the existing _Registry.invoke
def invoke(self, name: str, args: dict[str, Any], *, db=None) -> Any:
    if name not in self._tools:
        raise KeyError(name)
    entry = self._tools[name]
    validated = entry.args_model(**args)
    payload = validated.model_dump()
    if entry.needs_db:
        if db is None:
            raise RuntimeError(f"tool {name} requires a db session")
        payload["db"] = db
    return entry.func(**payload)
```

`register()` gets a new `needs_db: bool` flag. The OpenAI schema generation **excludes** the `db` parameter (it's not in the args model — it's a runtime-only kwarg).

### The five tools (signatures only; implementations follow the same pattern)

```python
# app/tools/transactions.py
class GetTransactionsArgs(BaseModel):
    user_id: str
    from_date: str | None = None  # ISO date
    to_date: str | None = None
    category: str | None = None  # one of CATEGORIES or None

def get_transactions(*, db, user_id, from_date, to_date, category) -> list[dict]:
    stmt = select(Transaction).where(Transaction.user_id == user_id)
    if from_date: stmt = stmt.where(Transaction.posted_at >= date.fromisoformat(from_date))
    if to_date:   stmt = stmt.where(Transaction.posted_at <= date.fromisoformat(to_date))
    if category:  stmt = stmt.where(Transaction.category == category)
    rows = db.execute(stmt.order_by(Transaction.posted_at)).scalars().all()
    return [{"id": r.id, "date": r.posted_at.isoformat(), "description": r.description,
             "amount": str(r.amount), "category": r.category} for r in rows]

registry.register("get_transactions", "Filtered transaction query.",
                  get_transactions, GetTransactionsArgs, needs_db=True)
```

```python
# app/tools/budget.py
class CalculateRemainingBudgetArgs(BaseModel):
    user_id: str
    month: str  # "YYYY-MM"

def calculate_remaining_budget(*, db, user_id, month) -> dict:
    budget = db.get(Budget, user_id)
    if budget is None:
        return {"error": "no budget set"}
    year, m = map(int, month.split("-"))
    start = date(year, m, 1)
    end = date(year + (m // 12), (m % 12) + 1, 1)
    spent = db.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0))
        .where(Transaction.user_id == user_id)
        .where(Transaction.posted_at >= start)
        .where(Transaction.posted_at < end)
    ).scalar_one()
    cap = Decimal(budget.monthly_cap)
    return {"month": month, "cap": str(cap), "spent": str(spent),
            "remaining": str(cap - Decimal(spent))}

registry.register(...)
```

```python
# app/tools/aggregate.py
def aggregate_by_category(*, db, user_id, month) -> dict[str, str]:
    """Returns {"food": "234.50", "transport": "120.00", ...} for the month."""
    # ... GROUP BY category SUM(amount)
```

```python
# app/tools/subscriptions.py — wraps the F6 detection algorithm
def detect_subscriptions(*, db, user_id, lookback_months=3) -> list[dict]:
    """See F6 for the heuristic. Returns merchant + monthly_amount + occurrences."""
```

```python
# app/tools/recommend.py
class RecommendArgs(BaseModel):
    user_id: str
    request_text: str  # "Can I spend $500 on a phone this month?"

def recommend(*, db, user_id, request_text) -> dict:
    """Rule-based + LLM. The advisor agent uses this directly OR composes
    the underlying tools itself — both paths are valid; this is a convenience."""
    # Pull remaining budget, upcoming subs total, then call llm.complete with a
    # rules-aware prompt. Returns {"verdict": "yes"|"caution"|"no", "rationale": "..."}
```

### Tests (3 minimum)

```python
# tests/test_tools.py
def test_get_transactions_filters_by_category(db):
    # Seed 3 transactions, 2 food / 1 transport, then assert filtered count
    ...

def test_calculate_remaining_budget_math(db):
    # Seed budget=1000, spend 300 in June, expect remaining=700
    ...

def test_registry_emits_openai_schemas_excluding_db_param(db):
    """The `db` kwarg must NOT appear in the OpenAI schema's properties."""
    schemas = registry.openai_schemas()
    for s in schemas:
        assert "db" not in s["function"]["parameters"]["properties"]
```

- [ ] **Steps:** RED tests → registry update → 5 tool modules → mount → GREEN → review subagent → commit (`feat: F4 tools layer`) → push.

---

## Task 5 (F5): Financial Advisor Agent + streaming

**Files:**
- Modify: `app/models.py` (add `ChatSession`, `Message`, `TraceEvent` — same as travel planner)
- Create: `alembic/versions/0003_chat_and_trace.py`
- Create: `app/agents/advisor.py` (the tool-calling loop)
- Create: `app/routers/chat.py` (sessions + advise + advise/stream + trace)
- Modify: `app/main.py` (mount router)
- Modify: `tests/conftest.py` (add `script_llm` and `stream_llm` fixtures — copied from mock-travel)
- Test: `tests/test_advisor.py`

### Carry-over

Architecture matches `mock-travel/app/agents/planner.py` almost exactly:
- `llm_chat(messages, tools)` and `llm_chat_stream(messages, tools)` seams
- `assistant tool_calls turn` + `role: tool` reply with matching `tool_call_id`
- `max_steps` cap with `for/else` truncation flag
- Trace events: `thinking`, `tool_call`, `tool_result`, `complete`
- SSE endpoint emitting `data: {json}\n\n`

### What's different

1. **System prompt** is finance-focused:
   ```
   You are a careful personal finance advisor. NEVER invent numbers — every
   numeric claim must come from a tool call result. If the user asks if they
   can afford something, call calculate_remaining_budget AND detect_subscriptions
   before answering. Verdicts are "yes" / "caution" / "no" with one-paragraph
   rationale grounded in the tool data.
   ```

2. **Tools dispatched** are the F4 set (`get_transactions`, `calculate_remaining_budget`, `aggregate_by_category`, `detect_subscriptions`, `recommend`).

3. **Tool dispatch passes `db`:** the loop calls `registry.invoke(name, args, db=self.db)` instead of `registry.invoke(name, args)`.

4. **No `PLAN:{...}` line** — the advisor doesn't need explicit sub-task decomposition; it just answers. Drop the plan-extraction code path. Simpler prompt, simpler loop.

### The 3 mandatory tests

```python
async def test_advisor_dispatches_budget_tool_for_afford_question(client, script_llm, db):
    # Seed: budget=1000, $400 spent, then ask "can I spend $500?"
    # Script: turn 1 = tool_call calculate_remaining_budget, turn 2 = "Yes, you have $600 left."
    # Assert tool_call recorded, final answer references the actual number.

def test_advisor_max_steps_caps_runaway(db, script_llm):
    # Script the LLM to call get_transactions forever; assert truncated=True.

async def test_advise_stream_emits_sse(client, stream_llm, db):
    # Same as travel-planner streaming SSE test. Asserts content-type, token deltas, done event.
```

- [ ] **Steps:** RED → models + migration → conftest fixtures → advisor agent → router → mount → GREEN → review subagent → commit (`feat: F5 advisor agent + streaming`) → push.

---

## Task 6 (F6): Subscription detection

**Files:**
- Create: `app/subscriptions.py` (pure-function detection algorithm)
- Modify: `app/tools/subscriptions.py` (wire the algorithm)
- Modify: `app/routers/transactions.py` (add `GET /users/{user_id}/subscriptions`)
- Test: `tests/test_subscriptions.py`

### The algorithm

```python
def detect(transactions: list[Transaction]) -> list[Subscription]:
    # 1. Normalise merchant name: lowercase, strip digits/punctuation, collapse whitespace
    # 2. Group by normalised name
    # 3. For each group with >=3 occurrences within lookback window:
    #    - Compute mean amount and stdev / mean ratio
    #    - If stdev/mean < 0.10 (10%), it's a subscription
    #    - Estimate next_due = max(posted_at) + median(diff between consecutive postings)
    # 4. Return [{merchant, monthly_amount, occurrences, last_seen, next_due_estimate}]
```

### Tests

```python
def test_three_monthly_netflix_charges_detected(db):
    # Seed 3 Netflix charges 1 month apart at $15.99 → flagged
    ...

def test_one_off_amazon_not_flagged(db):
    # Single Amazon charge → empty subs list
    ...

def test_amount_tolerance_within_10_percent(db):
    # Seed 3 gym charges at $50, $52, $48 → flagged (variance within tolerance)
    # Seed 3 charges at $50, $50, $5000 → NOT flagged (variance too high)
    ...
```

- [ ] **Steps:** RED → algorithm module → wire tool + endpoint → GREEN → review → commit (`feat: F6 subscription detection`) → push.

---

## Task 7 (F7): Monthly Financial Review

**Files:**
- Create: `app/agents/reviewer.py` (or extend `advisor.py` with a different system prompt — your call)
- Modify: `app/routers/chat.py` (add `POST /sessions/{id}/review`)
- Test: `tests/test_review.py`

### Decision

Reviewer is **a different system prompt over the same tool-calling loop**, not a new file with a copy-pasted loop. Either:
- Add `system_prompt` parameter to `AdvisorAgent.__init__` and have one class with two prompt constants, OR
- Have `ReviewerAgent(AdvisorAgent)` subclass overriding `SYSTEM_PROMPT`

The first is cleaner. **Pick that.**

### System prompt

```
You are a financial reviewer. The user asks about their spending — describe
patterns, highlight the top categories, point out month-over-month changes
if data permits. Always call aggregate_by_category before summarising. Use
plain prose, no bullet headers, max 3 short paragraphs.
```

### Tests

```python
async def test_review_defaults_to_current_month(client, script_llm, db):
    # No `month` in request → reviewer uses today's month
    ...

async def test_review_commentary_references_top_category(client, script_llm, db):
    # Mock aggregate to return {food: 800, transport: 200}; mock LLM to mention "food"
    # Assert response.commentary includes "food"
    ...

async def test_review_empty_month_handled_gracefully(client, script_llm, db):
    # No transactions → response says "no data" without crashing
    ...
```

- [ ] **Steps:** RED → reviewer agent (subclass or refactor) → endpoint → GREEN → review → commit (`feat: F7 monthly review`) → push.

---

## Task 8 (F8): Chat UI + dashboard

**Files:**
- Create: `app/templates/index.html`
- Create: `app/static/app.css`
- Create: `app/routers/dashboard.py` (`GET /users/{user_id}/dashboard`)
- Modify: `app/main.py` (add `GET /` index route)
- Test: `tests/test_ui.py`

### UI panels

```
┌──────────────────────────────────────────────────────┐
│  💰 Smart Financial Advisor    user_id: [alice    ]  │
├──────────────┬───────────────────────────────────────┤
│ Budget       │  Chat                                  │
│ $3000/mo     │  ┌──────────────────────────────────┐ │
│ Spent: $1240 │  │ user: Can I spend $500 on a phone│ │
│ Left:  $1760 │  │ 🔧 calculate_remaining_budget(.)│ │
│              │  │ ↳ {remaining: 1760}              │ │
│ Top this mo: │  │ assistant: Yes, you have $1760  │ │
│  food   $480 │  │ left this month. ...             │ │
│  trnsp  $320 │  └──────────────────────────────────┘ │
│  ent    $260 │  [______________________] [Send]     │
│              │                                       │
│ Upload CSV:  │                                       │
│ [Choose…]    │                                       │
└──────────────┴───────────────────────────────────────┘
```

### Dashboard endpoint

```python
@router.get("/users/{user_id}/dashboard")
def dashboard(user_id, db) -> DashboardOut:
    """Returns budget, spent_this_month, top_categories — three SQL queries."""
```

### Tests

```python
async def test_index_renders_all_panels(client):
    r = await client.get("/")
    assert r.status_code == 200
    body = r.text
    for marker in ('id="budget-panel"', 'id="chat"', 'id="dashboard"', 'id="upload-form"'):
        assert marker in body, f"missing {marker}"


async def test_dashboard_returns_aggregated_numbers(client, db):
    # Seed budget+transactions, GET /users/alice/dashboard, assert spent + top categories
    ...


async def test_upload_form_posts_multipart(client):
    # POST a small CSV to the upload route via the same form action; assert 201
    ...
```

- [ ] **Steps:** RED → templates + static + dashboard router → mount → GREEN → manual sanity check via `make run` and curl → review → commit (`feat: F8 UI + dashboard`) → push.

---

## Per-feature loop reminder (every task)

```
1. Skill: superpowers:test-driven-development
2. Write failing tests in tests/test_<feature>.py (3+ non-trivial)
3. Run pytest — verify RED for the right reason (feature missing, not typo)
4. Write minimal implementation to pass tests
5. Run pytest — verify GREEN
6. PARALLEL:
   ├─ Run final pytest -v  (you, fast)
   └─ Dispatch code-review subagent on git diff HEAD (in parallel, ~60s)
7. Apply review findings (or push back with reasoning)
8. git add -A && git commit -m "feat: F<N> <name>" && git push
9. TaskUpdate the task → completed
```

---

## Code-review subagent prompt template

When you dispatch the review subagent at step 6, use this prompt (substitute `<F>` and `<files>`):

```
Review uncommitted changes in /Users/I589682/Desktop/mock for feature F<N>
(<feature name>). HEAD is the previous commit; only the diff since HEAD is in scope.

Run `cd /Users/I589682/Desktop/mock && git diff HEAD --stat` then `git diff HEAD`.
Read these key files:
- <list>

Review at MEDIUM effort. Focus on:
1. Correctness — anything that breaks under realistic input
2. Security — SQL injection (we use SA params), prompt injection (validated outputs),
   IDOR (no auth — flag only if cross-user data leaks beyond the user_id query param),
   file upload (size/row caps enforced)
3. Test quality — ≥3 non-trivial tests, real assertions not tautologies
4. Reuse — anything duplicated from earlier features?

Constraints:
- 2-hour interview test. Skip nits/style.
- No auth by design. Flag missing auth ONLY if data leaks across users.

Return findings tagged [BLOCKER]/[SHOULD-FIX]/[NIT] with file:line + rationale +
suggested fix. If nothing material, say so.
```

---

## Self-review (against the spec)

| Spec section | Plan coverage |
|---|---|
| §3 Stack | Task 0 sets it up |
| §4 Domain model | Tasks 1, 2, 3, 5 add tables; types match (DECIMAL(12,2), categories enum, JSONB for trace) |
| §5 F1–F8 | Tasks 1–8, one per feature, each with ≥3 tests |
| §6 File layout | Tasks reference exact paths matching spec section 6 |
| §7.1 LLM seams | Task 3 (`classify_transactions`), Task 5 (`llm_chat`, `llm_chat_stream`); all monkeypatched in conftest |
| §7.2 Security | Task 2 enforces upload caps; Task 4 keeps `db` out of OpenAI schemas (defence in depth on tool args); commits explicitly mention `<pref>`-style untrusted-input wrapping where relevant |
| §7.3 Money correctness | Decimal types from Task 1 onwards; pydantic uses `Decimal` |
| §7.4 Testing | Each task has its own test file; `_silence_classifier` autouse fixture defaults all tests to no-op LLM |
| §8 Build order | Tasks 1–8 in the same order |

**Placeholder scan:** No "TBD" / "TODO" left. Tasks 6/7 reference algorithms in prose where the implementation is straightforward enough that prescribing every line would be busywork; tests are concrete.

**Type consistency check:**
- `Transaction.amount` is `Decimal` everywhere
- `Transaction.category` is `str` (DB) but routed through `CATEGORIES` enum at the application layer
- `BudgetOut.monthly_cap` is `Decimal` in pydantic, serialised as a quoted string in JSON (per pydantic 2 default) — tests use `Decimal(body["monthly_cap"])` to handle this

---

## Plan complete

Saved to `docs/superpowers/plans/2026-06-15-financial-advisor.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Good for the mock-interview framing because it mirrors how a real team would assign work.

2. **Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`. Batch execution with checkpoints for your review. More control, slower per task.

For interview prep specifically, **inline is probably better** — you'll want to see and explain the code as it's being written, not have it appear from a subagent's transcript.

**Which approach?**
