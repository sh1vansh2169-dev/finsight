"""Duplicate review: candidate pairs and a pointer from a duplicate to the kept record.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("transactions") as batch:
        batch.add_column(sa.Column("duplicate_of_id", sa.Integer, nullable=True))
        batch.create_foreign_key("fk_transactions_duplicate_of", "transactions", ["duplicate_of_id"], ["id"])

    op.create_table(
        "match_candidates",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("transaction_a_id", sa.Integer, sa.ForeignKey("transactions.id"), nullable=False),
        sa.Column("transaction_b_id", sa.Integer, sa.ForeignKey("transactions.id"), nullable=False),
        sa.Column("score", sa.Integer, nullable=False),
        sa.Column("reasons", sa.JSON, nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("kept_id", sa.Integer, sa.ForeignKey("transactions.id")),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("resolved_at", sa.DateTime),
        sa.CheckConstraint("transaction_a_id < transaction_b_id", name="ck_match_ordered"),
        sa.CheckConstraint("score BETWEEN 0 AND 100", name="ck_match_score"),
        sa.CheckConstraint(
            "status IN ('open', 'duplicate', 'distinct', 'superseded')", name="ck_match_status"
        ),
        sa.UniqueConstraint("transaction_a_id", "transaction_b_id", name="uq_match_pair"),
    )
    op.create_index("ix_match_candidates_status", "match_candidates", ["status"])


def downgrade() -> None:
    op.drop_index("ix_match_candidates_status", "match_candidates")
    op.drop_table("match_candidates")
    with op.batch_alter_table("transactions") as batch:
        batch.drop_constraint("fk_transactions_duplicate_of", type_="foreignkey")
        batch.drop_column("duplicate_of_id")
