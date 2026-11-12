"""Recurring-payment detection over the ledger, and stored commitments."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from moneyos.analytics.recurring import RecurringSeries, detect
from moneyos.db.tables import AuditEvent, Commitment, TransactionRecord
from moneyos.domain.models import Direction
from moneyos.domain.money import from_minor, to_minor
from moneyos.domain.simulator import Occurrence, schedule
from moneyos.services.errors import ConflictError, InvalidRequestError, NotFoundError
from moneyos.services.mapping import to_domain

CADENCES = ("once", "weekly", "monthly", "quarterly", "yearly")


def _audit(session: Session, action: str, commitment_id: int, **details) -> None:
    session.add(AuditEvent(actor="user", action=action, entity_type="commitment", entity_id=commitment_id,
                           details=details))


def active_records(session: Session, currency: str) -> list[TransactionRecord]:
    return list(session.scalars(
        select(TransactionRecord)
        .where(TransactionRecord.currency == currency, TransactionRecord.duplicate_of_id.is_(None))
        .options(selectinload(TransactionRecord.account))
        .order_by(TransactionRecord.occurred_on, TransactionRecord.id)
    ))


def detected(session: Session, currency: str, as_of: date) -> list[RecurringSeries]:
    return detect([(r.id, to_domain(r)) for r in active_records(session, currency)], as_of=as_of)


def list_commitments(session: Session, currency: str | None = None, *, active_only: bool = False) -> list[Commitment]:
    query = select(Commitment).order_by(Commitment.status, Commitment.next_due, Commitment.name)
    if currency:
        query = query.where(Commitment.currency == currency)
    if active_only:
        query = query.where(Commitment.status == "active")
    return list(session.scalars(query))


def get(session: Session, commitment_id: int) -> Commitment:
    commitment = session.get(Commitment, commitment_id)
    if commitment is None:
        raise NotFoundError(f"commitment {commitment_id} not found")
    return commitment


def _tidy(text: str) -> str:
    """Bank narrations are often all upper or all lower case; make them readable."""
    return text.title() if text.isupper() or text.islower() else text


def confirm_detected(session: Session, key: str, currency: str, as_of: date, *, name: str | None = None) -> Commitment:
    """Turn a detected recurring series into a commitment, using its typical amount and schedule."""
    series = next((s for s in detected(session, currency, as_of) if s.key == key), None)
    if series is None:
        raise NotFoundError(f"no recurring payment {key!r} was detected")
    if session.scalar(select(Commitment.id).where(Commitment.merchant_key == key, Commitment.currency == currency,
                                                   Commitment.status != "ended")):
        raise ConflictError(f"{key!r} is already a commitment")
    commitment = Commitment(
        name=name or _tidy(series.name), direction=series.direction.value,
        amount_minor=to_minor(series.typical_amount, currency), amount_varies=series.amount_varies,
        high_minor=to_minor(series.high, currency) if series.amount_varies else None, currency=currency,
        cadence=series.cadence, next_due=series.next_expected, category=series.category, source="detected",
        merchant_key=series.key, status="active",
    )
    session.add(commitment)
    session.flush()
    _audit(session, "commitment_confirmed", commitment.id, key=key, confidence=series.confidence)
    session.commit()
    return commitment


def add_manual(
    session: Session, *, name: str, direction: Direction, amount: Decimal, currency: str, cadence: str,
    next_due: date, category: str = "Uncategorized", end_date: date | None = None,
) -> Commitment:
    if cadence not in CADENCES:
        raise InvalidRequestError(f"cadence must be one of {', '.join(CADENCES)}")
    if amount <= 0:
        raise InvalidRequestError("amount must be positive")
    if end_date and end_date < next_due:
        raise InvalidRequestError("end date is before the first due date")
    try:
        minor = to_minor(amount, currency)
    except ValueError as error:
        raise InvalidRequestError(str(error)) from None
    commitment = Commitment(name=name, direction=direction.value, amount_minor=minor, amount_varies=False,
                            currency=currency.upper(), cadence=cadence, next_due=next_due, end_date=end_date,
                            category=category, source="manual", status="active")
    session.add(commitment)
    session.flush()
    _audit(session, "commitment_added", commitment.id, name=name)
    session.commit()
    return commitment


def update(session: Session, commitment_id: int, *, status: str | None = None, amount: Decimal | None = None,
           next_due: date | None = None, end_date: date | None = None) -> Commitment:
    commitment = get(session, commitment_id)
    before = {"status": commitment.status, "amount_minor": commitment.amount_minor,
              "next_due": commitment.next_due.isoformat(),
              "end_date": commitment.end_date.isoformat() if commitment.end_date else None}
    if status is not None:
        if status not in ("active", "paused", "ended"):
            raise InvalidRequestError("status must be active, paused or ended")
        commitment.status = status
    if amount is not None:
        if amount <= 0:
            raise InvalidRequestError("amount must be positive")
        commitment.amount_minor = to_minor(amount, commitment.currency)
    if next_due is not None:
        commitment.next_due = next_due
    if end_date is not None:
        commitment.end_date = end_date
    _audit(session, "commitment_updated", commitment.id, before=before)
    session.commit()
    return commitment


def occurrences(session: Session, currency: str, start: date, end: date) -> list[Occurrence]:
    """Scheduled amounts of active commitments in [start, end]: positive in, negative out."""
    out = []
    for c in list_commitments(session, currency, active_only=True):
        amount = from_minor(c.amount_minor, c.currency)
        high = from_minor(c.high_minor, c.currency) if c.amount_varies and c.high_minor else None
        signed = amount if c.direction == Direction.CREDIT.value else -amount
        for day in schedule(c.next_due, c.cadence, start, end, c.end_date):
            out.append(Occurrence(day, c.name, signed, high if signed < 0 else None))
    return sorted(out, key=lambda o: (o.on, o.name))
