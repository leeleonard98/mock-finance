"""F5: Financial Advisor Agent — tool-calling loop with streaming.

Two seams:
- llm_chat(messages, tools) → {"content", "tool_calls"}: single-turn,
  used by AdvisorAgent.advise()
- llm_chat_stream(messages, tools) → iterator of {"delta", "done", "tool_calls"}:
  streaming, used by AdvisorAgent.advise_stream()

Tests monkeypatch these seams via script_llm / stream_llm fixtures.
The agent itself is plain Python — no SDK coupling at the loop level.

Trace events emitted: thinking, tool_call, tool_result, complete.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ChatSession, Message, TraceEvent
from app.tools import registry

SYSTEM_PROMPT = (
    "You are a careful personal finance advisor. NEVER invent numbers — every "
    "numeric claim must come from a tool call result. If the user asks if "
    "they can afford something, call calculate_remaining_budget AND "
    "detect_subscriptions before answering. Verdicts are 'yes', 'caution', or "
    "'no' with one short paragraph rationale, grounded in the tool data. "
    "Be conversational, not a corporate report."
)


@dataclass
class _Step:
    name: str
    arguments: dict[str, Any]
    result: Any


# ---------------------------------------------------------------------------
# LLM seams (real implementations — tests monkeypatch these)
# ---------------------------------------------------------------------------


def llm_chat(*, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
    """Non-streaming chat completion. Returns normalised {content, tool_calls}."""
    from openai import OpenAI

    settings = get_settings()
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set.")
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=messages,
        tools=tools,
        tool_choice="auto",
    )
    msg = resp.choices[0].message
    tool_calls: list[dict[str, Any]] = []
    for tc in msg.tool_calls or []:
        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        tool_calls.append({"id": tc.id, "name": tc.function.name, "arguments": args})
    return {"content": msg.content or "", "tool_calls": tool_calls}


def llm_chat_stream(
    *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
):
    """Streaming chat completion. Yields {delta, done, tool_calls} chunks.

    Aggregates streamed tool_call fragments across deltas (OpenAI streams
    them piecewise — name in chunk 3, arg fragments in chunks 4-7).
    """
    from openai import OpenAI

    settings = get_settings()
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set.")
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    stream = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=messages,
        tools=tools,
        tool_choice="auto",
        stream=True,
    )
    pending: dict[int, dict[str, Any]] = {}
    for chunk in stream:
        choice = chunk.choices[0]
        delta = choice.delta
        if delta.content:
            yield {"delta": delta.content, "done": False}
        for tc_delta in delta.tool_calls or []:
            idx = tc_delta.index
            slot = pending.setdefault(
                idx, {"id": tc_delta.id or f"call_{idx}", "name": "", "arguments": ""}
            )
            if tc_delta.id:
                slot["id"] = tc_delta.id
            if tc_delta.function and tc_delta.function.name:
                slot["name"] += tc_delta.function.name
            if tc_delta.function and tc_delta.function.arguments:
                slot["arguments"] += tc_delta.function.arguments
        if choice.finish_reason is not None:
            tool_calls: list[dict[str, Any]] = []
            for slot in pending.values():
                try:
                    args = json.loads(slot["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append({"id": slot["id"], "name": slot["name"], "arguments": args})
            yield {"delta": "", "done": True, "tool_calls": tool_calls}
            return


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class AdvisorAgent:
    """Tool-calling loop. system_prompt is overridable so the F7 reviewer can
    subclass without copy-pasting the loop."""

    SYSTEM_PROMPT = SYSTEM_PROMPT

    def __init__(self, db: Session, *, max_steps: int = 6) -> None:
        self.db = db
        self.max_steps = max_steps

    # ------- non-streaming -------

    def advise(self, session_id: int, request: str) -> dict[str, Any]:
        sess = self.db.get(ChatSession, session_id)
        if sess is None:
            raise ValueError(f"session {session_id} not found")

        self._persist(session_id, "user", request)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": request},
        ]
        tools = registry.openai_schemas()
        steps: list[_Step] = []
        truncated = False
        final_content = ""

        for step_no in range(self.max_steps):
            self._trace(session_id, "thinking", {"step": step_no})
            response = llm_chat(messages=messages, tools=tools)
            content = response.get("content") or ""
            tool_calls = response.get("tool_calls") or []

            if content:
                self._persist(session_id, "assistant", content)
            if tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": content or None,
                        "tool_calls": [
                            {
                                "id": tc.get("id") or f"call_{step_no}_{i}",
                                "type": "function",
                                "function": {
                                    "name": tc["name"],
                                    "arguments": json.dumps(tc.get("arguments") or {}),
                                },
                            }
                            for i, tc in enumerate(tool_calls)
                        ],
                    }
                )
            elif content:
                messages.append({"role": "assistant", "content": content})

            if not tool_calls:
                final_content = content
                break

            for i, tc in enumerate(tool_calls):
                name = tc["name"]
                args = tc.get("arguments") or {}
                self._trace(session_id, "tool_call", {"name": name, "arguments": args})
                try:
                    result = registry.invoke(name, args, db=self.db)
                except Exception as e:
                    result = {"error": f"{type(e).__name__}: {e}"}
                self._trace(session_id, "tool_result", {"name": name, "result": result})
                steps.append(_Step(name=name, arguments=args, result=result))
                payload = json.dumps(result, default=str)
                self._persist(
                    session_id,
                    "tool",
                    f"[{name}] args={json.dumps(args)} result={payload}",
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id") or f"call_{step_no}_{i}",
                        "name": name,
                        "content": payload,
                    }
                )
        else:
            truncated = True

        self._trace(
            session_id,
            "complete",
            {"final": final_content, "truncated": truncated},
        )

        return {
            "tool_calls": [
                {"name": s.name, "arguments": s.arguments, "result": s.result} for s in steps
            ],
            "final": final_content,
            "truncated": truncated,
        }

    # ------- streaming -------

    def advise_stream(self, session_id: int, request: str):
        """Generator yielding event dicts for the SSE wrapper."""
        sess = self.db.get(ChatSession, session_id)
        if sess is None:
            raise ValueError(f"session {session_id} not found")

        self._persist(session_id, "user", request)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": request},
        ]
        tools = registry.openai_schemas()
        truncated = False
        full_final = ""

        for step_no in range(self.max_steps):
            self._trace(session_id, "thinking", {"step": step_no})
            buf: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            for chunk in llm_chat_stream(messages=messages, tools=tools):
                delta = chunk.get("delta") or ""
                if delta:
                    buf.append(delta)
                    yield {"type": "token", "delta": delta}
                if chunk.get("done"):
                    tool_calls = chunk.get("tool_calls", [])

            content = "".join(buf)
            if content:
                self._persist(session_id, "assistant", content)

            if tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": content or None,
                        "tool_calls": [
                            {
                                "id": tc.get("id") or f"call_{step_no}_{i}",
                                "type": "function",
                                "function": {
                                    "name": tc["name"],
                                    "arguments": json.dumps(tc.get("arguments") or {}),
                                },
                            }
                            for i, tc in enumerate(tool_calls)
                        ],
                    }
                )
            elif content:
                messages.append({"role": "assistant", "content": content})

            if not tool_calls:
                full_final = content
                break

            for i, tc in enumerate(tool_calls):
                name = tc["name"]
                args = tc.get("arguments") or {}
                yield {"type": "tool_call", "name": name, "arguments": args}
                self._trace(session_id, "tool_call", {"name": name, "arguments": args})
                try:
                    result = registry.invoke(name, args, db=self.db)
                except Exception as e:
                    result = {"error": f"{type(e).__name__}: {e}"}
                self._trace(session_id, "tool_result", {"name": name, "result": result})
                payload = json.dumps(result, default=str)
                self._persist(
                    session_id,
                    "tool",
                    f"[{name}] args={json.dumps(args)} result={payload}",
                )
                yield {"type": "tool_result", "name": name, "result": result}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id") or f"call_{step_no}_{i}",
                        "name": name,
                        "content": payload,
                    }
                )
        else:
            truncated = True

        self._trace(
            session_id, "complete", {"final": full_final, "truncated": truncated}
        )
        yield {"type": "done", "final": full_final, "truncated": truncated}

    # ------- helpers -------

    def _persist(self, session_id: int, role: str, content: str) -> None:
        self.db.add(Message(session_id=session_id, role=role, content=content))
        self.db.commit()

    def _trace(self, session_id: int, event_type: str, payload: dict[str, Any]) -> None:
        self.db.add(
            TraceEvent(session_id=session_id, event_type=event_type, payload=payload)
        )
        self.db.commit()
