"""Single-turn OpenAI wrapper.

Importing this module never fails (no API key required at import time).
A missing key raises only when complete() is actually called.

Tests should monkeypatch app.llm.complete via the mock_llm fixture in
tests/conftest.py — never make real API calls in unit tests.
"""

from __future__ import annotations

from functools import lru_cache

from openai import OpenAI

from app.config import get_settings


class LLMNotConfiguredError(RuntimeError):
    """Raised when complete() is called without OPENAI_API_KEY set."""


@lru_cache
def _client() -> OpenAI:
    settings = get_settings()
    if not settings.OPENAI_API_KEY:
        raise LLMNotConfiguredError(
            "OPENAI_API_KEY is not set. Set it in .env or use the mock_llm fixture in tests."
        )
    return OpenAI(api_key=settings.OPENAI_API_KEY)


def complete(prompt: str, *, model: str | None = None, system: str | None = None) -> str:
    """Send a prompt to OpenAI Chat Completions and return the assistant text."""
    settings = get_settings()
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    resp = _client().chat.completions.create(
        model=model or settings.OPENAI_MODEL,
        messages=messages,
    )
    return resp.choices[0].message.content or ""
