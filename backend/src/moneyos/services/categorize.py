"""Model-based category suggestions for transactions the rules left uncategorised.

Order of authority: the source file and the user first, then keyword rules,
then the model. The model only ever looks at transactions whose category is
still unknown (basis ``none``), and anything it sets is recorded with basis
``model`` so it stays visibly inferred and can be corrected.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from moneyos.db.tables import AuditEvent, TransactionRecord
from moneyos.domain.models import ALLOWED_DIRECTIONS, UNCATEGORIZED, Basis, Direction, TxnType
from moneyos.services.errors import InvalidRequestError

DEFAULT_THRESHOLD = 0.6  # the pre-registered threshold used in the experiment


@dataclass
class Suggestion:
    record: TransactionRecord
    category: str
    confidence: float
    alternatives: list[tuple[str, float]]  # next most likely categories

    def confident(self, threshold: float) -> bool:
        return self.confidence >= threshold


def _candidates(session: Session, limit: int) -> list[TransactionRecord]:
    return list(
        session.scalars(
            select(TransactionRecord)
            .where(
                TransactionRecord.category_basis == Basis.NONE.value,
                TransactionRecord.category == UNCATEGORIZED,
                TransactionRecord.duplicate_of_id.is_(None),
            )
            .options(selectinload(TransactionRecord.account))
            .order_by(TransactionRecord.occurred_on.desc(), TransactionRecord.id.desc())
            .limit(limit)
        )
    )


def suggest(session: Session, model, *, limit: int = 100) -> list[Suggestion]:
    records = _candidates(session, limit)
    if not records:
        return []
    probabilities = model.predict_proba(np.asarray([r.description for r in records], dtype=object))
    classes = list(model.classes_)
    suggestions = []
    for record, row in zip(records, probabilities):
        order = np.argsort(row)[::-1]
        suggestions.append(
            Suggestion(record, classes[order[0]], float(row[order[0]]),
                       [(classes[i], float(row[i])) for i in order[1:3]])
        )
    return suggestions


def apply(session: Session, model, version: str, *, min_confidence: float) -> int:
    """Set categories the model is at least ``min_confidence`` sure of. Returns how many."""
    if not DEFAULT_THRESHOLD <= min_confidence <= 1:
        raise InvalidRequestError(f"min_confidence must be between {DEFAULT_THRESHOLD} and 1")
    applied = 0
    for s in suggest(session, model, limit=10_000):
        if not s.confident(min_confidence):
            continue
        r = s.record
        r.category, r.category_basis = s.category, Basis.MODEL.value
        # Same reasoning as the keyword rules: a categorised debit is spending.
        if r.txn_type == TxnType.UNKNOWN.value and Direction(r.direction) in ALLOWED_DIRECTIONS[TxnType.EXPENSE]:
            r.txn_type, r.type_basis = TxnType.EXPENSE.value, Basis.MODEL.value
        session.add(AuditEvent(actor="system", action="model_categorized", entity_type="transaction", entity_id=r.id,
                               details={"category": s.category, "confidence": round(s.confidence, 4),
                                        "model": version}))
        applied += 1
    session.commit()
    return applied
