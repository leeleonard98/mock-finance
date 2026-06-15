"""SQLAlchemy declarative base.

Models are added per-feature in the tasks below. Build order is in the spec
(docs/superpowers/specs/2026-06-15-financial-advisor-design.md, section 4).
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
