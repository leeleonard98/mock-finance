"""F3: LLM-based expense categorisation.

One batched LLM call per upload (not per row — token cost matters). The LLM
gets all descriptions in one prompt and must return a JSON array of length N
where each element is one of CATEGORIES. Anything malformed falls back to
'other' for that slot, never crashes the upload.

Tests monkeypatch app.classifier.classify_transactions via the
script_classifier fixture; an autouse _silence_classifier fixture defaults
all other tests to "all other" so they don't hit OpenAI.
"""

from __future__ import annotations

import json
from typing import Final

from app.config import get_settings

CATEGORIES: Final = (
    "food",
    "transport",
    "utilities",
    "entertainment",
    "rent",
    "subscriptions",
    "healthcare",
    "shopping",
    "other",
)
_VALID = set(CATEGORIES)


_PROMPT = (
    "Classify each bank-transaction description into ONE of these categories: "
    + ", ".join(CATEGORIES)
    + ". Respond with ONLY a JSON object of the form "
    + '{"categories": ["food", "transport", ...]} where the list length '
    + "equals the input list length and is in the same order. Use 'other' "
    + "if uncertain. Do not invent new categories."
)


def classify_transactions(descriptions: list[str]) -> list[str]:
    """Return one category per input row. Best-effort — never raises."""
    if not descriptions:
        return []

    settings = get_settings()
    if not settings.OPENAI_API_KEY:
        return ["other"] * len(descriptions)

    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": _PROMPT},
                {"role": "user", "content": json.dumps(descriptions)},
            ],
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
    except Exception:
        return ["other"] * len(descriptions)

    if isinstance(data, dict):
        data = data.get("categories", [])
    if not isinstance(data, list):
        return ["other"] * len(descriptions)

    out: list[str] = []
    for i in range(len(descriptions)):
        if i < len(data) and isinstance(data[i], str) and data[i] in _VALID:
            out.append(data[i])
        else:
            out.append("other")
    return out


def coerce_category(value: str) -> str:
    """Defence-in-depth: any caller-supplied category string normalised to a
    known one or 'other'. Used in the upload route."""
    return value if value in _VALID else "other"
