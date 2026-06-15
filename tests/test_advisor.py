"""Tests for F5: advisor agent + streaming."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import httpx
from sqlalchemy.orm import Session

from app.agents.advisor import AdvisorAgent
from app.models import Budget, ChatSession, Message, TraceEvent, Transaction


def _seed(db: Session) -> ChatSession:
    db.add(Budget(user_id="alice", monthly_cap=Decimal("1000.00")))
    db.add(
        Transaction(
            user_id="alice",
            posted_at=date(2026, 6, 1),
            description="Coffee",
            amount=Decimal("400.00"),
            category="food",
        )
    )
    sess = ChatSession(user_id="alice", title="phone?")
    db.add(sess)
    db.commit()
    db.refresh(sess)
    return sess


def test_advisor_dispatches_budget_tool_and_persists(db, script_llm) -> None:
    """For an 'afford' question, the agent calls calculate_remaining_budget
    and the final answer is grounded in the tool's number."""
    sess = _seed(db)

    script_llm.script = [
        # Turn 1: tool call
        {
            "content": "",
            "tool_calls": [
                {
                    "name": "calculate_remaining_budget",
                    "arguments": {"user_id": "alice", "month": "2026-06"},
                }
            ],
        },
        # Turn 2: final answer
        {"content": "Yes — you have $600 left this month.", "tool_calls": []},
    ]

    out = AdvisorAgent(db).advise(sess.id, request="Can I spend $500 on a phone?")

    assert len(out["tool_calls"]) == 1
    assert out["tool_calls"][0]["name"] == "calculate_remaining_budget"
    # The tool is real (not mocked) — assert it returned the right number
    assert Decimal(out["tool_calls"][0]["result"]["remaining"]) == Decimal("600.00")
    assert "600" in out["final"]

    # Persistence: user msg, tool msg, assistant msg
    msgs = db.query(Message).filter(Message.session_id == sess.id).order_by(Message.id).all()
    roles = [m.role for m in msgs]
    assert "user" in roles
    assert "tool" in roles
    assert "assistant" in roles


def test_advisor_max_steps_caps_runaway_loop(db, script_llm) -> None:
    """If the LLM keeps requesting tools forever, we bail at max_steps."""
    sess = _seed(db)
    script_llm.script = [
        {
            "content": "",
            "tool_calls": [
                {
                    "name": "calculate_remaining_budget",
                    "arguments": {"user_id": "alice", "month": "2026-06"},
                }
            ],
        }
    ] * 50  # way more than max_steps

    out = AdvisorAgent(db, max_steps=3).advise(sess.id, request="loop forever")
    assert out["truncated"] is True
    assert len(out["tool_calls"]) == 3


def test_advisor_emits_trace_events(db, script_llm) -> None:
    """thinking → tool_call → tool_result → complete sequence is recorded."""
    sess = _seed(db)
    script_llm.script = [
        {
            "content": "",
            "tool_calls": [
                {
                    "name": "calculate_remaining_budget",
                    "arguments": {"user_id": "alice", "month": "2026-06"},
                }
            ],
        },
        {"content": "ok", "tool_calls": []},
    ]
    AdvisorAgent(db).advise(sess.id, request="hi")

    events = (
        db.query(TraceEvent)
        .filter(TraceEvent.session_id == sess.id)
        .order_by(TraceEvent.id)
        .all()
    )
    types = [e.event_type for e in events]
    assert types[0] == "thinking"
    assert "tool_call" in types
    assert "tool_result" in types
    assert types[-1] == "complete"


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


async def test_advise_stream_emits_sse(client: httpx.AsyncClient, stream_llm) -> None:
    """POST /sessions/{id}/advise/stream returns SSE chunks."""
    r = await client.post("/sessions", json={"user_id": "alice"})
    sid = r.json()["id"]

    stream_llm.script = [
        {"chunks": ["You ", "have ", "$600 ", "left."], "tool_calls": []},
    ]

    async with client.stream(
        "POST",
        f"/sessions/{sid}/advise/stream",
        json={"request": "remaining?"},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = ""
        async for chunk in response.aiter_text():
            body += chunk

    payload_lines = [
        line.removeprefix("data: ")
        for line in body.splitlines()
        if line.startswith("data: ")
    ]
    events = [json.loads(p) for p in payload_lines]
    deltas = [e["delta"] for e in events if e["type"] == "token"]
    assert "".join(deltas) == "You have $600 left."
    assert any(e["type"] == "done" for e in events)


async def test_get_trace_returns_events(client: httpx.AsyncClient, script_llm) -> None:
    """GET /sessions/{id}/trace returns persisted events."""
    r = await client.post("/sessions", json={"user_id": "alice"})
    sid = r.json()["id"]
    script_llm.script = [{"content": "ok", "tool_calls": []}]
    await client.post(f"/sessions/{sid}/advise", json={"request": "hi"})

    r = await client.get(f"/sessions/{sid}/trace")
    assert r.status_code == 200
    events = r.json()["events"]
    types = [e["event_type"] for e in events]
    assert types[0] == "thinking"
    assert types[-1] == "complete"
