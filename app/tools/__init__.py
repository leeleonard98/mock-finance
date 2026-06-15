"""Tool calling system.

Tools are plain Python functions wrapped in pydantic-validated arg models.
The registry exposes them by name, validates args, and emits OpenAI
function-calling schemas the agent can pick from.

Per-tool modules import from registry and call register() at import time.
This package's __init__ does NOT eagerly import the tool modules — that
happens in the tools router's startup or wherever the registry is first
needed. (Avoids circular imports during tests.)
"""
