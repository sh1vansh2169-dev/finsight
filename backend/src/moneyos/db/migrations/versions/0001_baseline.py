"""Baseline: the v0.2 schema.

Databases created by v0.2 (before migrations existed) already have exactly
these tables; ``migrate`` stamps them with this revision instead of running it.

Revision ID: 0001
Revises:
Create Date: 2026-10-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_meta",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.String(256), nullable=False),
    )
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "import_batches",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("account_override", sa.String(100)),
        sa.Column("default_currency", sa.String(3), nullable=False),
        sa.Column("day_first", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("committed_at", sa.DateTime),
        *(
            sa.Column(name, sa.Integer, nullable=False)
            for name in (
                "total_rows", "blank_rows", "rejected_rows", "new_rows",
                "suspected_rows", "duplicate_rows", "inserted_rows",
            )
        ),
        sa.CheckConstraint("status IN ('previewed', 'committed', 'discarded')", name="ck_batch_status"),
    )
    op.create_index("ix_import_batches_file_sha256", "import_batches", ["file_sha256"])
    op.create_table(
        "import_rows",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("batch_id", sa.Integer, sa.ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_row", sa.Integer, nullable=False),
        sa.Column("outcome", sa.String(10), nullable=False),
        sa.Column("reason", sa.String(255)),
        sa.Column("payload", sa.JSON),
        sa.Column("raw", sa.JSON),
        sa.CheckConstraint("outcome IN ('new', 'suspected', 'duplicate', 'rejected')", name="ck_row_outcome"),
    )
    op.create_index("ix_import_rows_batch_id", "import_rows", ["batch_id"])
    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("occurred_on", sa.Date, nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("raw_description", sa.String(500), nullable=False),
        sa.Column("amount_minor", sa.BigInteger, nullable=False),
        sa.Column("direction", sa.String(6), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("txn_type", sa.String(24), nullable=False),
        sa.Column("type_basis", sa.String(8), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("category_basis", sa.String(8), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("external_id", sa.String(100)),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("import_batch_id", sa.Integer, sa.ForeignKey("import_batches.id")),
        sa.Column("source_file", sa.String(255)),
        sa.Column("source_row", sa.Integer),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.CheckConstraint("amount_minor > 0", name="ck_amount_positive"),
        sa.CheckConstraint("direction IN ('debit', 'credit')", name="ck_direction"),
    )
    op.create_index("ix_transactions_account_date", "transactions", ["account_id", "occurred_on"])
    op.create_index(
        "uq_transactions_account_reference",
        "transactions",
        ["account_id", "external_id"],
        unique=True,
        sqlite_where=sa.text("external_id IS NOT NULL"),
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("occurred_at", sa.DateTime, nullable=False),
        sa.Column("actor", sa.String(20), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("entity_type", sa.String(30), nullable=False),
        sa.Column("entity_id", sa.Integer, nullable=False),
        sa.Column("details", sa.JSON, nullable=False),
    )


def downgrade() -> None:
    for table in ("audit_events", "transactions", "import_rows", "import_batches", "accounts", "app_meta"):
        op.drop_table(table)
