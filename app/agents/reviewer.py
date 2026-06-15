"""F7: Monthly Financial Review agent.

Same tool-calling loop as the advisor, different system prompt. The user
asks 'how did I spend my money this month?' — the reviewer aggregates and
narrates trends.

We subclass AdvisorAgent rather than copy-paste so the SSE/persistence/
trace machinery stays in one place.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.agents.advisor import AdvisorAgent

REVIEWER_PROMPT = (
    "You are a financial reviewer. The user asks about their spending — "
    "describe patterns, highlight the top categories, point out anything "
    "unusual. Always call aggregate_by_category before summarising; never "
    "invent numbers. Use plain prose, no bullet headers, max 3 short "
    "paragraphs. If there are no transactions, say so plainly."
)


class ReviewerAgent(AdvisorAgent):
    SYSTEM_PROMPT = REVIEWER_PROMPT

    def review(self, session_id: int, *, month: str | None = None) -> dict[str, Any]:
        """Review a month's spending. Defaults to the current month."""
        if month is None:
            today = date.today()
            month = f"{today.year:04d}-{today.month:02d}"
        # Frame the request so the LLM has a concrete month to aggregate over.
        request = (
            f"Please review my spending for {month}. Call aggregate_by_category "
            "for that month and give me a short, friendly summary."
        )
        return self.advise(session_id, request=request)
