# Smart Financial Advisor — Architecture & Features Walkthrough

> A reading guide for the interview. Each section: the idea, the key file/function, and the questions an interviewer is likely to ask with the answers already prepped. Not the spec; not the demo script. Open this on your second monitor.

---

## Table of contents

1. [The 30-second pitch](#1-the-30-second-pitch)
2. [Architecture in one diagram](#2-architecture-in-one-diagram)
3. [The four key seams](#3-the-four-key-seams-where-tests-cut-the-system)
4. [The data model — six tables](#4-the-data-model--six-tables)
5. [Feature-by-feature](#5-feature-by-feature)
   - [F1 — Budget management](#f1--budget-management)
   - [F2 — CSV upload + parser](#f2--csv-upload--parser)
   - [F3 — LLM categorisation](#f3--llm-based-expense-categorisation)
   - [F4 — Tools layer](#f4--tools-layer)
   - [F5 — Advisor agent + streaming](#f5--advisor-agent--streaming)
   - [F6 — Subscription detection](#f6--subscription-detection)
   - [F7 — Monthly review](#f7--monthly-financial-review)
   - [F8 — UI + dashboard](#f8--ui--dashboard)
6. [Cross-cutting: security posture](#6-cross-cutting-security-posture)
7. [Cross-cutting: testing posture](#7-cross-cutting-testing-posture)
8. [Trade-offs we'd revisit with more time](#8-trade-offs-wed-revisit-with-more-time)
9. [Hard questions cheat-sheet](#9-hard-questions-cheat-sheet)

---

## 1. The 30-second pitch

> "FastAPI + Postgres + OpenAI. Personal finance assistant: upload a bank-statement CSV, set a monthly budget, ask natural-language questions like 'Can I spend $500 on a phone?'. Three layers — routers (validation), agents (LLM-driven loops), tools (deterministic capabilities). The LLM picks tools and writes prose; the math is pure Python over Postgres so the agent can't invent numbers. 8 features, 9 commits, 59 tests, all green."

---

## 2. Architecture in one diagram

```
                     HTTP request
                          │
                          ▼
                ┌──────────────────┐
                │  Routers         │   ← thin, validation only
                │  app/routers/    │      (budget, transactions, tools,
                │                  │       chat, dashboard)
                └────────┬─────────┘
                         │
            ┌────────────┴────────────┐
            ▼                         ▼
   ┌────────────────┐         ┌────────────────┐
   │  Agents        │         │  Plain helpers │
   │ app/agents/    │         │ csv_parser.py  │
   │  advisor.py    │         │ classifier.py  │
   │  reviewer.py   │         │ subscriptions  │
   └───────┬────────┘         └────────┬───────┘
           │                           │
           ▼                           │
   ┌────────────────┐                  │
   │  Tool registry │                  │
   │ app/tools/     │                  │
   │  registry.py   │                  │
   │  + 4 tools     │                  │
   └───────┬────────┘                  │
           │                           │
           ▼                           ▼
   ┌──────────────────────────────────────┐
   │            Postgres (5432)           │
   │  budgets, transactions, chat_*, ...  │
   └──────────────────────────────────────┘
```

**Layering rule:** routers → agents → tools → models. Helpers (csv_parser, subscriptions, classifier) sit beside agents — they're called directly by routers when no LLM is involved. **No agent imports a router; tools never import agents.**

If asked *"why does `dashboard.py` directly import from `app/tools/`?"* — because the dashboard composes the same deterministic functions the agent's tools wrap. They're pure utility functions; both the agent (via the registry) and the dashboard (directly) can call them. That's *intentional reuse*, not a layer violation.

---

## 3. The four key seams (where tests cut the system)

Every test in this app monkeypatches one of these. **If you understand these four functions, you understand testing in this codebase.**

| Seam | Type | Where | What tests do |
|---|---|---|---|
| `app.llm.complete` | sync | scaffold | `mock_llm` fixture — recording stub. Not actually used in this app's main flow but kept for any single-turn helper. |
| `app.classifier.classify_transactions` | sync | F3 | `script_classifier` fixture — scripted return values per call. Autouse `_silence_classifier` defaults all tests to "all other" so the upload tests don't hit OpenAI. |
| `app.agents.advisor.llm_chat` | sync, returns dict | F5 | `script_llm` fixture — scripts a multi-turn LLM by popping responses. |
| `app.agents.advisor.llm_chat_stream` | generator | F5 | `stream_llm` fixture — yields token chunks then a `done` event. |

**Why four seams instead of one?** Each takes/returns a different shape:
- `complete` — single string in, single string out.
- `classify_transactions` — list of strings in, list of strings out (single batched call).
- `llm_chat` — multi-turn message list + tool schemas in, `{content, tool_calls}` dict out.
- `llm_chat_stream` — same input, *generator* of chunks out.

Conflating them would either make the streaming tests messy or compromise type clarity in the agent loop.

> **Interview answer if probed:** "Each seam is a function I monkeypatch in tests so no test ever hits OpenAI. They're shaped after what the production code needs — single-turn vs multi-turn vs streaming — rather than forcing one common shape that'd be lossy in both directions."

---

## 4. The data model — six tables

Six tables. Recite this from memory if asked.

| Table | Cols (key ones) | Why |
|---|---|---|
| **`budgets`** | `user_id` PK, `monthly_cap` Decimal(12,2), `currency` | F1: one cap per user; PK = user_id means one row per user always. |
| **`transactions`** | `id`, `user_id`, `posted_at`, `description`, `amount` Decimal(12,2), `category`, `is_recurring`, `source_file` | F2: one outflow row per CSV row. `category` defaults to 'other' until F3 classifier overwrites it. `is_recurring` set by F6. |
| **`chat_sessions`** | `id`, `user_id`, `title`, `created_at` | F5: one conversation between user and advisor. |
| **`messages`** | `id`, `session_id` FK CASCADE, `role`, `content` | F5: one turn (user/assistant/tool/system). Roles validated as a pydantic Literal at the route. |
| **`trace_events`** | `id`, `session_id` FK CASCADE, `event_type`, `payload` JSONB | F5/F7: one agent decision (thinking/tool_call/tool_result/complete). JSONB so payload shape varies by event type. |
| **`alembic_version`** | one row, current revision | Alembic bookkeeping. |

**Why DECIMAL(12,2) not float?** Money. `0.1 + 0.2 == 0.3` is False in float. Decimal end-to-end (pydantic Decimal in requests, Numeric(12,2) in Postgres). 12 digits = up to 9,999,999,999.99 — plenty for a personal-finance app, capped via pydantic.

**Why JSONB on `trace_events.payload`?** Event types have different shapes:
- `thinking` payload: `{"step": int}`
- `tool_call`: `{"name": str, "arguments": {...}}`
- `tool_result`: `{"name": str, "result": Any}`
- `complete`: `{"final": str, "truncated": bool}`

Forcing a unified columnar schema would mean lots of nullable columns. JSONB keeps it flexible without giving up indexability if we needed it later (Postgres can index into JSONB).

**Cascade deletes:** `messages` and `trace_events` cascade-delete when their `chat_sessions` row goes. That's the only intentional FK cascade — everything else (budgets ↔ transactions) is intentionally NOT linked at the FK level because they're independent per-user buckets keyed by `user_id` string.

---

## 5. Feature-by-feature

Each section: idea → key file → likely interview probes.

### F1 — Budget management

**Files:** `app/models.py::Budget`, `app/routers/budget.py`, `alembic/versions/0001_budgets.py`, `tests/test_budget.py`

**Idea:** Single monthly cap per user. PUT upserts (replaces), GET returns 404 when no budget set.

**Why GET returns 404 instead of `{cap: null}`:** so clients can distinguish "user hasn't set a budget" from "user set their budget to zero". Both are valid states.

**Why PUT not POST:** PUT is idempotent — same payload twice = same end state. POST would imply creating a new resource each time, which is the wrong mental model.

**The signature line of design:** `Field(ge=0, decimal_places=2, max_digits=12)` on `monthly_cap`. That single annotation enforces:
- non-negative
- max 2 decimal places
- max 12 total digits → caps at 9,999,999,999.99
- type is `Decimal`, not `float`

→ Pydantic rejects bad input as 422 before it ever reaches SQLAlchemy.

**Likely probes:**

| Q | A |
|---|---|
| "Why no auth?" | "Deliberately deferred — the spec calls it out as a follow-up. Path-param `user_id` is the seam where `Depends(get_current_user)` plugs in." |
| "What if two PUTs race?" | "Both see None, both `add()`, second commit fails with a PK violation surfaced as 500. Acceptable for single-user dev. Production: `INSERT … ON CONFLICT (user_id) DO UPDATE`." |
| "Why is `currency` 3 chars not enum-validated?" | "Validation is shape only — length 3, ISO-4217-shaped. Validating against the actual ISO list is out of scope; the app is single-currency in practice." |

---

### F2 — CSV upload + parser

**Files:** `app/csv_parser.py` (pure function), `app/routers/transactions.py`, `app/models.py::Transaction`, `alembic/versions/0002_transactions.py`, `tests/test_csv_parser.py`, `tests/test_csv_upload.py`

**Idea:** Upload bank CSV → parse → persist outflow rows. Parser handles three CSV shapes (single Amount; Debit/Credit; Amount+Type), drops income rows, handles Excel BOM.

**The interesting bit — file-wide date format detection.**

A naïve parser tries `%Y-%m-%d`, then `%m/%d/%Y`, then `%d/%m/%Y` per row, first-match-wins. **That silently mis-dates DD/MM CSVs** because `01/02/2026` parses as Jan 2 under `%m/%d/%Y` even when the rest of the file is unambiguously DD/MM.

My parser does **two passes**:
1. Pass 1: collect all date strings; pick the format(s) that succeed for *every* row. Disambiguate MM/DD vs DD/MM by looking for any sample with `day > 12` (forces DD/MM) or `month > 12` (forces MM/DD). If still ambiguous, raise `CSVParseError`.
2. Pass 2: parse all rows with the chosen format.

Test: `test_dd_mm_format_detected_when_day_over_12`.

**Per-field DoS guard.** A 5 MB file under the byte cap could be one row with a 4.9 MB description. So the parser caps per-field length:
- `description` ≤ 1024 chars
- `amount` ≤ 32 chars (defends against `Decimal("9" * 4_900_000)`)
- `date` ≤ 32 chars

Test: `test_oversized_description_rejected`.

**Three CSV shapes:**

```
Shape 1: Date,Description,Amount             (positive=outflow, negative=income)
Shape 2: Date,Description,Debit,Credit       (debit positive, credit dropped)
Shape 3: Date,Description,Amount,Type        (Type=debit|credit; we sign-flip)
```

Header detection is heuristic-by-alias (`_DATE_KEYS`, `_DESC_KEYS`, etc.) — covers the most common bank exports.

**Likely probes:**

| Q | A |
|---|---|
| "What happens with 4.9 MB on one row?" | "Per-field cap rejects descriptions > 1KB and amount strings > 32 chars. Test `test_oversized_description_rejected` pins this." |
| "Is the parser tolerant of Excel?" | "UTF-8 BOM stripped via `decode('utf-8-sig')`; header whitespace stripped; `$` and `,` stripped from amount." |
| "Streaming reads for huge files?" | "Today the upload reads the whole file into memory before checking size — a known limitation. For prod we'd loop in 64KB chunks and abort on overflow." |
| "Why drop income rows?" | "App tracks spend, not income. A future net-worth feature would need them — that's why the parser explicitly drops vs. silently skipping; it's an intentional decision documented in the docstring." |

---

### F3 — LLM-based expense categorisation

**Files:** `app/classifier.py`, `app/routers/transactions.py` (calls into classifier), `tests/test_classifier.py`

**Idea:** After CSV parse, classify each transaction's category via the LLM. **One batched LLM call per upload, not per row.**

50 rows = 1 LLM call. Token cost matters.

**Validated against fixed enum.** Categories: `food, transport, utilities, entertainment, rent, subscriptions, healthcare, shopping, other`. The prompt forces a JSON object `{"categories": [...]}`. Anything malformed (wrong length, bogus category) collapses to `"other"`. Best-effort — never raises, never crashes the upload.

**Defence in depth.** Two layers:
1. `classify_transactions` validates LLM output against `_VALID` set before returning.
2. The upload route still calls `coerce_category(cat)` on the way to the DB, so even if a future bug or test mock returns junk, nothing bogus reaches `transactions.category`.

**The autouse fixture trap.** `_silence_classifier` in `tests/conftest.py` patches BOTH:
- `app.classifier.classify_transactions` (the function)
- `app.routers.transactions.classify_transactions` (the import-site)

Why both? The router does `from app.classifier import classify_transactions` which **binds the name locally at module load**. Patching only `app.classifier.classify_transactions` leaves the router's local binding pointing at the unpatched function. We patch both. That's *the* gotcha new contributors hit when a test starts hitting OpenAI unexpectedly.

**Likely probes:**

| Q | A |
|---|---|
| "Why one call per upload, not per row?" | "Token cost. 50 rows = 1 call ~= $0.0001 with gpt-4o-mini. 50 calls would burn ~50× more and add 50× the latency. Test `test_classifier_called_once_per_upload` pins the contract." |
| "What if the LLM returns 49 categories for 50 rows?" | "Length mismatch → unmatched slots default to 'other'. Defence-in-depth `coerce_category` catches any unknown string too. Test: `test_invalid_llm_output_falls_back_to_other`." |
| "Why `response_format=json_object`?" | "Forces the model to emit valid JSON. Without it, models often wrap output in markdown code fences (```json …```) and `json.loads` chokes." |
| "What if OpenAI is down?" | "`classify_transactions` catches `Exception`, returns all 'other'. Upload still succeeds; user sees uncategorised rows and can re-upload later." |

---

### F4 — Tools layer

**Files:** `app/tools/registry.py`, `app/tools/{transactions,budget,aggregate,subscriptions}.py`, `app/tools/__init__.py`, `app/routers/tools.py`, `tests/test_tools.py`

**Idea:** Tools are plain Python functions with pydantic args models. The registry exposes them by name, validates args, and emits OpenAI function-calling schemas.

**Four tools:**

| Tool | Purpose | needs_db |
|---|---|---|
| `get_transactions` | Filtered query (date range, category) | yes |
| `calculate_remaining_budget` | `cap - sum(amounts in month)` | yes |
| `aggregate_by_category` | per-category totals + top 3 for a month | yes |
| `detect_subscriptions` | wraps the F6 algorithm | yes |

**Two non-obvious extensions** over a basic registry:

#### a) `needs_db=True` flag

Tools that need DB access can't take `Session` as a model field — pydantic doesn't serialise it, OpenAI shouldn't see it. Solution: `register(..., needs_db=True)` tells the registry to inject `db` at invoke time. The args model defines only the LLM-visible parameters.

```python
def get_transactions(*, db, user_id, from_date, to_date, category):
    # `db` is injected by the registry; LLM never sees it
    ...
```

**Test:** `test_db_kwarg_excluded_from_openai_schemas` walks every emitted schema and asserts `"db"` is not in `properties`. Regression test for "what if someone forgets `needs_db=True` and adds `db` to the args model".

#### b) `$defs` propagation

Pydantic's `model_json_schema()` for a model with nested types (e.g. `attractions: list[Attraction]`) emits `{"$ref": "#/$defs/Attraction"}` and puts the actual definition in a top-level `$defs` block. If the registry only forwards `properties` and `required`, the `$ref` is dangling and OpenAI rejects the schema.

My registry forwards `$defs` too. **Regression test:** `test_openai_schemas_have_no_dangling_refs` walks every schema, finds every `#/$defs/X` ref, and asserts it resolves in the schema's `$defs`. Caught a real bug during travel-planner development; carried over here as standing protection.

**Likely probes:**

| Q | A |
|---|---|
| "Why a registry instead of a dict?" | "Encapsulates three concerns: callable, args validator, OpenAI schema emission. A bare dict would fragment them across the codebase. The registry makes 'add a tool = one register() call' the only ceremony." |
| "What if the LLM sends bad args?" | "Pydantic validates at `invoke()` time, raises `ValidationError`. The HTTP wrapper turns that into 422; the agent loop catches it and surfaces `{"error": "..."}` in the tool result so the LLM can recover." |
| "Why aren't tools async?" | "Pure-function tools doing SQL + Decimal math don't benefit from async. The cost of async-everywhere is a refactor of the agent loop + classifier + every tool. For a 2hr scope, sync is right; production-scale would benefit from async + asyncpg." |

---

### F5 — Advisor agent + streaming

**Files:** `app/agents/advisor.py`, `app/routers/chat.py`, `tests/test_advisor.py`

**Idea:** The headline feature. Tool-calling loop: send user request + tool schemas to LLM, dispatch any tool_calls, feed results back, loop until LLM emits a final answer.

**Two methods, one logic:**

- `advise(session_id, request)` — non-streaming, returns dict
- `advise_stream(session_id, request)` — generator yielding events for SSE

Both maintain proper OpenAI message shape:

```python
# After the LLM emits tool_calls, append the assistant turn WITH tool_calls:
messages.append({
    "role": "assistant",
    "content": content or None,
    "tool_calls": [{"id": tc["id"], "type": "function",
                    "function": {"name": tc["name"],
                                 "arguments": json.dumps(tc["arguments"])}}, ...]
})
# Then for each tool reply:
messages.append({
    "role": "tool",
    "tool_call_id": tc["id"],   # ← MUST match assistant's tool_calls[i].id
    "name": tc["name"],
    "content": json.dumps(result),
})
```

Real OpenAI **rejects** `role:tool` messages without a matching preceding `tool_calls[i].id`. The mock tests pass without it (they ignore message shape) but live runs would 400. This is the most common mistake when hand-rolling a tool-calling loop and worth pointing out.

**`max_steps` cap** — runaway-loop guard. Default 6. The test `test_advisor_max_steps_caps_runaway_loop` scripts a model that calls the same tool forever; my loop exits at `max_steps=3` and returns `truncated: True`. The mechanism is Python's `for/else`:

```python
for step_no in range(self.max_steps):
    ...
    if not tool_calls:   # final answer
        break
    # dispatch tools
else:
    truncated = True   # only runs if we never broke
```

**Trace events** persisted at every decision: `thinking` (start of turn), `tool_call`, `tool_result`, `complete`. Each is its own row, committed immediately, so a crash mid-run still leaves a queryable trail.

**SSE streaming.** `advise_stream` is a generator yielding `{type: "token"|"tool_call"|"tool_result"|"done", ...}` dicts. The route wraps it in `StreamingResponse(media_type="text/event-stream")` and serialises each event as `data: {json}\n\n`.

**`llm_chat_stream` aggregates tool_call fragments.** OpenAI streams tool_calls piecewise — name in chunk 3, arg JSON fragments in chunks 4-7. My streaming wrapper accumulates them in `pending_tool_calls[idx]` keyed by index until `finish_reason` arrives, then emits the assembled `tool_calls` list in the final chunk.

**Likely probes:**

| Q | A |
|---|---|
| "Where does planning happen?" | "Inside the LLM. My loop just dispatches whatever it asks for. Three signals shape its decisions: the system prompt (gather data first, never invent numbers), the tool descriptions (`generate_itinerary` takes attractions → implies dependency on `search`), and the growing message history." |
| "Why `tool_choice="auto"`?" | "Lets the model choose between calling a tool or answering directly. `'required'` would force a tool call every turn — wrong, because once tools have returned, the model should produce the final answer with no more calls." |
| "Why split `advise` and `advise_stream`?" | "Different return type — dict vs generator. Different response wiring at the route — `JSONResponse` vs `StreamingResponse`. Sharing one method via `if streaming: yield else: append` would be a mess. The duplication is intentional symmetry, not copy-paste." |

---

### F6 — Subscription detection

**Files:** `app/subscriptions.py`, `app/tools/subscriptions.py`, `app/routers/transactions.py` (added endpoint), `tests/test_subscriptions_endpoint.py`, plus algorithm tests in `tests/test_tools.py`

**Idea:** Detect recurring monthly payments. The detection is a pure function over a list of `Transaction` objects.

**Heuristic:**

1. Normalise merchant name: lowercase, strip digits/punctuation, collapse whitespace.
   - `"Netflix.com 12345"` → `"netflix com"`
   - `"NETFLIX.COM 99999"` → `"netflix com"`
2. Group by normalised name.
3. For groups with `≥3 occurrences` AND `stdev/mean < 10%`, flag as subscription.

**Why both occurrence count and amount stability?**
- Occurrences alone miss "I went to the same restaurant 5 times" (not a subscription).
- Amount alone misses "I paid $15.99 once at Netflix and once at Hulu" (different merchants).
- Combined: 3+ recurring same-merchant payments with stable amount = real subscription.

**Tolerance is 10%.** Tested both directions: `[50, 52, 48]` → flagged (4% spread). `[50, 50, 5000]` → not flagged.

**Side-effect on detection:** the HTTP endpoint flips `is_recurring=True` on matched transactions, so the advisor agent's tools can see "this $15.99 is locked in" next time. Idempotent — repeated calls produce the same end state.

**Why not LLM-based detection?** Three reasons:
1. Deterministic — same input always yields same output. Tests are simple.
2. Cheap — one SQL query, no API call.
3. Auditable — a user can ask "why did you flag this?" and get a numeric answer (`stdev/mean=0.04 < 0.10`). LLM can't justify itself this cleanly.

**Likely probes:**

| Q | A |
|---|---|
| "What if Netflix raises prices mid-year — three at $15.99, three at $18.99?" | "Six total occurrences, but stdev/mean ~9% — borderline. Falls within the 10% tolerance, gets flagged as one subscription with a slightly noisy mean. Acceptable for the demo; production would want to detect the price-change event itself." |
| "Why is normalisation lossy?" | "Stripping digits also strips legitimate identifiers ('Apple Music 1' vs 'Apple Music 2'). For this app, that's fine — both are still 'apple music'. For sub-account separation, we'd keep digits." |
| "Could a malicious user game this to mark a charge as recurring?" | "They'd need to upload a CSV with 3+ identical-amount entries from the same merchant. That doesn't grant any privilege — the flag just affects how the advisor reasons about the budget. Low-risk attack surface." |

---

### F7 — Monthly Financial Review

**Files:** `app/agents/reviewer.py`, `app/routers/chat.py` (added `/review` endpoint), `tests/test_review.py`

**Idea:** Same tool-calling loop as the advisor, different system prompt. The user asks "how did I spend my money this month?" — the reviewer aggregates and narrates.

**Implementation:** `ReviewerAgent` subclasses `AdvisorAgent` and overrides one class attribute:

```python
class ReviewerAgent(AdvisorAgent):
    SYSTEM_PROMPT = REVIEWER_PROMPT
    def review(self, session_id, *, month=None):
        if month is None:
            today = date.today()
            month = f"{today.year:04d}-{today.month:02d}"
        return self.advise(session_id, request=f"Review my spending for {month}...")
```

That's the entire class. The inherited `advise()` method runs the full loop; `self.SYSTEM_PROMPT` resolves to `REVIEWER_PROMPT` via Python attribute lookup (subclass first).

**Why subclass and not just two prompts in the router?**
- The `review()` method handles month framing in one place — without it, every caller would need to format the prompt the same way.
- Subclassing makes the persona override structural. You can't accidentally use the wrong prompt.
- A future `BudgetCoachAgent` is just another subclass; the loop machinery doesn't change.

**Likely probes:**

| Q | A |
|---|---|
| "Why not pass system_prompt as a constructor arg?" | "I considered it. Class-attribute override is cleaner because the prompt is a *class-level fact about this kind of agent*, not a per-instance config. Future budget-coach agent has its own prompt → its own class. A constructor arg would let you accidentally instantiate the wrong combination at runtime." |
| "What if the LLM doesn't call `aggregate_by_category` like the prompt asks?" | "Then the reviewer's response would be ungrounded — likely a refusal ('no data to summarise') or a hallucination. The system prompt instructs but doesn't enforce. Production guard: parse the response, check for at least one tool_result event in the trace; if missing, retry with a sterner prompt or bail with an error." |

---

### F8 — UI + dashboard

**Files:** `app/routers/dashboard.py`, `app/templates/index.html`, `app/static/app.css`, `tests/test_ui.py`

**Idea:** Browser surface. Sidebar shows budget + dashboard panel, main area is the chat. SSE streaming wired to `/advise/stream`.

**Dashboard endpoint composes existing tools:**

```python
@router.get("/users/{user_id}/dashboard")
def dashboard(user_id, db):
    today = date.today()
    month = f"{today.year:04d}-{today.month:02d}"
    budget = calculate_remaining_budget(db=db, user_id=user_id, month=month)
    aggr = aggregate_by_category(db=db, user_id=user_id, month=month)
    # Compose into one DTO
```

→ The dashboard is just **the same tools the agent uses**, called directly. That's intentional reuse.

**The UI's load-bearing pattern: lazy-create the assistant bubble.**

When SSE events arrive, if I create an empty assistant bubble *before* tokens start streaming, then later `tool_call` events render *after* it (later in the DOM), and the order looks wrong:

```
user: Can I afford a phone?
assistant:                       ← empty bubble created early
🔧 calculate_remaining_budget(...)
↳ result: {remaining: 678}
                                 ← tokens fill the bubble later
```

Fix: create the assistant bubble **lazily on the first token event**:

```js
let assistantBody = null;
const appendAssistant = (t) => {
  if (!assistantBody) {
    // create the bubble here, on first token
    assistantBody = document.createElement("span");
    ...
  }
  assistantBody.textContent += t;
};
```

Now the order is: user → tool_call → tool_result → assistant bubble appears with first token → fills in. Right ordering, no DOM reshuffling.

**XSS protection:** UI uses `textContent` (DOM nodes) only — never `innerHTML` interpolation. Even a malicious `description` field stored in `transactions` is rendered as plain text.

**Likely probes:**

| Q | A |
|---|---|
| "Why no React?" | "30+ minutes of scaffolding for a 2-hour test. Vanilla JS is ~150 lines, fits the demo. The interview rewards 'works end-to-end' over 'has a build step'." |
| "Why SSE not WebSockets?" | "Server-to-client only. SSE is plain HTTP, no upgrade handshake, easy to demo with `curl -N` and consume with `fetch().body.getReader()`. WebSockets would be overkill." |
| "What happens if the connection drops mid-stream?" | "Browser surfaces `body.getReader()` reading as ended. UI stops appending to the assistant bubble. The server-side trace was committed event-by-event so the user can refresh and `GET /sessions/{id}/trace` to see what was happening. Production would add an idempotent retry endpoint." |

---

## 6. Cross-cutting: security posture

Listed by category. Each row says what we do today and what we'd add for prod.

| Area | Today | Production |
|---|---|---|
| **Auth** | None — `user_id` is a free-form string | JWT or session, `Depends(current_user)` on every route, path-param `user_id` cross-checked against principal |
| **SQL injection** | All queries via SQLAlchemy ORM with parameterised binds | Same; lint for `text(f"...")` or string concatenation |
| **Prompt injection** | System prompt explicitly says "never invent numbers"; tool args validated by pydantic at registry boundary | Add untrusted-data delimiters around user-supplied content (e.g. `<user-input>...</user-input>`); add an output classifier that flags hallucinated numbers |
| **CSRF** | Not relevant — no cookie-based auth | When auth lands, double-submit cookie pattern or SameSite strict |
| **XSS** | UI uses `textContent` and DOM nodes (never `innerHTML`) | Add CSP header (`Content-Security-Policy: script-src 'self'`) |
| **CSV upload DoS** | 5 MB byte cap, 10k row cap, per-field length caps (description ≤1KB, amount ≤32 chars) | Streaming size cap before fully buffering; content-type sniffing; quarantine on parse failure |
| **CORS** | Not enabled | Explicit origin allowlist; never `*` |
| **Rate limiting** | None | Per-user limit on `/advise` and `/upload` (slowapi or Redis-backed); hard daily token budget per user to cap LLM cost |
| **Secrets** | `.env` gitignored, real key not in repo | Secret manager (1Password, Vault); rotate quarterly; never log key |
| **LLM output handling** | `coerce_category` in classifier; Decimal validation everywhere; `is_recurring` only flipped by deterministic algorithm | Output guardrails (Guardrails AI, NeMo Guardrails); tighter JSON schema enforcement |
| **PII / logs** | We log nothing user-identifiable | Same; if logging, scrub Description fields and amount values |

**The honest gaps to acknowledge:**

1. **No auth.** The biggest one. Every PUT/POST endpoint takes `user_id` as a path param with zero verification. Anyone with the URL can write to any user.
2. **CSV trust boundary.** Description text is stored raw. We don't sanitise for embedded NUL bytes or weird unicode that could break downstream consumers.
3. **No content-type check on upload.** A non-CSV file that happens to parse as CSV would still go through.

**How to talk about this in the interview:** Don't apologise. Say *"the spec deliberately defers auth as out-of-scope for the 2-hour test; the seam where it lands is `Depends(current_user)` on every route. I'd want JWT, rate limiting, and an LLM cost cap before deploying this anywhere real."*

---

## 7. Cross-cutting: testing posture

**59 tests, all green, runs in 1.5s.**

The principle: **mock the LLM, exercise everything else for real.** Postgres included — tests run against the actual `app_test` Postgres database with transactional rollback per test.

| Layer | What we test | Example |
|---|---|---|
| Pure functions | Inputs → outputs | `test_calculate_remaining_budget_math` |
| CSV parser | Three shapes, DD/MM detection, length caps | `test_dd_mm_format_detected_when_day_over_12` |
| Pydantic validation | 422 on bad input | `test_budget_negative_cap_rejected` |
| Tool registry | $defs propagation, `db` excluded from schema | `test_openai_schemas_have_no_dangling_refs` |
| Agent (mocked LLM) | Loop logic, tool dispatch, persistence | `test_advisor_dispatches_budget_tool_and_persists` |
| Agent (mocked stream) | Token streaming, tool events mid-stream | `test_advise_stream_emits_sse` |
| HTTP end-to-end | Wiring, status codes | `test_dashboard_returns_aggregated_numbers` |

**The mocking pattern is load-bearing.** Tests don't validate that the LLM is *smart* — that's OpenAI's job. They validate that the agent *plumbs the LLM correctly*: right messages, right tools, right dispatch, right persistence. That's what we control.

**Why tests use real Postgres:**
- Decimal precision differs between SQLite and Postgres
- JSONB doesn't exist in SQLite
- Date/time semantics differ
- Real Postgres = no subtle prod-vs-test divergence

The transactional rollback fixture in `tests/conftest.py::db` opens a connection, begins a transaction, binds a session to it, yields, and rolls back. Each test sees a clean DB.

**Test count per feature:**

| F | Tests |
|---|---|
| F1 | 7 |
| F2 | 14 |
| F3 | 4 |
| F4 | 15 |
| F5 | 5 |
| F6 | 3 |
| F7 | 4 |
| F8 | 3 |
| Health | 3 |
| **Total** | **58 listed (+ 1 misc) = 59** |

---

## 8. Trade-offs we'd revisit with more time

Things we explicitly punted. Mention these as *deliberate cuts*, not omissions.

### Cut for time, would add in production

1. **Auth.** Real JWT + middleware. Probably the first thing any reviewer mentions.
2. **Webhooks / push notifications.** "Alert me when food spending exceeds 80% of my food budget." Needs a background runner (Celery/RQ) + a notification channel (email, Slack, web push). Seam: a `subscriptions/alerts` table + a daily worker polling `aggregate_by_category`.
3. **Rate limiting + cost caps.** Each `/advise` call hits OpenAI. An unauthenticated, unlimited endpoint = wallet drain risk. SlowAPI middleware + a per-user `llm_calls` table tracking token spend.
4. **Streaming size cap on CSV upload.** Today we read the whole file into memory before checking byte size. Should chunk-and-abort.
5. **LLM guardrails.** Today we have prompt-level mitigation (`<pref>`-style delimiters in the travel planner; "never invent numbers" instruction here). Production: OpenAI Moderation pre-check on every input; output classifiers; framework like Guardrails AI for structural enforcement.
6. **Containerisation of the app itself.** Postgres is in Docker; the app runs on host uvicorn. Production needs a multi-stage Dockerfile, slim base, non-root user, healthcheck, second compose service.
7. **Deployment / CI.** No GitHub Actions. Production: pytest + ruff + mypy in CI, build Docker image, deploy to Fly.io / Railway / managed K8s.
8. **Observability.** No structured logging beyond per-session trace events. Production: structlog + OpenTelemetry → Honeycomb / Datadog. The agent loop is exactly the kind of code you debug via traces in prod.
9. **Cost / token accounting.** OpenAI returns `usage` on every response; we discard it. Production: a `llm_calls` table capturing tokens-in / tokens-out / model / cost, exposed to users as "AI cost: $0.07 this month".

### Cut for product fit, wouldn't add even with time

- Real bank integration (Plaid). Adds compliance scope (PCI / GLBA) we're not solving.
- Multi-currency / FX. Single-currency is a deliberate simplification.
- Tax. Different domain.
- Investment / portfolio tracking. This is a *spending* app.
- Receipt image upload / OCR. Vision-LLM nice-to-have; doesn't change the core agent story.
- Monte-Carlo budget projections. Cool but not what users ask for.

### Things we know are wrong but kept

1. **`PUT /budget` race condition.** Two concurrent PUTs for a fresh user can both see `None`, both `add()`, second `commit()` fails with PK violation → 500. Acceptable single-user; production: `INSERT … ON CONFLICT (user_id) DO UPDATE`.
2. **`source_file` not length-truncated** before insert. `String(255)` → 500 on overflow. One-liner fix; not done because no real exploit path in current scope.
3. **No bulk insert on upload.** 10k rows = 10k INSERT round-trips. Not a correctness bug, just slow at the cap. Trivial fix: `db.bulk_save_objects(...)` or `db.execute(insert(Transaction), [...])`.
4. **Reviewer doesn't enforce that aggregate_by_category was actually called.** The system prompt instructs it but there's no post-hoc check. A response could theoretically be ungrounded.

---

## 9. Hard questions cheat-sheet

Pre-baked one-liner answers for likely probes. If asked any of these, deliver the answer cleanly.

| Question | One-line answer |
|---|---|
| "Is the LLM doing the math?" | "No. The LLM picks tools and writes prose. Math is in `calculate_remaining_budget` — pure Python over Postgres. System prompt: 'never invent numbers'." |
| "Where's planning happen?" | "Inside the LLM. My loop dispatches whatever tool calls it asks for. Three signals shape decisions: system prompt, tool descriptions, message history." |
| "Why no auth?" | "Deferred. `user_id` as path-param is the seam where `Depends(current_user)` plugs in. Spec calls it out explicitly." |
| "Why DECIMAL not float?" | "Money. `0.1 + 0.2 ≠ 0.3` in float. Decimal end-to-end: pydantic Decimal in pydantic, Numeric(12,2) in Postgres." |
| "What if the LLM never returns a final answer?" | "`max_steps=6` cap. Loop exits with `truncated: True`. Test scripts an infinite-tool-call LLM and asserts `truncated`." |
| "What's `tool_call_id`?" | "Real OpenAI requires `role:tool` messages reference a `tool_calls[i].id` from a preceding assistant turn. Mocks ignore it; live calls 400 without it. My loop appends both correctly." |
| "Why JSONB on trace_events?" | "Event payloads vary by type (thinking has `step`, tool_call has `name+arguments`, complete has `final+truncated`). Unifying them as columns means lots of nulls. JSONB stays flexible without giving up indexability." |
| "How do you scale this?" | "Three first moves: async + asyncpg for I/O fan-out; cache OpenAI tool schemas per process (they don't change at runtime); partition `trace_events` by month or move to an analytics store." |
| "Why not LangChain / autogen / LlamaIndex?" | "Direct OpenAI = one fewer abstraction to debug. Every framework layer is something I have to mock to test. For 2 hours I want code I can read every line of." |
| "Biggest weakness?" | "Two: no auth, and the agent loop is sync — it blocks a worker for the full tool-calling round. Both are intentional scope cuts. Auth = 30 min I didn't have. Async = a refactor across the SQLAlchemy session, OpenAI client, and every tool." |
| "What if I asked you to add a new tool?" | "One register() call in a new module under `app/tools/`. Add the import in `app/tools/__init__.py`. Write 3 tests. Done — the registry handles schema emission, validation, and dispatch automatically." |
| "Walk me through one query end-to-end." | (See section 5, F5 — the section literally walks you through this. Practice that one.) |

---

## 10. Two-minute fallback (if you run out of time)

> "FastAPI on Postgres. Three layers: routers (validation), agents (loop), tools (registry of pydantic-validated functions). LLM is one seam, every test mocks it. Eight features, one commit each, 59 tests green. The agent picks tools and writes prose; math is pure Python so the LLM can never invent numbers. Streaming works via SSE; trace events persist every decision; tool-call IDs match between assistant and role:tool turns so it works against real OpenAI, not just mocks. Pick any feature and I'll walk the code."
