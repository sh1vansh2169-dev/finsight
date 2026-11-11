"""Money Majra: people, groups, shared expenses, loans and payments.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "majra_people",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("is_me", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index(
        "uq_majra_people_me", "majra_people", ["is_me"], unique=True,
        sqlite_where=sa.text("is_me = 1"), postgresql_where=sa.text("is_me"),
    )
    op.create_table(
        "majra_groups",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.CheckConstraint("kind IN ('group', 'direct')", name="ck_majra_group_kind"),
    )
    op.create_table(
        "majra_group_members",
        sa.Column("group_id", sa.Integer, sa.ForeignKey("majra_groups.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("person_id", sa.Integer, sa.ForeignKey("majra_people.id"), primary_key=True),
    )
    op.create_table(
        "majra_entries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("group_id", sa.Integer, sa.ForeignKey("majra_groups.id"), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("description", sa.String(200), nullable=False),
        sa.Column("occurred_on", sa.Date, nullable=False),
        sa.Column("amount_minor", sa.BigInteger, nullable=False),
        sa.Column("paid_by_id", sa.Integer, sa.ForeignKey("majra_people.id"), nullable=False),
        sa.Column("paid_to_id", sa.Integer, sa.ForeignKey("majra_people.id")),
        sa.Column("split_method", sa.String(10)),
        sa.Column("transaction_id", sa.Integer, sa.ForeignKey("transactions.id")),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("voided_at", sa.DateTime),
        sa.Column("void_reason", sa.String(200)),
        sa.CheckConstraint("kind IN ('expense', 'loan', 'payment')", name="ck_majra_entry_kind"),
        sa.CheckConstraint("amount_minor > 0", name="ck_majra_entry_positive"),
    )
    op.create_index("ix_majra_entries_group_id", "majra_entries", ["group_id"])
    op.create_table(
        "majra_shares",
        sa.Column("entry_id", sa.Integer, sa.ForeignKey("majra_entries.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("person_id", sa.Integer, sa.ForeignKey("majra_people.id"), primary_key=True),
        sa.Column("share_minor", sa.BigInteger, nullable=False),
        sa.CheckConstraint("share_minor >= 0", name="ck_majra_share_non_negative"),
    )


def downgrade() -> None:
    op.drop_table("majra_shares")
    op.drop_index("ix_majra_entries_group_id", "majra_entries")
    op.drop_table("majra_entries")
    op.drop_table("majra_group_members")
    op.drop_table("majra_groups")
    op.drop_index("uq_majra_people_me", "majra_people")
    op.drop_table("majra_people")
