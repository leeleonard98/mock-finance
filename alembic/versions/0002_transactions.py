"""transactions

Revision ID: 0002_transactions
Revises: 0001_budgets
Create Date: 2026-06-15 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_transactions"
down_revision: Union[str, None] = "0001_budgets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("posted_at", sa.Date(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "category",
            sa.String(length=32),
            nullable=False,
            server_default="other",
        ),
        sa.Column(
            "is_recurring",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("source_file", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_transactions_user_id", "transactions", ["user_id"])
    op.create_index("ix_transactions_posted_at", "transactions", ["posted_at"])


def downgrade() -> None:
    op.drop_index("ix_transactions_posted_at", table_name="transactions")
    op.drop_index("ix_transactions_user_id", table_name="transactions")
    op.drop_table("transactions")
