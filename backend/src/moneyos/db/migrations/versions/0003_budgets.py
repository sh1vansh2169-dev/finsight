"""Monthly category budgets.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "budgets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("limit_minor", sa.BigInteger, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.CheckConstraint("limit_minor > 0", name="ck_budget_positive"),
        sa.UniqueConstraint("category", "currency", name="uq_budget_category_currency"),
    )


def downgrade() -> None:
    op.drop_table("budgets")
