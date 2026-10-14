"""Conversion between domain Transactions, staged JSON payloads and DB rows."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from moneyos.db.tables import Account, TransactionRecord
from moneyos.domain.models import Basis, Direction, Status, Transaction, TxnType
from moneyos.domain.money import from_minor, to_minor


def to_payload(t: Transaction) -> dict[str, Any]:
    return {
        "date": t.date.isoformat(),
        "description": t.description,
        "amount": str(t.amount),
        "currency": t.currency,
        "account": t.account,
        "category": t.category,
        "category_basis": t.category_basis.value,
        "txn_type": t.txn_type.value,
        "type_basis": t.type_basis.value,
        "status": t.status.value,
        "reference": t.reference,
        "raw_description": t.raw_description,
        "source_file": t.source_file,
        "source_row": t.source_row,
    }


def from_payload(p: dict[str, Any]) -> Transaction:
    return Transaction(
        date=date.fromisoformat(p["date"]),
        description=p["description"],
        amount=Decimal(p["amount"]),
        currency=p["currency"],
        account=p["account"],
        category=p["category"],
        category_basis=Basis(p["category_basis"]),
        txn_type=TxnType(p["txn_type"]),
        type_basis=Basis(p["type_basis"]),
        status=Status(p["status"]),
        reference=p["reference"],
        raw_description=p["raw_description"],
        source_file=p["source_file"],
        source_row=p["source_row"],
    )


def signed_amount(record: TransactionRecord) -> Decimal:
    amount = from_minor(record.amount_minor, record.currency)
    return amount if record.direction == Direction.CREDIT else -amount


def to_domain(record: TransactionRecord) -> Transaction:
    return Transaction(
        date=record.occurred_on,
        description=record.description,
        amount=signed_amount(record),
        currency=record.currency,
        account=record.account.name,
        category=record.category,
        category_basis=Basis(record.category_basis),
        txn_type=TxnType(record.txn_type),
        type_basis=Basis(record.type_basis),
        status=Status(record.status),
        reference=record.external_id,
        raw_description=record.raw_description,
        source_file=record.source_file or "",
        source_row=record.source_row or 0,
    )


def get_or_create_account(session: Session, name: str, currency: str, kind: str = "other") -> Account:
    account = session.scalar(select(Account).where(Account.name == name))
    if account is None:
        account = Account(name=name, currency=currency, kind=kind)
        session.add(account)
        session.flush()
    return account


def to_record(
    t: Transaction,
    account: Account,
    *,
    source: str,
    import_batch_id: int | None = None,
) -> TransactionRecord:
    return TransactionRecord(
        account=account,
        occurred_on=t.date,
        description=t.description,
        raw_description=t.raw_description,
        amount_minor=to_minor(abs(t.amount), t.currency),
        direction=t.direction.value,
        currency=t.currency,
        txn_type=t.txn_type.value,
        type_basis=t.type_basis.value,
        category=t.category,
        category_basis=t.category_basis.value,
        status=t.status.value,
        external_id=t.reference,
        source=source,
        import_batch_id=import_batch_id,
        source_file=t.source_file or None,
        source_row=t.source_row or None,
    )
