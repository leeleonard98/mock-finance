"""FastAPI app factory.

Routers mount inside `create_app()` as features land. Right now only `/health`
is wired so we have something to ship from commit 0.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_db


class HealthResponse(BaseModel):
    status: str
    db: str


_BASE_DIR = Path(__file__).resolve().parent
_TEMPLATES_DIR = _BASE_DIR / "templates"
_STATIC_DIR = _BASE_DIR / "static"


def create_app() -> FastAPI:
    app = FastAPI(title="Smart Financial Advisor", version="0.1.0")

    # Templates / static — created lazily so tests don't need them on disk to import.
    if _TEMPLATES_DIR.exists():
        app.state.templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/health", response_model=HealthResponse)
    def health(db: Session = Depends(get_db)) -> HealthResponse:
        try:
            db.execute(text("SELECT 1"))
            return HealthResponse(status="ok", db="ok")
        except SQLAlchemyError:
            return HealthResponse(status="ok", db="down")

    # Per-feature routers mount here, e.g. `app.include_router(budget.router)`.

    return app


app = create_app()
