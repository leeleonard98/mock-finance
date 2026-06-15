"""HTTP wrapper for direct tool invocation (F4)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.db import get_db
from app.tools import registry

router = APIRouter(prefix="/tools", tags=["tools"])


class ToolInvokeRequest(BaseModel):
    args: dict[str, Any]


class ToolInvokeResponse(BaseModel):
    name: str
    result: Any


@router.get("", response_model=list[dict[str, Any]])
def list_tools() -> list[dict[str, Any]]:
    """Return the OpenAI tool-call schemas for all registered tools."""
    return registry.openai_schemas()


@router.post("/{name}/invoke", response_model=ToolInvokeResponse)
def invoke_tool(
    name: str,
    payload: ToolInvokeRequest,
    db: Session = Depends(get_db),
) -> ToolInvokeResponse:
    if name not in registry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown tool: {name}"
        )
    try:
        result = registry.invoke(name, payload.args, db=db)
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=e.errors()
        ) from e
    return ToolInvokeResponse(name=name, result=result)
