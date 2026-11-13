"""Phones paired with the FinSight phone app.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "phone_devices",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("last_seen_at", sa.DateTime),
        sa.Column("revoked_at", sa.DateTime),
    )
    op.create_index("ix_phone_devices_user_id", "phone_devices", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_phone_devices_user_id", "phone_devices")
    op.drop_table("phone_devices")
