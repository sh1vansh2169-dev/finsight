"""Database schema (SQLAlchemy 2.x declarative models).

Portable column types only, so the same schema can move to PostgreSQL.
Money is stored as a positive integer number of minor units (paise, cents)
plus an explicit direction; floats are never used.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    TypeDecorator,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """Timezone-aware datetimes, stored as UTC.

    SQLite has no timezone support, so values are normalised to UTC on the
    way in and tagged as UTC on the way out. Naive datetimes are refused.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime; use timezone-aware values")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON}


class AppMeta(Base):
    """Key/value facts about the database itself, e.g. its data mode."""

    __tablename__ = "app_meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(256))


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    kind: Mapped[str] = mapped_column(String(20), default="other")
    currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)


class ImportBatch(Base):
    """One uploaded file: previewed first, then committed or discarded."""

    __tablename__ = "import_batches"
    __table_args__ = (
        CheckConstraint("status IN ('previewed', 'committed', 'discarded')", name="ck_batch_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(12), default="previewed")
    account_override: Mapped[str | None] = mapped_column(String(100))
    default_currency: Mapped[str] = mapped_column(String(3))
    day_first: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    committed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    blank_rows: Mapped[int] = mapped_column(Integer, default=0)
    rejected_rows: Mapped[int] = mapped_column(Integer, default=0)
    new_rows: Mapped[int] = mapped_column(Integer, default=0)
    suspected_rows: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_rows: Mapped[int] = mapped_column(Integer, default=0)
    inserted_rows: Mapped[int] = mapped_column(Integer, default=0)

    rows: Mapped[list[ImportRow]] = relationship(
        back_populates="batch", cascade="all, delete-orphan", order_by="ImportRow.source_row"
    )


class ImportRow(Base):
    """A staged row from an import, with its outcome.

    Valid rows keep the normalised transaction (``payload``); rejected rows
    keep the raw cells (``raw``) so the error report can show them.
    """

    __tablename__ = "import_rows"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('new', 'suspected', 'duplicate', 'rejected')", name="ck_row_outcome"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"), index=True)
    source_row: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(10))
    reason: Mapped[str | None] = mapped_column(String(255))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    batch: Mapped[ImportBatch] = relationship(back_populates="rows")


class TransactionRecord(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="ck_amount_positive"),
        CheckConstraint("direction IN ('debit', 'credit')", name="ck_direction"),
        Index("ix_transactions_account_date", "account_id", "occurred_on"),
        # A bank reference identifies one transaction per account.
        Index(
            "uq_transactions_account_reference",
            "account_id",
            "external_id",
            unique=True,
            sqlite_where=text("external_id IS NOT NULL"),
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    occurred_on: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(String(500))
    raw_description: Mapped[str] = mapped_column(String(500), default="")
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    direction: Mapped[str] = mapped_column(String(6))
    currency: Mapped[str] = mapped_column(String(3))
    txn_type: Mapped[str] = mapped_column(String(24))
    type_basis: Mapped[str] = mapped_column(String(8))
    category: Mapped[str] = mapped_column(String(100))
    category_basis: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(10))
    external_id: Mapped[str | None] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(20))  # csv_import | manual
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"))
    source_file: Mapped[str | None] = mapped_column(String(255))
    source_row: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, onupdate=utc_now)

    account: Mapped[Account] = relationship()


class AuditEvent(Base):
    """Append-only record of imports, manual entries and corrections."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    actor: Mapped[str] = mapped_column(String(20))  # user | system
    action: Mapped[str] = mapped_column(String(50))
    entity_type: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[int] = mapped_column(Integer)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
