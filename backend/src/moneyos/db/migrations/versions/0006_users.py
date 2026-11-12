"""Users, sign-in sessions and per-user ownership of every record.

An existing (single-user) database keeps all its data: an "owner" user with
no password is created and becomes the owner of every existing row. Set its
password with `moneyos user set-password owner@localhost`.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-12
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

OWNED = ("accounts", "import_batches", "transactions", "match_candidates", "budgets", "majra_people",
         "majra_groups", "majra_entries", "commitments", "audit_events")
OWNER_EMAIL = "owner@localhost"
# Names SQLite gives nothing to (constraints created by `unique=True`).
NAMING = {"uq": "uq_%(table_name)s_%(column_0_name)s"}


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(200)),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("revoked_at", sa.DateTime),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])

    for table in OWNED:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("user_id", sa.Integer, nullable=True))

    connection = op.get_bind()
    has_data = any(connection.execute(sa.text(f"SELECT 1 FROM {t} LIMIT 1")).first() for t in OWNED)
    if has_data:
        connection.execute(
            sa.text("INSERT INTO users (email, password_hash, created_at) VALUES (:email, NULL, :now)"),
            {"email": OWNER_EMAIL, "now": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")},
        )
        owner = connection.execute(sa.text("SELECT id FROM users WHERE email = :e"), {"e": OWNER_EMAIL}).scalar()
        for table in OWNED:
            connection.execute(sa.text(f"UPDATE {table} SET user_id = :owner"), {"owner": owner})

    for table in OWNED:
        with op.batch_alter_table(table, naming_convention=NAMING) as batch:
            batch.alter_column("user_id", existing_type=sa.Integer, nullable=False)
            batch.create_foreign_key(f"fk_{table}_user_id", "users", ["user_id"], ["id"])
            batch.create_index(f"ix_{table}_user_id", ["user_id"])
            if table == "accounts":
                batch.drop_constraint("uq_accounts_name", type_="unique")
                batch.create_unique_constraint("uq_accounts_user_name", ["user_id", "name"])
            elif table == "budgets":
                batch.drop_constraint("uq_budget_category_currency", type_="unique")
                batch.create_unique_constraint("uq_budget_user_category_currency", ["user_id", "category", "currency"])
            elif table == "majra_people":
                batch.drop_constraint("uq_majra_people_name", type_="unique")
                batch.drop_index("uq_majra_people_me")
                batch.create_unique_constraint("uq_majra_people_user_name", ["user_id", "name"])
                batch.create_index("uq_majra_people_user_me", ["user_id"], unique=True,
                                   sqlite_where=sa.text("is_me = 1"), postgresql_where=sa.text("is_me"))


def downgrade() -> None:
    for table in reversed(OWNED):
        with op.batch_alter_table(table) as batch:
            if table == "majra_people":
                batch.drop_index("uq_majra_people_user_me")
                batch.drop_constraint("uq_majra_people_user_name", type_="unique")
                batch.create_unique_constraint("uq_majra_people_name", ["name"])
                batch.create_index("uq_majra_people_me", ["is_me"], unique=True,
                                   sqlite_where=sa.text("is_me = 1"), postgresql_where=sa.text("is_me"))
            elif table == "budgets":
                batch.drop_constraint("uq_budget_user_category_currency", type_="unique")
                batch.create_unique_constraint("uq_budget_category_currency", ["category", "currency"])
            elif table == "accounts":
                batch.drop_constraint("uq_accounts_user_name", type_="unique")
                batch.create_unique_constraint("uq_accounts_name", ["name"])
            batch.drop_index(f"ix_{table}_user_id")
            batch.drop_constraint(f"fk_{table}_user_id", type_="foreignkey")
            batch.drop_column("user_id")
    op.drop_index("ix_auth_sessions_user_id", "auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("users")
