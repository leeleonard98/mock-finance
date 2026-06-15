"""chat sessions, messages, trace events

Revision ID: 0003_chat_and_trace
Revises: 0002_transactions
Create Date: 2026-06-15 00:00:02.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0003_chat_and_trace"
down_revision: Union[str, None] = "0002_transactions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_messages_session_id", "messages", ["session_id"])

    op.create_table(
        "trace_events",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_trace_events_session_id", "trace_events", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_trace_events_session_id", table_name="trace_events")
    op.drop_table("trace_events")
    op.drop_index("ix_messages_session_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_chat_sessions_user_id", table_name="chat_sessions")
    op.drop_table("chat_sessions")
