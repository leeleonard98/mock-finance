"""F5: chat sessions, advise, advise/stream, trace."""

from __future__ import annotations

import json as _json
from datetime import datetime
from typing import Any, Iterator, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import ChatSession, Message, TraceEvent

router = APIRouter(tags=["chat"])

Role = Literal["user", "assistant", "system", "tool"]


class SessionCreate(BaseModel):
    user_id: str = Field(min_length=1, max_length=255)
    title: str | None = Field(default=None, max_length=255)


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    session_id: int
    role: str
    content: str
    created_at: datetime


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: str
    title: str | None
    created_at: datetime


class SessionWithMessages(SessionOut):
    messages: list[MessageOut]


class AdviseRequest(BaseModel):
    request: str = Field(min_length=1, max_length=2000)


class ToolCallOut(BaseModel):
    name: str
    arguments: dict
    result: object


class AdviseResponse(BaseModel):
    tool_calls: list[ToolCallOut]
    final: str
    truncated: bool


class TraceEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    session_id: int
    event_type: str
    payload: dict
    created_at: datetime


class TraceOut(BaseModel):
    session_id: int
    events: list[TraceEventOut]


def _get_session_or_404(session_id: int, db: Session) -> ChatSession:
    obj = db.get(ChatSession, session_id)
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="session not found"
        )
    return obj


@router.post("/sessions", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
def create_session(payload: SessionCreate, db: Session = Depends(get_db)) -> SessionOut:
    obj = ChatSession(user_id=payload.user_id, title=payload.title)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return SessionOut.model_validate(obj)


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(user_id: str, db: Session = Depends(get_db)) -> list[SessionOut]:
    rows = (
        db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(ChatSession.id.desc())
        )
        .scalars()
        .all()
    )
    return [SessionOut.model_validate(r) for r in rows]


@router.get("/sessions/{session_id}", response_model=SessionWithMessages)
def get_session(session_id: int, db: Session = Depends(get_db)) -> SessionWithMessages:
    obj = db.execute(
        select(ChatSession)
        .where(ChatSession.id == session_id)
        .options(selectinload(ChatSession.messages))
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="session not found"
        )
    return SessionWithMessages(
        id=obj.id,
        user_id=obj.user_id,
        title=obj.title,
        created_at=obj.created_at,
        messages=[MessageOut.model_validate(m) for m in obj.messages],
    )


@router.post("/sessions/{session_id}/advise", response_model=AdviseResponse)
def advise(
    session_id: int, payload: AdviseRequest, db: Session = Depends(get_db)
) -> AdviseResponse:
    """Run the advisor agent against a session (non-streaming)."""
    from app.agents.advisor import AdvisorAgent

    _get_session_or_404(session_id, db)
    out = AdvisorAgent(db).advise(session_id, request=payload.request)
    return AdviseResponse(**out)


@router.post("/sessions/{session_id}/advise/stream")
def advise_stream(
    session_id: int, payload: AdviseRequest, db: Session = Depends(get_db)
) -> StreamingResponse:
    """SSE streaming variant: yields token / tool_call / tool_result / done events."""
    from app.agents.advisor import AdvisorAgent

    _get_session_or_404(session_id, db)

    def _sse() -> Iterator[bytes]:
        agent = AdvisorAgent(db)
        for event in agent.advise_stream(session_id, request=payload.request):
            yield f"data: {_json.dumps(event)}\n\n".encode()

    return StreamingResponse(_sse(), media_type="text/event-stream")


@router.get("/sessions/{session_id}/trace", response_model=TraceOut)
def get_trace(session_id: int, db: Session = Depends(get_db)) -> TraceOut:
    _get_session_or_404(session_id, db)
    rows = (
        db.execute(
            select(TraceEvent)
            .where(TraceEvent.session_id == session_id)
            .order_by(TraceEvent.id)
        )
        .scalars()
        .all()
    )
    return TraceOut(
        session_id=session_id,
        events=[TraceEventOut.model_validate(r) for r in rows],
    )
