"""Ledger reads, manual entry, user corrections and summaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload

from moneyos.db.tables import Account, AuditEvent, TransactionRecord
from moneyos.domain.classify import Rules, classify
from moneyos.domain.dedupe import fingerprint
from moneyos.domain.models import (
    ALLOWED_DIRECTIONS,
    UNCATEGORIZED,
    Basis,
    Direction,
    Status,
    Transaction,
    TxnType,
)
from moneyos.domain.money import to_minor
from moneyos.domain.summary import LedgerSummary, summarize_by_currency
from moneyos.services.errors import InvalidRequestError, NotFoundError
from moneyos.services.mapping import get_or_create_account, to_domain, to_record


@dataclass(frozen=True, slots=True)
class TransactionFilter:
    start: date | None = None
    end: date | None = None
    account: str | None = None
    currency: str | None = None
    txn_type: TxnType | None = None
    category: str | None = None


def _filtered(query: Select, f: TransactionFilter) -> Select:
    if f.start:
        query = query.where(TransactionRecord.occurred_on >= f.start)
    if f.end:
        query = query.where(TransactionRecord.occurred_on <= f.end)
    if f.account:
        query = query.where(Account.name == f.account)
    if f.currency:
        query = query.where(TransactionRecord.currency == f.currency.upper())
    if f.txn_type:
        query = query.where(TransactionRecord.txn_type == f.txn_type.value)
    if f.category:
        query = query.where(TransactionRecord.category == f.category)
    return query


def list_transactions(
    session: Session, f: TransactionFilter, *, limit: int = 100, offset: int = 0
) -> tuple[list[TransactionRecord], int]:
    """Newest first. Returns (page, total matching)."""
    base = select(TransactionRecord).join(Account)
    total = session.scalar(_filtered(select(func.count()).select_from(TransactionRecord).join(Account), f))
    page = session.scalars(
        _filtered(base, f)
        .options(selectinload(TransactionRecord.account))
        .order_by(TransactionRecord.occurred_on.desc(), TransactionRecord.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(page), total or 0


def get_transaction(session: Session, transaction_id: int) -> TransactionRecord:
    record = session.get(TransactionRecord, transaction_id)
    if record is None:
        raise NotFoundError(f"transaction {transaction_id} not found")
    return record


def _check_type(txn_type: TxnType, direction: Direction) -> None:
    if direction not in ALLOWED_DIRECTIONS[txn_type]:
        raise InvalidRequestError(f"a {direction.value} cannot be of type {txn_type.value}")


def create_manual(
    session: Session,
    *,
    occurred_on: date,
    description: str,
    amount: Decimal,
    direction: Direction,
    currency: str,
    account: str,
    rules: Rules,
    txn_type: TxnType | None = None,
    category: str | None = None,
) -> tuple[TransactionRecord, list[str]]:
    """Record a transaction the user entered by hand, e.g. a cash payment.

    Returns the record and any warnings. A possible duplicate is reported
    but still saved: the user typed it in deliberately.
    """
    if amount <= 0:
        raise InvalidRequestError("amount must be positive; use direction for money in or out")
    currency = currency.upper()
    try:
        to_minor(amount, currency)
    except ValueError as error:
        raise InvalidRequestError(str(error)) from None
    if txn_type is not None:
        _check_type(txn_type, direction)

    t = Transaction(
        date=occurred_on,
        description=description,
        amount=amount if direction == Direction.CREDIT else -amount,
        currency=currency,
        account=account,
        category=category or UNCATEGORIZED,
        category_basis=Basis.USER if category else Basis.NONE,
        txn_type=txn_type or TxnType.UNKNOWN,
        type_basis=Basis.USER if txn_type else Basis.NONE,
        status=Status.POSTED,
        raw_description=description,
    )
    t = classify(t, rules)

    warnings = []
    key = fingerprint(t)
    same_account = session.scalars(
        select(TransactionRecord)
        .join(Account)
        .where(Account.name == account, TransactionRecord.occurred_on == occurred_on)
        .options(selectinload(TransactionRecord.account))
    )
    if any(fingerprint(to_domain(r)) == key for r in same_account):
        warnings.append("A transaction with the same account, date, amount and description already exists.")

    record = to_record(t, get_or_create_account(session, account, currency), source="manual")
    session.add(record)
    session.flush()
    session.add(
        AuditEvent(actor="user", action="transaction_created", entity_type="transaction", entity_id=record.id)
    )
    session.commit()
    return record, warnings


def correct_transaction(
    session: Session,
    transaction_id: int,
    *,
    txn_type: TxnType | None = None,
    category: str | None = None,
) -> TransactionRecord:
    """Apply a user correction. The previous values go into the audit log."""
    if txn_type is None and category is None:
        raise InvalidRequestError("nothing to change")
    record = get_transaction(session, transaction_id)
    before = {
        "txn_type": record.txn_type,
        "type_basis": record.type_basis,
        "category": record.category,
        "category_basis": record.category_basis,
    }
    if txn_type is not None:
        _check_type(txn_type, Direction(record.direction))
        record.txn_type, record.type_basis = txn_type.value, Basis.USER.value
    if category is not None:
        record.category, record.category_basis = category, Basis.USER.value
    after = {k: getattr(record, k) for k in before}
    session.add(
        AuditEvent(
            actor="user",
            action="transaction_corrected",
            entity_type="transaction",
            entity_id=record.id,
            details={"before": before, "after": after},
        )
    )
    session.commit()
    return record


def audit_trail(session: Session, entity_type: str, entity_id: int) -> list[AuditEvent]:
    return list(
        session.scalars(
            select(AuditEvent)
            .where(AuditEvent.entity_type == entity_type, AuditEvent.entity_id == entity_id)
            .order_by(AuditEvent.id)
        )
    )


def summarize_ledger(session: Session, f: TransactionFilter) -> dict[str, LedgerSummary]:
    records = session.scalars(
        _filtered(select(TransactionRecord).join(Account), f).options(
            selectinload(TransactionRecord.account)
        )
    )
    return summarize_by_currency(to_domain(r) for r in records)


def list_accounts(session: Session) -> list[Account]:
    return list(session.scalars(select(Account).order_by(Account.name)))

