"""Money Majra storage and workflows. Calculations live in domain/majra.py.

Expected repayments are money you are *owed*, not money you have: nothing
here is added to ledger totals or balances.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from moneyos.db.tables import AuditEvent, MajraEntry, MajraGroup, MajraPerson, MajraShare, TransactionRecord, utc_now
from moneyos.domain.majra import (
    Entry,
    EntryKind,
    MajraError,
    SettlementPlan,
    SplitMethod,
    allocate,
    balances,
    check_payment,
    settle,
)
from moneyos.domain.models import ALLOWED_DIRECTIONS, Direction, TxnType
from moneyos.domain.money import to_minor
from moneyos.services import ledger
from moneyos.services.errors import ConflictError, InvalidRequestError, NotFoundError

ME_NAME = "You"


def _audit(session: Session, action: str, entity_type: str, entity_id: int, **details) -> None:
    session.add(AuditEvent(actor="user", action=action, entity_type=entity_type, entity_id=entity_id, details=details))


def _minor(amount: Decimal, currency: str) -> int:
    if amount <= 0:
        raise InvalidRequestError("amount must be positive")
    try:
        return to_minor(amount, currency)
    except ValueError as error:
        raise InvalidRequestError(str(error)) from None


def _exact_share(value: Decimal | None, currency: str) -> int | None:
    """An exact-split amount in minor units; zero is allowed (someone who took nothing)."""
    if value is None or value == 0:
        return None if value is None else 0
    return _minor(value, currency)


# ------------------------------------------------------------------- people


def me(session: Session) -> MajraPerson:
    person = session.scalar(select(MajraPerson).where(MajraPerson.is_me.is_(True)))
    if person is None:
        person = MajraPerson(name=ME_NAME, is_me=True)
        session.add(person)
        session.flush()
    return person


def add_person(session: Session, name: str) -> MajraPerson:
    name = " ".join(name.split())
    if not name:
        raise InvalidRequestError("a name is required")
    me(session)
    if session.scalar(select(MajraPerson).where(MajraPerson.name == name)):
        raise ConflictError(f"{name!r} already exists")
    person = MajraPerson(name=name)
    session.add(person)
    session.flush()
    _audit(session, "person_added", "majra_person", person.id, name=name)
    session.commit()
    return person


def list_people(session: Session) -> list[MajraPerson]:
    me(session)
    session.commit()
    return list(session.scalars(select(MajraPerson).order_by(MajraPerson.is_me.desc(), MajraPerson.name)))


def get_person(session: Session, person_id: int) -> MajraPerson:
    person = session.get(MajraPerson, person_id)
    if person is None:
        raise NotFoundError(f"person {person_id} not found")
    return person


# ------------------------------------------------------------------- groups


def create_group(session: Session, name: str, currency: str, member_ids: list[int]) -> MajraGroup:
    """A group always includes you."""
    you = me(session)
    members = {you.id: you}
    for person_id in member_ids:
        members[person_id] = get_person(session, person_id)
    if len(members) < 2:
        raise InvalidRequestError("a group needs at least one other person")
    group = MajraGroup(name=" ".join(name.split()) or "Group", kind="group", currency=currency.upper(),
                       members=list(members.values()))
    session.add(group)
    session.flush()
    _audit(session, "group_created", "majra_group", group.id, members=sorted(members))
    session.commit()
    return group


def direct_group(session: Session, person: MajraPerson, currency: str) -> MajraGroup:
    """The one-to-one group for lending between you and ``person`` in ``currency``."""
    you = me(session)
    if person.id == you.id:
        raise InvalidRequestError("you cannot lend to yourself")
    for group in session.scalars(
        select(MajraGroup).where(MajraGroup.kind == "direct", MajraGroup.currency == currency.upper())
    ):
        if {m.id for m in group.members} == {you.id, person.id}:
            return group
    group = MajraGroup(name=f"You and {person.name}", kind="direct", currency=currency.upper(), members=[you, person])
    session.add(group)
    session.flush()
    return group


def get_group(session: Session, group_id: int) -> MajraGroup:
    group = session.get(MajraGroup, group_id)
    if group is None:
        raise NotFoundError(f"group {group_id} not found")
    return group


def list_groups(session: Session) -> list[MajraGroup]:
    return list(session.scalars(select(MajraGroup).order_by(MajraGroup.kind, MajraGroup.name)))


def active_entries(session: Session, group_id: int) -> list[MajraEntry]:
    return list(
        session.scalars(
            select(MajraEntry)
            .where(MajraEntry.group_id == group_id, MajraEntry.voided_at.is_(None))
            .options(selectinload(MajraEntry.shares))
            .order_by(MajraEntry.occurred_on, MajraEntry.id)
        )
    )


def _domain(entry: MajraEntry) -> Entry:
    return Entry(
        EntryKind(entry.kind),
        entry.amount_minor,
        entry.paid_by_id,
        entry.paid_to_id,
        {s.person_id: s.share_minor for s in entry.shares} if entry.kind == EntryKind.EXPENSE else None,
    )


@dataclass
class GroupState:
    group: MajraGroup
    balances: dict[int, int]  # person id -> minor units; positive = owed money
    plan: SettlementPlan


def group_state(session: Session, group: MajraGroup) -> GroupState:
    balance = {m.id: 0 for m in group.members}
    balance.update(balances(_domain(e) for e in active_entries(session, group.id)))
    return GroupState(group, balance, settle(balance))


def _require_members(group: MajraGroup, *person_ids: int) -> None:
    member_ids = {m.id for m in group.members}
    missing = [p for p in person_ids if p not in member_ids]
    if missing:
        raise InvalidRequestError(f"person {missing[0]} is not a member of this group")


# --------------------------------------------------------------- ledger link


def _link(session: Session, entry: MajraEntry, transaction_id: int | None, group: MajraGroup) -> None:
    """Tie the entry to the bank/card transaction that carried the money.

    The transaction must be in the group's currency, for the same amount, in
    the right direction from your point of view, and not already used by
    another entry. Its type is then set (as your correction, audited) to
    lent / borrowed / repayment, where that type fits its direction.
    """
    if transaction_id is None:
        return
    record = ledger.get_transaction(session, transaction_id)
    you = me(session).id
    if you not in (entry.paid_by_id, entry.paid_to_id):
        raise InvalidRequestError("only entries where you paid or received money can be linked to your transactions")
    if record.currency != group.currency or record.amount_minor != entry.amount_minor:
        raise InvalidRequestError("the linked transaction must have the same amount and currency")
    expected = Direction.DEBIT if entry.paid_by_id == you else Direction.CREDIT
    if record.direction != expected.value:
        raise InvalidRequestError(f"the linked transaction should be money {'out' if expected == Direction.DEBIT else 'in'}")
    taken = session.scalar(
        select(MajraEntry.id).where(MajraEntry.transaction_id == transaction_id, MajraEntry.voided_at.is_(None))
    )
    if taken:
        raise ConflictError(f"transaction {transaction_id} is already recorded as Money Majra entry {taken}")
    entry.transaction_id = transaction_id

    new_type = {
        (EntryKind.LOAN, Direction.DEBIT): TxnType.LENT,
        (EntryKind.LOAN, Direction.CREDIT): TxnType.BORROWED,
        (EntryKind.PAYMENT, Direction.DEBIT): TxnType.REPAYMENT_MADE,
        (EntryKind.PAYMENT, Direction.CREDIT): TxnType.REPAYMENT_RECEIVED,
    }.get((EntryKind(entry.kind), expected))
    if new_type and record.txn_type != new_type.value and expected in ALLOWED_DIRECTIONS[new_type]:
        ledger.correct_transaction(session, record.id, txn_type=new_type, commit=False)


# ------------------------------------------------------------------ entries


def add_expense(
    session: Session,
    group_id: int,
    *,
    description: str,
    occurred_on: date,
    amount: Decimal,
    paid_by_id: int,
    method: SplitMethod,
    participants: list[tuple[int, Decimal | None]],
    transaction_id: int | None = None,
) -> MajraEntry:
    group = get_group(session, group_id)
    total = _minor(amount, group.currency)
    _require_members(group, paid_by_id, *(p for p, _ in participants))
    values = [(p, _exact_share(v, group.currency)) for p, v in participants] if method == SplitMethod.EXACT else participants
    try:
        shares = allocate(total, method, values)
    except MajraError as error:
        raise InvalidRequestError(str(error)) from None
    entry = MajraEntry(
        group_id=group.id, kind=EntryKind.EXPENSE.value, description=description, occurred_on=occurred_on,
        amount_minor=total, paid_by_id=paid_by_id, split_method=method.value,
        shares=[MajraShare(person_id=p, share_minor=s) for p, s in shares.items()],
    )
    session.add(entry)
    _link(session, entry, transaction_id, group)
    session.flush()
    _audit(session, "majra_expense_added", "majra_entry", entry.id, group=group.id, amount=total)
    session.commit()
    return entry


def add_loan(
    session: Session,
    *,
    person_id: int,
    lent: bool,
    amount: Decimal,
    currency: str,
    occurred_on: date,
    description: str,
    transaction_id: int | None = None,
) -> MajraEntry:
    """Money you lent to (``lent=True``) or borrowed from a person."""
    person = get_person(session, person_id)
    group = direct_group(session, person, currency)
    you = me(session)
    lender, borrower = (you, person) if lent else (person, you)
    entry = MajraEntry(
        group_id=group.id, kind=EntryKind.LOAN.value, description=description, occurred_on=occurred_on,
        amount_minor=_minor(amount, group.currency), paid_by_id=lender.id, paid_to_id=borrower.id,
    )
    session.add(entry)
    _link(session, entry, transaction_id, group)
    session.flush()
    _audit(session, "majra_loan_added", "majra_entry", entry.id, group=group.id, lender=lender.id, borrower=borrower.id)
    session.commit()
    return entry


def add_payment(
    session: Session,
    group_id: int,
    *,
    payer_id: int,
    receiver_id: int,
    amount: Decimal,
    occurred_on: date,
    description: str = "Repayment",
    transaction_id: int | None = None,
    confirm_duplicate: bool = False,
) -> MajraEntry:
    """A repayment or settlement. Refused if it overpays or looks like a repeat."""
    group = get_group(session, group_id)
    _require_members(group, payer_id, receiver_id)
    minor = _minor(amount, group.currency)
    try:
        check_payment(group_state(session, group).balances, payer_id, receiver_id, minor)
    except MajraError as error:
        raise InvalidRequestError(str(error)) from None
    repeat = session.scalar(
        select(MajraEntry.id).where(
            MajraEntry.group_id == group.id, MajraEntry.kind == EntryKind.PAYMENT.value,
            MajraEntry.paid_by_id == payer_id, MajraEntry.paid_to_id == receiver_id,
            MajraEntry.amount_minor == minor, MajraEntry.occurred_on == occurred_on,
            MajraEntry.voided_at.is_(None),
        )
    )
    if repeat and not confirm_duplicate:
        raise ConflictError(
            f"an identical payment on the same day is already recorded (entry {repeat}); "
            "send confirm_duplicate=true if this really is a second payment"
        )
    entry = MajraEntry(
        group_id=group.id, kind=EntryKind.PAYMENT.value, description=description, occurred_on=occurred_on,
        amount_minor=minor, paid_by_id=payer_id, paid_to_id=receiver_id,
    )
    session.add(entry)
    _link(session, entry, transaction_id, group)
    session.flush()
    _audit(session, "majra_payment_added", "majra_entry", entry.id, group=group.id, payer=payer_id,
           receiver=receiver_id, confirmed_duplicate=bool(repeat))
    session.commit()
    return entry


def void_entry(session: Session, entry_id: int, reason: str) -> MajraEntry:
    entry = session.get(MajraEntry, entry_id)
    if entry is None:
        raise NotFoundError(f"entry {entry_id} not found")
    if entry.voided_at is not None:
        raise ConflictError(f"entry {entry_id} is already voided")
    entry.voided_at, entry.void_reason = utc_now(), reason
    _audit(session, "majra_entry_voided", "majra_entry", entry.id, reason=reason)
    session.commit()
    return entry


# ------------------------------------------------------------------ summary


@dataclass
class PersonPosition:
    person: MajraPerson
    currency: str
    owes_you: int  # minor units, from suggested settlements
    you_owe: int


@dataclass
class MajraSummary:
    currency: str
    owed_to_you: int
    you_owe: int
    people: list[PersonPosition]


def summary(session: Session) -> list[MajraSummary]:
    """Your position across every group, per currency.

    Per-person amounts come from each group's suggested settlement: in a
    shared group, who pays whom is a choice, and this is the plan FinSight
    suggests.
    """
    you = me(session)
    session.commit()
    owed, owing = defaultdict(int), defaultdict(int)
    per_person: dict[tuple[int, str], list[int]] = defaultdict(lambda: [0, 0])
    for group in list_groups(session):
        state = group_state(session, group)
        mine = state.balances.get(you.id, 0)
        if mine > 0:
            owed[group.currency] += mine
        else:
            owing[group.currency] -= mine
        for t in state.plan.transfers:
            if t.receiver == you.id:
                per_person[(t.payer, group.currency)][0] += t.amount
            elif t.payer == you.id:
                per_person[(t.receiver, group.currency)][1] += t.amount
    currencies = sorted(set(owed) | set(owing) | {c for _, c in per_person})
    return [
        MajraSummary(
            currency=c,
            owed_to_you=owed[c],
            you_owe=owing[c],
            people=[
                PersonPosition(get_person(session, pid), c, a, b)
                for (pid, cur), (a, b) in sorted(per_person.items())
                if cur == c and (a or b)
            ],
        )
        for c in currencies
    ]
