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
    UniqueConstraint,
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

    Every row keeps its original cells (``raw``) for traceability and
    reprocessing; valid rows also keep the normalised transaction
    (``payload``).
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
    # Set when the user confirms this record duplicates another. The record
    # is kept for provenance but excluded from totals and listings.
    duplicate_of_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id", name="fk_transactions_duplicate_of")
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, onupdate=utc_now)

    account: Mapped[Account] = relationship()


class MatchCandidate(Base):
    """A pair of transactions that may be the same real-world payment.

    Created by the matcher, resolved only by the user. ``transaction_a_id``
    is always the smaller id so each pair is stored once.
    """

    __tablename__ = "match_candidates"
    __table_args__ = (
        CheckConstraint("transaction_a_id < transaction_b_id", name="ck_match_ordered"),
        CheckConstraint("score BETWEEN 0 AND 100", name="ck_match_score"),
        CheckConstraint("status IN ('open', 'duplicate', 'distinct', 'superseded')", name="ck_match_status"),
        UniqueConstraint("transaction_a_id", "transaction_b_id", name="uq_match_pair"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_a_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"))
    transaction_b_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"))
    score: Mapped[int] = mapped_column(Integer)  # 0-100
    reasons: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(12), default="open", index=True)
    kept_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    transaction_a: Mapped[TransactionRecord] = relationship(foreign_keys=[transaction_a_id])
    transaction_b: Mapped[TransactionRecord] = relationship(foreign_keys=[transaction_b_id])


class Budget(Base):
    """A monthly spending limit for one category in one currency."""

    __tablename__ = "budgets"
    __table_args__ = (
        CheckConstraint("limit_minor > 0", name="ck_budget_positive"),
        UniqueConstraint("category", "currency", name="uq_budget_category_currency"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(100))
    currency: Mapped[str] = mapped_column(String(3))
    limit_minor: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, onupdate=utc_now)


class MajraPerson(Base):
    """Someone you share costs with or lend to. Exactly one row is you."""

    __tablename__ = "majra_people"
    __table_args__ = (
        Index(
            "uq_majra_people_me",
            "is_me",
            unique=True,
            sqlite_where=text("is_me = 1"),
            postgresql_where=text("is_me"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    is_me: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)


class MajraGroupMember(Base):
    __tablename__ = "majra_group_members"

    group_id: Mapped[int] = mapped_column(ForeignKey("majra_groups.id", ondelete="CASCADE"), primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("majra_people.id"), primary_key=True)


class MajraGroup(Base):
    """A set of people whose shared costs are settled together.

    ``direct`` groups hold one-to-one lending between you and one person.
    """

    __tablename__ = "majra_groups"
    __table_args__ = (CheckConstraint("kind IN ('group', 'direct')", name="ck_majra_group_kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(10), default="group")
    currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    members: Mapped[list[MajraPerson]] = relationship(secondary="majra_group_members", order_by="MajraPerson.id")


class MajraEntry(Base):
    """A shared expense, a loan or a payment. Corrected by voiding, never deleted."""

    __tablename__ = "majra_entries"
    __table_args__ = (
        CheckConstraint("kind IN ('expense', 'loan', 'payment')", name="ck_majra_entry_kind"),
        CheckConstraint("amount_minor > 0", name="ck_majra_entry_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("majra_groups.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    description: Mapped[str] = mapped_column(String(200))
    occurred_on: Mapped[date] = mapped_column(Date)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    paid_by_id: Mapped[int] = mapped_column(ForeignKey("majra_people.id"))
    paid_to_id: Mapped[int | None] = mapped_column(ForeignKey("majra_people.id"))
    split_method: Mapped[str | None] = mapped_column(String(10))
    # The ledger transaction this entry corresponds to, if any (e.g. the UPI
    # payment that was the loan). One transaction backs at most one entry.
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    voided_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    void_reason: Mapped[str | None] = mapped_column(String(200))

    shares: Mapped[list[MajraShare]] = relationship(cascade="all, delete-orphan", order_by="MajraShare.person_id")
    paid_by: Mapped[MajraPerson] = relationship(foreign_keys=[paid_by_id])
    paid_to: Mapped[MajraPerson | None] = relationship(foreign_keys=[paid_to_id])


class MajraShare(Base):
    """One participant's share of a shared expense."""

    __tablename__ = "majra_shares"
    __table_args__ = (CheckConstraint("share_minor >= 0", name="ck_majra_share_non_negative"),)

    entry_id: Mapped[int] = mapped_column(ForeignKey("majra_entries.id", ondelete="CASCADE"), primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("majra_people.id"), primary_key=True)
    share_minor: Mapped[int] = mapped_column(BigInteger)


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
