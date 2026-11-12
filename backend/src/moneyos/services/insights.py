"""Unusual-spending flags over the stored ledger.

Uses the personal robust z-score (see ML_EXPERIMENTS.md, E3): each payment
is compared only with *your own earlier* payments in the same category. A
flag means "unusual for you", never "fraud". Dismissing a flag is recorded
in the audit log and the payment is not flagged again.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from moneyos.db.tables import AuditEvent, TransactionRecord
from moneyos.domain.models import Status, TxnType
from moneyos.domain.money import from_minor
from moneyos.ml.anomaly import MIN_HISTORY, personal_scores
from moneyos.services import ledger

METHOD = "robust_z_score"
NOTE = (
    "Unusual compared with your own earlier payments in the same category. This is not a fraud check, "
    f"and categories with fewer than {MIN_HISTORY} earlier payments are not judged."
)


@dataclass
class UnusualPayment:
    record: TransactionRecord
    score: float
    reason: str


def _dismissed(session: Session) -> set[int]:
    return set(session.scalars(
        select(AuditEvent.entity_id).where(AuditEvent.action == "unusual_dismissed", AuditEvent.entity_type == "transaction")
    ))


def unusual(session: Session, currency: str, start: date | None = None, end: date | None = None) -> list[UnusualPayment]:
    records = list(session.scalars(
        select(TransactionRecord)
        .where(TransactionRecord.currency == currency, TransactionRecord.txn_type == TxnType.EXPENSE.value,
               TransactionRecord.status != Status.FAILED.value, TransactionRecord.duplicate_of_id.is_(None))
        .options(selectinload(TransactionRecord.account))
        .order_by(TransactionRecord.occurred_on, TransactionRecord.id)
    ))
    if not records:
        return []
    stream = pd.DataFrame({
        "day": [(r.occurred_on - records[0].occurred_on).days for r in records],
        "category": [r.category for r in records],
        "amount": [float(from_minor(r.amount_minor, r.currency)) for r in records],
    })
    dismissed = _dismissed(session)
    found = []
    for record, flag in zip(records, personal_scores(stream, robust=True)):
        if not flag.flagged or record.id in dismissed:
            continue
        if (start and record.occurred_on < start) or (end and record.occurred_on > end):
            continue
        found.append(UnusualPayment(record, flag.score, flag.reason))
    return sorted(found, key=lambda u: u.record.occurred_on, reverse=True)


def dismiss(session: Session, transaction_id: int, note: str | None = None) -> None:
    ledger.get_transaction(session, transaction_id)  # 404 if missing
    session.add(AuditEvent(actor="user", action="unusual_dismissed", entity_type="transaction",
                           entity_id=transaction_id, details={"note": note, "method": METHOD}))
    session.commit()
