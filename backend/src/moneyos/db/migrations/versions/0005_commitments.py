"""Commitments: known future payments and income.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "commitments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("direction", sa.String(6), nullable=False),
        sa.Column("amount_minor", sa.BigInteger, nullable=False),
        sa.Column("amount_varies", sa.Boolean, nullable=False),
        sa.Column("high_minor", sa.BigInteger),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("cadence", sa.String(10), nullable=False),
        sa.Column("next_due", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("merchant_key", sa.String(200)),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.CheckConstraint("amount_minor > 0", name="ck_commitment_positive"),
        sa.CheckConstraint("direction IN ('debit', 'credit')", name="ck_commitment_direction"),
        sa.CheckConstraint("cadence IN ('once', 'weekly', 'monthly', 'quarterly', 'yearly')", name="ck_commitment_cadence"),
        sa.CheckConstraint("status IN ('active', 'paused', 'ended')", name="ck_commitment_status"),
        sa.CheckConstraint("source IN ('detected', 'manual')", name="ck_commitment_source"),
    )


def downgrade() -> None:
    op.drop_table("commitments")
