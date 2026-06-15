"""Tool calling system.

Tools are plain Python functions wrapped in pydantic-validated arg models.
The registry exposes them by name, validates args, and emits OpenAI
function-calling schemas the agent can pick from.

Tool modules import from registry and call register() at import time.
We import all tool modules here so registration runs as soon as the package
is imported anywhere (e.g. by app.routers.tools or app.agents.advisor).
"""

from __future__ import annotations

from app.tools.registry import registry  # re-export

# Side-effect imports — each registers its tool(s).
from app.tools import aggregate as _aggregate  # noqa: F401
from app.tools import budget as _budget  # noqa: F401
from app.tools import subscriptions as _subscriptions  # noqa: F401
from app.tools import transactions as _transactions  # noqa: F401

__all__ = ["registry"]
