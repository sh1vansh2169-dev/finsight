"""Money Majra workflows against a real SQLite file."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from moneyos.db.tables import AuditEvent, MajraPerson
from moneyos.domain.majra import SplitMethod, apply
from moneyos.domain.models import Direction
from moneyos.services import ledger, majra
from moneyos.services.errors import ConflictError, InvalidRequestError, NotFoundError

D = date(2026, 3, 10)


@pytest.fixture
def people(session):
    you = majra.me(session)
    sam = majra.add_person(session, "Sam")
    ria = majra.add_person(session, "Ria")
    return you, sam, ria


@pytest.fixture
def trip(session, people):
    """You pay 1,200 (equal); Sam pays 900 (equal shares); Ria pays 300 (exact: You 100, Sam 200)."""
    you, sam, ria = people
    group = majra.create_group(session, "Goa trip", "INR", [sam.id, ria.id])
    everyone = [(you.id, None), (sam.id, None), (ria.id, None)]
    majra.add_expense(session, group.id, description="Dinner", occurred_on=D, amount=Decimal("1200"),
                      paid_by_id=you.id, method=SplitMethod.EQUAL, participants=everyone)
    majra.add_expense(session, group.id, description="Cab", occurred_on=D, amount=Decimal("900"),
                      paid_by_id=sam.id, method=SplitMethod.SHARES,
                      participants=[(you.id, Decimal(1)), (sam.id, Decimal(1)), (ria.id, Decimal(1))])
    majra.add_expense(session, group.id, description="Snacks", occurred_on=D, amount=Decimal("300"),
                      paid_by_id=ria.id, method=SplitMethod.EXACT,
                      participants=[(you.id, Decimal("100")), (sam.id, Decimal("200")), (ria.id, Decimal("0"))])
    return group


def test_group_balances_reconcile_and_settle(session, people, trip):
    you, sam, ria = people
    state = majra.group_state(session, trip)
    # You: +1200 -400 -300 -100 = 400. Sam: -400 +900 -300 -200 = 0. Ria: -400 -300 +300 = -400.
    assert state.balances == {you.id: 40000, sam.id: 0, ria.id: -40000}
    assert sum(state.balances.values()) == 0
    (transfer,) = state.plan.transfers
    assert (transfer.payer, transfer.receiver, transfer.amount) == (ria.id, you.id, 40000)
    assert all(v == 0 for v in apply(state.balances, state.plan.transfers).values())


def test_payments_cannot_overpay_or_repeat_by_accident(session, people, trip):
    you, sam, ria = people
    with pytest.raises(InvalidRequestError, match="more than is outstanding"):
        majra.add_payment(session, trip.id, payer_id=ria.id, receiver_id=you.id, amount=Decimal("400.01"), occurred_on=D)
    with pytest.raises(InvalidRequestError, match="does not owe"):
        majra.add_payment(session, trip.id, payer_id=sam.id, receiver_id=you.id, amount=Decimal("1"), occurred_on=D)

    majra.add_payment(session, trip.id, payer_id=ria.id, receiver_id=you.id, amount=Decimal("100"), occurred_on=D)
    with pytest.raises(ConflictError, match="identical payment"):
        majra.add_payment(session, trip.id, payer_id=ria.id, receiver_id=you.id, amount=Decimal("100"), occurred_on=D)
    majra.add_payment(session, trip.id, payer_id=ria.id, receiver_id=you.id, amount=Decimal("100"), occurred_on=D,
                      confirm_duplicate=True)
    majra.add_payment(session, trip.id, payer_id=ria.id, receiver_id=you.id, amount=Decimal("200"), occurred_on=D)
    state = majra.group_state(session, trip)
    assert all(v == 0 for v in state.balances.values()) and state.plan.transfers == ()


def test_loans_and_summary(session, people, trip):
    you, sam, ria = people
    majra.add_loan(session, person_id=sam.id, lent=True, amount=Decimal("500"), currency="INR",
                   occurred_on=D, description="Concert ticket")
    majra.add_loan(session, person_id=ria.id, lent=False, amount=Decimal("150"), currency="INR",
                   occurred_on=D, description="Borrowed for lunch")
    majra.add_loan(session, person_id=sam.id, lent=True, amount=Decimal("100"), currency="INR",
                   occurred_on=D, description="Auto fare")  # same direct group as the first loan
    assert sum(1 for g in majra.list_groups(session) if g.kind == "direct") == 2

    (inr,) = majra.summary(session)
    # Trip: Ria owes you 400. Direct: Sam owes you 600; you owe Ria 150.
    assert (inr.currency, inr.owed_to_you, inr.you_owe) == ("INR", 100000, 15000)
    by_name = {p.person.name: (p.owes_you, p.you_owe) for p in inr.people}
    assert by_name == {"Sam": (60000, 0), "Ria": (40000, 15000)}


def test_void_reverses_an_entry_and_is_audited(session, people):
    you, sam, _ = people
    loan = majra.add_loan(session, person_id=sam.id, lent=True, amount=Decimal("500"), currency="INR",
                          occurred_on=D, description="Typo amount")
    majra.void_entry(session, loan.id, "entered by mistake")
    (inr,) = majra.summary(session)
    assert inr.owed_to_you == 0
    with pytest.raises(ConflictError):
        majra.void_entry(session, loan.id, "again")
    actions = [e.action for e in session.scalars(select(AuditEvent).where(AuditEvent.entity_id == loan.id,
                                                                            AuditEvent.entity_type == "majra_entry"))]
    assert actions == ["majra_loan_added", "majra_entry_voided"]


def test_linking_a_bank_payment_marks_it_as_lending(session, people, rules):
    you, sam, _ = people
    record, _ = ledger.create_manual(session, occurred_on=D, description="UPI/P2P/SAM", amount=Decimal("500"),
                                     direction=Direction.DEBIT, currency="INR", account="Savings", rules=rules)
    assert record.txn_type == "unknown"
    majra.add_loan(session, person_id=sam.id, lent=True, amount=Decimal("500"), currency="INR", occurred_on=D,
                   description="Lent to Sam", transaction_id=record.id)
    assert (record.txn_type, record.type_basis) == ("lent", "user")
    assert [e.action for e in ledger.audit_trail(session, "transaction", record.id)][-1] == "transaction_corrected"

    with pytest.raises(ConflictError, match="already recorded"):
        majra.add_loan(session, person_id=sam.id, lent=True, amount=Decimal("500"), currency="INR", occurred_on=D,
                       description="Same payment again", transaction_id=record.id)
    with pytest.raises(InvalidRequestError, match="same amount"):
        majra.add_loan(session, person_id=sam.id, lent=True, amount=Decimal("499"), currency="INR", occurred_on=D,
                       description="Wrong amount", transaction_id=record.id)
    with pytest.raises(InvalidRequestError, match="money in"):
        majra.add_loan(session, person_id=sam.id, lent=False, amount=Decimal("500"), currency="INR", occurred_on=D,
                       description="Wrong direction", transaction_id=record.id)


def test_money_owed_is_not_counted_as_money_you_have(session, people, trip):
    """Majra entries never change ledger totals."""
    assert ledger.summarize_ledger(session, ledger.TransactionFilter()) == {}


def test_validation(session, people, trip):
    you, sam, ria = people
    outsider = majra.add_person(session, "Kabir")
    with pytest.raises(InvalidRequestError, match="not a member"):
        majra.add_expense(session, trip.id, description="X", occurred_on=D, amount=Decimal("10"), paid_by_id=you.id,
                          method=SplitMethod.EQUAL, participants=[(you.id, None), (outsider.id, None)])
    with pytest.raises(InvalidRequestError, match="add up to"):
        majra.add_expense(session, trip.id, description="X", occurred_on=D, amount=Decimal("10"), paid_by_id=you.id,
                          method=SplitMethod.EXACT, participants=[(you.id, Decimal("4")), (sam.id, Decimal("5"))])
    with pytest.raises(InvalidRequestError, match="at least one other"):
        majra.create_group(session, "Solo", "INR", [])
    with pytest.raises(ConflictError):
        majra.add_person(session, "Sam")
    with pytest.raises(InvalidRequestError, match="yourself"):
        majra.add_loan(session, person_id=you.id, lent=True, amount=Decimal("1"), currency="INR", occurred_on=D,
                       description="X")
    with pytest.raises(NotFoundError):
        majra.get_group(session, 999)


def test_there_is_only_one_you(session, people):
    session.add(MajraPerson(name="Another me", is_me=True))
    with pytest.raises(IntegrityError):
        session.commit()
