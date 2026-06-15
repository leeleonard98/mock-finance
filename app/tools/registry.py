"""Tool registry — name → (callable, pydantic args model).

Pattern carried from a previous project: tools are plain Python functions
wrapped in a pydantic args model. The registry exposes them by name,
validates args, and emits OpenAI function-calling schemas.

Two extensions over a basic registry:
1. needs_db=True flag — the tool's callable expects a `db` kwarg that the
   registry injects at invoke time. The DB session is NOT exposed in the
   OpenAI schema (it's a runtime-only kwarg).
2. $defs propagation in openai_schemas() — pydantic's nested-model schemas
   use $ref pointers; without forwarding $defs the schema has dangling refs
   and OpenAI rejects it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel


@dataclass(frozen=True)
class _ToolEntry:
    name: str
    description: str
    func: Callable[..., Any]
    args_model: type[BaseModel]
    needs_db: bool


class _Registry:
    def __init__(self) -> None:
        self._tools: dict[str, _ToolEntry] = {}

    def register(
        self,
        name: str,
        description: str,
        func: Callable[..., Any],
        args_model: type[BaseModel],
        *,
        needs_db: bool = False,
    ) -> None:
        if name in self._tools:
            raise ValueError(f"tool already registered: {name}")
        self._tools[name] = _ToolEntry(name, description, func, args_model, needs_db)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._tools

    def names(self) -> list[str]:
        return sorted(self._tools)

    def invoke(self, name: str, args: dict[str, Any], *, db: Any = None) -> Any:
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

    def openai_schemas(self) -> list[dict[str, Any]]:
        """Emit OpenAI Chat Completions tool-call schemas.

        Forwards $defs so nested-model $refs resolve. The `db` runtime
        kwarg is NOT in the args model so it's automatically excluded.
        """
        out: list[dict[str, Any]] = []
        for entry in self._tools.values():
            schema = entry.args_model.model_json_schema()
            parameters: dict[str, Any] = {
                "type": "object",
                "properties": schema.get("properties", {}),
                "required": schema.get("required", []),
            }
            if "$defs" in schema:
                parameters["$defs"] = schema["$defs"]
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": entry.name,
                        "description": entry.description,
                        "parameters": parameters,
                    },
                }
            )
        return out


registry = _Registry()
