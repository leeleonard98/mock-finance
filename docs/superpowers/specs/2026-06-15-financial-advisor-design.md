# Smart Financial Advisor Agent — Spec

**Date:** 2026-06-15
**Author:** drafted with Claude in mock-interview mode
**Status:** awaiting user review

---

## 1. Goal

Build an AI-powered personal-finance assistant that ingests a user's bank statement, categorises spending, tracks against a budget, surfaces recurring subscriptions, and answers natural-language questions like *"Can I spend $500 on a new phone this month?"* with a grounded recommendation.

The grading rubric (per the original interview brief): one feature per commit, ≥3 non-trivial tests per feature, no obvious security flaws, agentic / GenAI-first design.

## 2. Non-goals

- **Real banking integration** (Plaid, Yodlee, etc.). User uploads CSVs.
- **Auth / multi-tenant production.** `user_id` stays a free-form string with optional query-param tenancy, same convention as the travel planner.
- **Frontend SPA.** A small Jinja+vanilla-JS UI is enough — a CSV upload form, a chat box, a dashboard panel.
- **Cross-currency.** Single-currency assumed (USD by default; configurable but not converted).
- **Background jobs / scheduling.** Everything runs synchronously in the request cycle; if a CSV is huge, that's a future problem.

## 3. Stack

Same scaffold as the travel planner:
- Python 3.11, FastAPI, SQLAlchemy 2.x, Alembic
- Postgres 16 on `:5432` via Docker Compose
- OpenAI Python SDK (gpt-4o-mini default)
- pytest + httpx.AsyncClient + transactional DB fixture
- Jinja2 templates + vanilla JS

The travel planner scaffold is at `~/Desktop/mock-travel/` — I'll copy the parts that don't bake in domain assumptions (db plumbing, conftest, llm seam, makefile, tests-against-real-postgres pattern) and rebuild the agent layer fresh.

## 4. Domain model

```
users                         (logical only — user_id is a free-form string)
budgets         (user_id PK, monthly_cap DECIMAL, currency, updated_at)
transactions    (id, user_id, posted_at DATE, description TEXT, amount DECIMAL,
                 category VARCHAR, is_recurring BOOL, source_file TEXT, created_at)
chat_sessions   (id, user_id, title, created_at)              -- carry-over from travel planner
messages        (id, session_id FK, role, content, created_at) -- carry-over
trace_events    (id, session_id FK, event_type, payload JSONB, created_at) -- carry-over
```

**Categories** (fixed enum):
```
food, transport, utilities, entertainment, rent, subscriptions, healthcare, shopping, other
```
A pydantic `Literal` enforces this at the validation layer; the DB stores the string but tests assert it's one of the nine.

**Sign convention:** `amount` is the **outflow** (positive = money spent). Income rows in a CSV either flip sign or are filtered out — see Feature 2 for the choice.

## 5. Feature breakdown (8 features → ~16 grading points)

Listed in build order. Same scoring rules as the travel planner (one commit each, ≥3 non-trivial tests).

### F1 — Budget management (foundation)
The user sets a monthly cap. Tools and the agent both read it.

- `PUT /users/{user_id}/budget` — body `{monthly_cap: number}`, upsert
- `GET /users/{user_id}/budget` — current cap or 404
- 3 tests: roundtrip, negative cap rejected (422), unknown user returns 404

**Why first:** every other feature reads this. No agent, no LLM — pure CRUD. Sets the user_id convention for the rest of the app.

### F2 — CSV upload + parser
Upload a bank-statement CSV, parse, persist to `transactions`. Categorisation in F3 — for now category defaults to `"other"`.

- `POST /users/{user_id}/transactions/upload` — multipart file
- Parser tolerates the most common bank-CSV column names (`Date`/`Posted Date`, `Description`/`Memo`, `Amount`/`Debit`/`Credit`)
- Income rows (negative amount) are dropped on parse — the app tracks spending, not income
- `GET /users/{user_id}/transactions?from=&to=&category=` for filtered reads
- 3 tests: a 5-row CSV persists 5 rows with correct fields, an income row is dropped, a malformed CSV returns 422 with row-level error detail

**Why second:** every other feature needs transaction data. Still no LLM.

### F3 — LLM-based categorisation
On upload (after parsing), classify each transaction's `category` via the LLM. The classifier is a **separate seam** (`classify_transactions(rows) -> list[category]`) so tests mock it deterministically.

- Single LLM call per upload (batched), not per row — token cost matters
- The prompt is constrained: "Return a JSON array of strings, one per input row, each one of [food, transport, utilities, entertainment, rent, subscriptions, healthcare, shopping, other]"
- Response shape validated; unknown categories collapse to `other`
- 3 tests: classifier called once per upload (not per row); mock returns mixed categories and rows are persisted with them; invalid LLM output (wrong length, bad category) doesn't crash — falls back to `other`

**Why now:** sets up the LLM seam pattern that F5/F7/F8 will reuse.

### F4 — Tools layer (carry-over pattern from T3)
Same registry pattern as the travel planner. Five deterministic tools:

| Tool | Purpose |
|---|---|
| `get_transactions(user_id, from?, to?, category?)` | filtered query |
| `calculate_remaining_budget(user_id, month)` | `budget.monthly_cap - sum(amounts in month)` |
| `detect_subscriptions(user_id, lookback_months=3)` | finds repeat payments by description-cluster + amount-stable |
| `aggregate_by_category(user_id, month)` | `{category: total}` for one month |
| `recommend(user_id, request_text)` | rule-based + LLM advice (see F5) |

- Registry, OpenAI schemas, `POST /tools/{name}/invoke` route, $defs propagation guard — copied wholesale from the travel planner with one regression test extending the existing pattern
- 3 tests: budget math correctness; subscription detection finds repeat payments and ignores one-offs; aggregate sums match raw transaction sums

### F5 — Financial Advisor Agent (the headline)
The user asks: *"Can I spend $500 on a new phone this month?"*. The agent runs a tool-calling loop just like the travel planner's PlannerAgent.

- `POST /sessions/{id}/advise` body `{request: str}`
- Streaming variant `POST /sessions/{id}/advise/stream` — same SSE shape as travel planner (token / tool_call / tool_result / done)
- The system prompt baked in: "You are a careful financial advisor. Use tools to ground every claim in real data. Never invent numbers. If a recommendation is uncertain, say so."
- Trace events emitted (`thinking`, `tool_call`, `tool_result`, `complete`) — carries over from travel planner T7
- 3 tests using a scripted-LLM fixture: dispatches `get_transactions` + `calculate_remaining_budget` for an "afford this?" question; final answer references the actual numeric remaining-budget result, not invented; max_steps cap prevents runaway loops

### F6 — Subscription detection (its own deliverable, not just a tool)
Even though the *tool* lives in F4, the user-facing surface lives here:

- `GET /users/{user_id}/subscriptions` — returns the detected list with `next_due_estimate`
- Heuristic: group by normalised merchant name; if ≥3 occurrences in lookback window with amount stdev <10%, it's a subscription
- Updates `transactions.is_recurring=True` for matched rows so the advisor agent can see them
- 3 tests: 3 monthly Netflix charges → flagged; one-off Amazon → not flagged; gym membership with $1 price variation → flagged (tolerance test)

### F7 — Monthly Financial Review
*"How did I spend my money this month?"* — agent retrieves, aggregates, explains trends.

- `POST /sessions/{id}/review` body `{month?: "YYYY-MM"}` (defaults to current month)
- Tool-calling loop calls `aggregate_by_category` then writes a friendly summary
- Returns structured `{by_category: {...}, total_spent: N, top_3_categories: [...], commentary: "..."}`
- 3 tests: defaults to current month when none given; commentary references the actual top category; empty month → "no transactions" handled gracefully (no LLM call needed for that path, or LLM mock proves the path)

### F8 — Chat UI + dashboard
Browser surface that ties everything together.

- `/` index renders: budget panel, upload form, recent transactions list, chat box
- Chat box hits `/sessions/{id}/advise/stream` with SSE rendering — copied from travel planner UI
- Dashboard panel: budget, total spent this month, top 3 categories — refreshed after each chat turn
- 3 tests: index page renders all four panels (assert HTML markers), upload form posts multipart, dashboard endpoint returns aggregated numbers

## 6. Architecture / file layout

```
mock/
├── docker-compose.yml
├── Dockerfile (optional)
├── Makefile
├── pyproject.toml
├── requirements.txt
├── README.md
├── alembic/
│   └── versions/
│       ├── 0001_initial.py        (transactions, budgets, chat_sessions, messages)
│       ├── 0002_trace_events.py
│       └── ...                    (one per feature that needs schema change)
├── app/
│   ├── main.py                    (factory, mounts routers, /health, GET /)
│   ├── config.py
│   ├── db.py
│   ├── models.py
│   ├── llm.py                     (single-turn complete() seam — for classifier)
│   ├── csv_parser.py              (F2 — heuristic column matching)
│   ├── classifier.py              (F3 — batched LLM call, validation)
│   ├── subscriptions.py           (F6 — pure-function detection algorithm)
│   ├── routers/
│   │   ├── budget.py              (F1)
│   │   ├── transactions.py        (F2 — upload + filtered list)
│   │   ├── tools.py               (F4 — registry HTTP wrapper)
│   │   ├── chat.py                (F5/F7/F8 — sessions, advise, review, stream)
│   │   └── dashboard.py           (F8 — aggregated numbers for the UI panel)
│   ├── tools/
│   │   ├── registry.py            (carry-over with $defs guard)
│   │   ├── transactions.py        (get_transactions)
│   │   ├── budget.py              (calculate_remaining_budget)
│   │   ├── subscriptions.py       (detect_subscriptions)
│   │   ├── aggregate.py           (aggregate_by_category)
│   │   └── recommend.py           (recommend — uses other tools internally)
│   ├── agents/
│   │   ├── advisor.py             (F5 — tool-calling loop with llm_chat / llm_chat_stream)
│   │   └── reviewer.py            (F7 — same loop, different system prompt)
│   ├── templates/index.html       (F8)
│   └── static/app.css
└── tests/
    ├── conftest.py                (db fixture, async client, mock_llm, scripted_llm, scripted_classifier)
    ├── test_budget.py             (F1)
    ├── test_csv_upload.py         (F2)
    ├── test_classifier.py         (F3)
    ├── test_tools.py              (F4)
    ├── test_advisor.py            (F5)
    ├── test_subscriptions.py      (F6)
    ├── test_review.py             (F7)
    └── test_ui.py                 (F8)
```

**Layering rule:** routers → agents → tools → models. No agent imports a router; tools never import agents. The `app/memory.py` precedent from the travel planner (a pure-data module both agents and routers depend on) carries over here as `app/csv_parser.py`, `app/classifier.py`, `app/subscriptions.py`.

## 7. Cross-cutting concerns

### LLM seams
Three:
- `app.llm.complete(prompt) -> str` — single-turn, used by `classify_transactions`
- `app.agents.advisor.llm_chat(messages, tools) -> {content, tool_calls}` — multi-turn for advisor
- `app.agents.advisor.llm_chat_stream(messages, tools) -> Iterator[chunk]` — streaming variant

All three are monkeypatched in tests; a `_silence_llm` autouse fixture in conftest zeroes them out by default so no test accidentally hits OpenAI.

### Security baseline (carry-over from travel planner)
- `.env` gitignored; only `.env.example` committed
- Postgres credentials env-driven; non-superuser
- All DB access via SQLAlchemy parameter binding
- Pydantic models on every request and response
- Jinja templates use `textContent` only — no `innerHTML` interpolation
- Optional `?user_id=` tenancy on session reads (404 on mismatch, no existence leak)
- **CSV-specific:** parser caps file size at 5 MB, row count at 10,000 — defends against zip-bomb / DoS via large upload
- **CSV-specific:** description text is stored raw; `<` is escaped at render time only (no XSS via Description field)
- **LLM-specific:** classifier output is validated against the fixed category enum — model can't inject arbitrary category strings

### Money correctness
Amounts are `DECIMAL(12, 2)`. Pydantic models use `decimal.Decimal`, not `float`. JSON serialisation goes via a custom encoder that emits decimals as JSON numbers (no quoted strings — easier for the LLM tool path).

### Testing posture
Same as travel planner — mock the LLM, exercise everything else for real (Postgres included). The `mock_llm` and `script_llm` patterns transfer; new fixture `script_classifier` replaces `app.classifier.classify_transactions` with a deterministic stub.

## 8. Build order summary (8 commits)

| # | Feature | New tables | Tests |
|---|---|---|---|
| 1 | F1 Budget management | `budgets` | 3 |
| 2 | F2 CSV upload + parser | `transactions` | 3 |
| 3 | F3 LLM categorisation | (column update only) | 3 |
| 4 | F4 Tools layer | — | 3 |
| 5 | F5 Advisor agent + streaming | `chat_sessions`, `messages`, `trace_events` | 3 |
| 6 | F6 Subscription detection | (column update: is_recurring) | 3 |
| 7 | F7 Monthly review | — | 3 |
| 8 | F8 Chat UI + dashboard | — | 3 |

≥24 non-trivial tests total. ~12-15 minutes per feature → fits the 2-hour clock with margin for the upload UI work in F8.

## 9. Open questions / things I'd ask the user before coding

- **Do you want a "spending alerts" feature** (push-style: agent proactively flags overspend)? It's not in the brief but every fintech demo has it. Could be a 9th commit if time permits.
- **Should the recommendation agent be allowed to write back to the budget?** ("You're consistently under on entertainment — want me to lower that cap?") That's a richer "agentic" story but compounds with auth concerns. Skipping by default.
- **CSV format examples.** I'll seed the parser with two synthetic-bank formats (Chase and Wells Fargo style) for tests. If you have a real CSV format you want supported, share it after the spec is approved.

## 10. What's NOT in this spec (things to deliberately deprioritise)

These aren't omissions — they're explicit cuts. Each one has a one-line answer for the interviewer. Grouped by *why* we cut them so the framing is honest.

### Out of scope because of time
We'd add these in a real engagement; the 2-hour clock just doesn't allow.

- **Auth / OAuth / multi-tenant.** `user_id` stays a free-form string with optional tenancy on session reads — same convention as the travel planner. Production cut: real JWT, `Depends(current_user)`, the path-param `user_id` must equal the authenticated user.
- **Webhooks / push notifications.** "Alert me when I overspend on food" is a natural fit — needs a background runner (Celery/RQ) and a notification channel (email, Slack, browser push). Out of scope; the seam would be a `subscriptions/alerts` table + a worker that polls `aggregate_by_category` daily.
- **LLM guardrails.** We have *prompt-level* mitigations (delimited untrusted input for preferences, validated category enum, max_steps cap), but no real input/output classifiers. Production cut: an OpenAI Moderation pre-check on every user message, a JSON-schema-validated output guard on tool args, and a hard refusal path for prompt-injection attempts. Frameworks like Guardrails AI or NeMo Guardrails plug in here.
- **Docker for the app, not just Postgres.** Today the app runs via `uvicorn` on the host; only Postgres is containerised. Production cut: a `Dockerfile` (multi-stage, slim base, non-root user) + a second compose service, then a healthcheck-aware reverse proxy (Traefik / Caddy).
- **Deployment / CI/CD.** No GitHub Actions, no production target. Production cut: GH Actions with `pytest`, `ruff check`, `mypy`, `docker build`, then deploy to Fly.io / Railway / a managed K8s. Plus secret rotation via 1Password / Vault rather than `.env`.
- **Observability.** No structured logging, no traces beyond the per-session `trace_events` table, no metrics. Production cut: structlog + OpenTelemetry → Honeycomb / Datadog. The agent loop is exactly the kind of code that gets debugged via traces in prod.
- **Rate limiting.** `/sessions/{id}/advise` calls OpenAI per turn; an unauthenticated user could burn your wallet. Production cut: per-user rate-limit middleware (slowapi or a Redis-backed limiter), plus a hard daily token budget per user.
- **Cost / token accounting.** We don't track LLM spend per user. Production cut: capture `usage` from each OpenAI response into a `llm_calls` table; expose it to the user as "AI cost: $0.03 this month".

### Out of scope because of product fit
We *wouldn't* add these even with time — they're outside what this app is.

- Real bank integration (Plaid). Adds compliance scope (PCI / GLBA) we're not solving.
- Multi-currency / FX. Single-currency is a deliberate simplification; cross-currency adds an FX-rate dependency and complicates every calculation.
- Tax calculation. Different domain entirely.
- Investment / portfolio tracking. This is a *spending* app, not a wealth-management one.
- Receipt / image upload. Vision-LLM nice-to-have; doesn't change the core agent story.
- Monte-Carlo budget projections. Cool but the user's question is "can I afford X this month", not "what's the 90th-percentile of my December spend".
- ML-trained classifier. We use an LLM with a constrained enum. A trained classifier would be cheaper at scale but the LLM is good enough for the demo and removes the "where do I get training data" problem.

### Out of scope because they're security flaws we'd never ship
Listed for completeness — calling them out shows we know.

- The `PUT /users/{user_id}/budget` endpoint is unauthenticated. In prod this would be an auth-gated dependency, full stop.
- The CSV parser trusts user-supplied content. We cap size and row count, but a malformed Description field with embedded NUL bytes or weird unicode could break downstream. Production cut: stricter sanitisation + content-type sniffing.
- LLM-generated content is rendered with `textContent` (good) but never run through a downstream sanitiser. If the model ever generated markdown or HTML for richer rendering, we'd need a sanitiser like bleach.

If the interviewer asks about any of the above, the answer is "out of scope for the 2hr test, but here's the seam where it'd plug in: ..." — same posture as the travel planner.
