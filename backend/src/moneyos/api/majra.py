"""Money Majra routes: people, groups, shared expenses, loans, payments."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from moneyos.api.routes import SessionDep
from moneyos.db.tables import MajraEntry, MajraGroup, MajraPerson
from moneyos.domain.majra import SplitMethod
from moneyos.domain.money import from_minor
from moneyos.services import majra

router = APIRouter(prefix="/majra", tags=["money majra"])
OWED_NOTE = "Expected back from others: not guaranteed, and not part of your recorded totals or any balance."

Money = Field(gt=0, max_digits=15, decimal_places=2)


class _In(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class PersonIn(_In):
    name: str = Field(min_length=1, max_length=100)


class PersonOut(BaseModel):
    id: int
    name: str
    is_me: bool

    @classmethod
    def of(cls, p: MajraPerson) -> PersonOut:
        return cls(id=p.id, name=p.name, is_me=p.is_me)


class GroupIn(_In):
    name: str = Field(min_length=1, max_length=100)
    currency: str = Field(default="INR", pattern=r"^[A-Za-z]{3}$")
    member_ids: list[int] = Field(min_length=1, description="Other members; you are always included.")


class GroupOut(BaseModel):
    id: int
    name: str
    kind: Literal["group", "direct"]
    currency: str
    members: list[PersonOut]

    @classmethod
    def of(cls, g: MajraGroup) -> GroupOut:
        return cls(id=g.id, name=g.name, kind=g.kind, currency=g.currency, members=[PersonOut.of(m) for m in g.members])


class ParticipantIn(_In):
    person_id: int
    value: Decimal | None = Field(
        default=None, ge=0, description="Amount for 'exact', percentage for 'percent', weight for 'shares'."
    )


class SplitIn(_In):
    method: SplitMethod = SplitMethod.EQUAL
    participants: list[ParticipantIn] = Field(min_length=1)


class ExpenseIn(_In):
    description: str = Field(min_length=1, max_length=200)
    date: date
    amount: Decimal = Money
    paid_by_id: int
    split: SplitIn
    transaction_id: int | None = None


class LoanIn(_In):
    person_id: int
    direction: Literal["lent", "borrowed"]
    amount: Decimal = Money
    currency: str = Field(default="INR", pattern=r"^[A-Za-z]{3}$")
    date: date
    description: str = Field(min_length=1, max_length=200)
    transaction_id: int | None = None


class PaymentIn(_In):
    payer_id: int
    receiver_id: int
    amount: Decimal = Money
    date: date
    description: str = Field(default="Repayment", min_length=1, max_length=200)
    transaction_id: int | None = None
    confirm_duplicate: bool = False


class VoidIn(_In):
    reason: str = Field(min_length=1, max_length=200)


class ShareOut(BaseModel):
    person_id: int
    amount: Decimal


class EntryOut(BaseModel):
    id: int
    kind: Literal["expense", "loan", "payment"]
    description: str
    date: date
    amount: Decimal
    paid_by_id: int
    paid_to_id: int | None
    split_method: str | None
    shares: list[ShareOut]
    transaction_id: int | None
    voided: bool
    void_reason: str | None

    @classmethod
    def of(cls, e: MajraEntry, currency: str) -> EntryOut:
        return cls(
            id=e.id, kind=e.kind, description=e.description, date=e.occurred_on,
            amount=from_minor(e.amount_minor, currency), paid_by_id=e.paid_by_id, paid_to_id=e.paid_to_id,
            split_method=e.split_method,
            shares=[ShareOut(person_id=s.person_id, amount=from_minor(s.share_minor, currency)) for s in e.shares],
            transaction_id=e.transaction_id, voided=e.voided_at is not None, void_reason=e.void_reason,
        )


class BalanceOut(BaseModel):
    person: PersonOut
    balance: Decimal = Field(description="Positive: is owed money. Negative: owes money.")
    status: Literal["is_owed", "owes", "settled"]


class TransferOut(BaseModel):
    payer: PersonOut
    receiver: PersonOut
    amount: Decimal


class GroupDetailOut(BaseModel):
    group: GroupOut
    balances: list[BalanceOut]
    balances_sum_to_zero: bool
    settlement: list[TransferOut]
    settlement_is_minimal: bool = Field(
        description="True when the plan uses the fewest possible payments; very large groups get a good plan instead."
    )
    entries: list[EntryOut]


class PersonPositionOut(BaseModel):
    person: PersonOut
    owes_you: Decimal
    you_owe: Decimal


class MajraSummaryOut(BaseModel):
    currency: str
    owed_to_you: Decimal
    you_owe: Decimal
    note: str = OWED_NOTE
    people: list[PersonPositionOut]


def _detail(session, group: MajraGroup) -> GroupDetailOut:
    state = majra.group_state(session, group)
    people = {m.id: m for m in group.members}
    c = group.currency
    return GroupDetailOut(
        group=GroupOut.of(group),
        balances=[
            BalanceOut(
                person=PersonOut.of(people[pid]), balance=from_minor(b, c),
                status="is_owed" if b > 0 else "owes" if b < 0 else "settled",
            )
            for pid, b in sorted(state.balances.items())
        ],
        balances_sum_to_zero=sum(state.balances.values()) == 0,
        settlement=[
            TransferOut(payer=PersonOut.of(people[t.payer]), receiver=PersonOut.of(people[t.receiver]),
                        amount=from_minor(t.amount, c))
            for t in state.plan.transfers
        ],
        settlement_is_minimal=state.plan.minimal,
        entries=[EntryOut.of(e, c) for e in group_entries(session, group.id)],
    )


def group_entries(session, group_id: int) -> list[MajraEntry]:
    """All entries, voided ones included (so the history stays visible)."""
    return list(session.scalars(select(MajraEntry).where(MajraEntry.group_id == group_id).order_by(MajraEntry.id)))


@router.get("/people", response_model=list[PersonOut])
def list_people(session: SessionDep):
    return [PersonOut.of(p) for p in majra.list_people(session)]


@router.post("/people", response_model=PersonOut, status_code=status.HTTP_201_CREATED)
def add_person(body: PersonIn, session: SessionDep):
    return PersonOut.of(majra.add_person(session, body.name))


@router.get("/groups", response_model=list[GroupOut])
def list_groups(session: SessionDep):
    return [GroupOut.of(g) for g in majra.list_groups(session)]


@router.post("/groups", response_model=GroupDetailOut, status_code=status.HTTP_201_CREATED)
def create_group(body: GroupIn, session: SessionDep):
    return _detail(session, majra.create_group(session, body.name, body.currency, body.member_ids))


@router.get("/groups/{group_id}", response_model=GroupDetailOut)
def get_group(group_id: int, session: SessionDep):
    """Balances, a suggested settlement with the fewest payments, and the full history."""
    return _detail(session, majra.get_group(session, group_id))


@router.post("/groups/{group_id}/expenses", response_model=GroupDetailOut, status_code=status.HTTP_201_CREATED)
def add_expense(group_id: int, body: ExpenseIn, session: SessionDep):
    majra.add_expense(
        session, group_id, description=body.description, occurred_on=body.date, amount=body.amount,
        paid_by_id=body.paid_by_id, method=body.split.method,
        participants=[(p.person_id, p.value) for p in body.split.participants],
        transaction_id=body.transaction_id,
    )
    return _detail(session, majra.get_group(session, group_id))


@router.post("/groups/{group_id}/payments", response_model=GroupDetailOut, status_code=status.HTTP_201_CREATED)
def add_payment(group_id: int, body: PaymentIn, session: SessionDep):
    """Record a repayment. Refused if it is more than is owed, or repeats one already recorded."""
    majra.add_payment(
        session, group_id, payer_id=body.payer_id, receiver_id=body.receiver_id, amount=body.amount,
        occurred_on=body.date, description=body.description, transaction_id=body.transaction_id,
        confirm_duplicate=body.confirm_duplicate,
    )
    return _detail(session, majra.get_group(session, group_id))


@router.post("/loans", response_model=GroupDetailOut, status_code=status.HTTP_201_CREATED)
def add_loan(body: LoanIn, session: SessionDep):
    """Money you lent to, or borrowed from, one person."""
    entry = majra.add_loan(
        session, person_id=body.person_id, lent=body.direction == "lent", amount=body.amount,
        currency=body.currency, occurred_on=body.date, description=body.description,
        transaction_id=body.transaction_id,
    )
    return _detail(session, majra.get_group(session, entry.group_id))


@router.post("/entries/{entry_id}/void", response_model=GroupDetailOut)
def void_entry(entry_id: int, body: VoidIn, session: SessionDep):
    """Cancel an entry. It stays in the history, marked as voided."""
    entry = majra.void_entry(session, entry_id, body.reason)
    return _detail(session, majra.get_group(session, entry.group_id))


@router.get("/summary", response_model=list[MajraSummaryOut])
def summary(session: SessionDep):
    """What others owe you and what you owe, per currency and person."""
    return [summary_out(s) for s in majra.summary(session)]


def summary_out(s: majra.MajraSummary) -> MajraSummaryOut:
    c = s.currency
    return MajraSummaryOut(
        currency=c,
        owed_to_you=from_minor(s.owed_to_you, c),
        you_owe=from_minor(s.you_owe, c),
        people=[
            PersonPositionOut(person=PersonOut.of(p.person), owes_you=from_minor(p.owes_you, c),
                              you_owe=from_minor(p.you_owe, c))
            for p in s.people
        ],
    )
