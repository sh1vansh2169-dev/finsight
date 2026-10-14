"""Duplicate review queue.

The matcher proposes pairs (``match_candidates``); only the user resolves
them. Confirming a duplicate sets ``duplicate_of_id`` on the record that is
dropped, which removes it from listings and totals but keeps it, with its
provenance, so the decision can be undone. Every decision is audited.
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from moneyos.db.tables import AuditEvent, MatchCandidate, TransactionRecord, utc_now
from moneyos.domain.matching import MatchConfig, find_candidates
from moneyos.services.errors import ConflictError, InvalidRequestError, NotFoundError
from moneyos.services.mapping import to_domain

OPEN, DUPLICATE, DISTINCT, SUPERSEDED = "open", "duplicate", "distinct", "superseded"


def find_new_candidates(session: Session, config: MatchConfig = MatchConfig()) -> list[MatchCandidate]:
    """Propose pairs not seen before. Flushes but does not commit.

    Pairs already in the table are skipped whatever their status, so a pair
    the user called distinct is never proposed again.
    """
    active = session.scalars(
        select(TransactionRecord)
        .where(TransactionRecord.duplicate_of_id.is_(None))
        .options(selectinload(TransactionRecord.account))
    ).all()
    known = {
        (a, b) for a, b in session.execute(select(MatchCandidate.transaction_a_id, MatchCandidate.transaction_b_id))
    }

    created = []
    for id_x, id_y, match in find_candidates([(r.id, to_domain(r)) for r in active], config):
        a, b = sorted((id_x, id_y))
        if (a, b) in known:
            continue
        candidate = MatchCandidate(
            transaction_a_id=a, transaction_b_id=b, score=match.score, reasons=list(match.reasons), status=OPEN
        )
        session.add(candidate)
        created.append(candidate)
        known.add((a, b))
    session.flush()
    return created


def scan(session: Session) -> int:
    created = find_new_candidates(session)
    session.commit()
    return len(created)


def list_candidates(session: Session, status: str | None = OPEN) -> list[MatchCandidate]:
    query = select(MatchCandidate).options(
        selectinload(MatchCandidate.transaction_a).selectinload(TransactionRecord.account),
        selectinload(MatchCandidate.transaction_b).selectinload(TransactionRecord.account),
    )
    if status is not None:
        query = query.where(MatchCandidate.status == status)
    return list(session.scalars(query.order_by(MatchCandidate.score.desc(), MatchCandidate.id)))


def count_open(session: Session, transaction_ids: list[int] | None = None) -> int:
    query = select(MatchCandidate.id).where(MatchCandidate.status == OPEN)
    if transaction_ids is not None:
        query = query.where(
            or_(MatchCandidate.transaction_a_id.in_(transaction_ids), MatchCandidate.transaction_b_id.in_(transaction_ids))
        )
    return len(session.scalars(query).all())


def _get(session: Session, candidate_id: int) -> MatchCandidate:
    candidate = session.get(MatchCandidate, candidate_id)
    if candidate is None:
        raise NotFoundError(f"review item {candidate_id} not found")
    return candidate


def _audit(session: Session, candidate: MatchCandidate, action: str, **details) -> None:
    session.add(
        AuditEvent(
            actor="user", action=action, entity_type="match_candidate", entity_id=candidate.id,
            details={"transaction_a_id": candidate.transaction_a_id,
                     "transaction_b_id": candidate.transaction_b_id, **details},
        )
    )


def resolve(session: Session, candidate_id: int, *, duplicate: bool, keep_id: int | None = None) -> MatchCandidate:
    """Record the user's decision on a pair.

    For a duplicate, ``keep_id`` names the record to keep; the other is
    marked as its duplicate, and any other open pairs involving the dropped
    record are closed as superseded.
    """
    candidate = _get(session, candidate_id)
    if candidate.status != OPEN:
        raise ConflictError(f"review item {candidate_id} is already {candidate.status}")
    pair = (candidate.transaction_a_id, candidate.transaction_b_id)

    if not duplicate:
        if keep_id is not None:
            raise InvalidRequestError("keep_transaction_id only applies to duplicates")
        candidate.status = DISTINCT
        candidate.resolved_at = utc_now()
        _audit(session, candidate, "match_marked_distinct")
        session.commit()
        return candidate

    if keep_id not in pair:
        raise InvalidRequestError(f"keep_transaction_id must be one of {pair[0]} or {pair[1]}")
    drop_id = pair[1] if keep_id == pair[0] else pair[0]
    drop = session.get(TransactionRecord, drop_id)
    drop.duplicate_of_id = keep_id
    candidate.status, candidate.kept_id, candidate.resolved_at = DUPLICATE, keep_id, utc_now()

    superseded = session.scalars(
        select(MatchCandidate).where(
            MatchCandidate.status == OPEN,
            MatchCandidate.id != candidate.id,
            or_(MatchCandidate.transaction_a_id == drop_id, MatchCandidate.transaction_b_id == drop_id),
        )
    ).all()
    for other in superseded:
        other.status, other.resolved_at = SUPERSEDED, utc_now()

    _audit(session, candidate, "match_marked_duplicate", kept=keep_id, dropped=drop_id,
           superseded=[c.id for c in superseded])
    session.add(
        AuditEvent(actor="user", action="marked_duplicate", entity_type="transaction", entity_id=drop_id,
                   details={"duplicate_of": keep_id, "review_item": candidate.id})
    )
    session.commit()
    return candidate


def reopen(session: Session, candidate_id: int) -> MatchCandidate:
    """Undo a decision: the pair goes back to the queue and nothing stays dropped."""
    candidate = _get(session, candidate_id)
    if candidate.status not in (DUPLICATE, DISTINCT):
        raise ConflictError(f"review item {candidate_id} is {candidate.status}; only decisions can be reopened")

    restored: list[int] = []
    if candidate.status == DUPLICATE:
        drop_id = (
            candidate.transaction_b_id if candidate.kept_id == candidate.transaction_a_id else candidate.transaction_a_id
        )
        drop = session.get(TransactionRecord, drop_id)
        if drop.duplicate_of_id == candidate.kept_id:
            drop.duplicate_of_id = None
            session.add(
                AuditEvent(actor="user", action="unmarked_duplicate", entity_type="transaction",
                           entity_id=drop_id, details={"review_item": candidate.id})
            )
        # Pairs closed only because this record was dropped become open again.
        for other in session.scalars(
            select(MatchCandidate).where(
                MatchCandidate.status == SUPERSEDED,
                or_(MatchCandidate.transaction_a_id == drop_id, MatchCandidate.transaction_b_id == drop_id),
            )
        ):
            other_ids = (other.transaction_a_id, other.transaction_b_id)
            if all(session.get(TransactionRecord, i).duplicate_of_id is None for i in other_ids):
                other.status, other.resolved_at = OPEN, None
                restored.append(other.id)

    previous = candidate.status
    candidate.status, candidate.kept_id, candidate.resolved_at = OPEN, None, None
    _audit(session, candidate, "match_reopened", previous=previous, restored=restored)
    session.commit()
    return candidate
