"""Duplicate review: proposals, decisions, undo, audit, and the effect on totals."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from moneyos.db.tables import AuditEvent
from moneyos.domain import synthetic
from moneyos.domain.models import Direction
from moneyos.services import imports, ledger, review
from moneyos.services.errors import ConflictError, InvalidRequestError, NotFoundError


def _import(session, rules, name, text, account=None):
    batch = imports.preview_import(
        session, filename=name, content=text.encode("utf-8"),
        options=imports.ImportOptions(account=account), rules=rules,
    )
    return imports.commit_import(session, batch.id)


def _load_everything(session, rules, dataset):
    for name, text in dataset.files.items():
        _import(session, rules, name, text, synthetic.CARD_ACCOUNT if "card" in name else None)
    _import(session, rules, dataset.payapp.name, dataset.payapp.text, synthetic.PAYAPP_ACCOUNT)


def _summary(session):
    (s,) = ledger.summarize_ledger(session, ledger.TransactionFilter()).values()
    return s


def _manual(session, rules, description, account, day="2026-03-05", amount="250.00"):
    record, warnings = ledger.create_manual(
        session, occurred_on=date.fromisoformat(day), description=description, amount=Decimal(amount),
        direction=Direction.DEBIT, currency="INR", account=account, rules=rules,
    )
    return record, warnings


def _is_app(record):
    return record.account.name == synthetic.PAYAPP_ACCOUNT


@pytest.fixture
def loaded(session, rules, dataset):
    _load_everything(session, rules, dataset)
    return session


APP_ONLY = Decimal("340.00") + Decimal("999.00") + Decimal("410.00")  # see synthetic._payapp


def test_cross_source_duplicates_are_proposed_not_removed(loaded, dataset):
    app = dataset.payapp
    open_items = review.list_candidates(loaded)
    assert len(open_items) == len(app.mirrored) + 1  # + the identical chai pair
    assert all(item.score >= 60 and item.reasons for item in open_items)

    # Before review, money out includes both copies of every mirrored payment.
    # (Compared on total outflow: app names like "Chai Point" match no rule,
    # so some copies are unclassified rather than expenses.)
    expected = dataset.expected
    mirrored = sum((-m.amount for m in app.mirrored), Decimal(0))
    assert _summary(loaded).outflow == expected.expenses + expected.unclassified_outflow + mirrored + APP_ONLY


def test_reviewing_everything_gives_correct_totals(loaded, dataset):
    for item in review.list_candidates(loaded):
        a, b = item.transaction_a, item.transaction_b
        if _is_app(a) or _is_app(b):
            bank = b if _is_app(a) else a
            review.resolve(loaded, item.id, duplicate=True, keep_id=bank.id)
        else:
            review.resolve(loaded, item.id, duplicate=False)  # the two chai purchases are real

    assert review.count_open(loaded) == 0
    expected = dataset.expected
    s = _summary(loaded)
    # Each payment is counted once; the app adds only what the bank never saw.
    assert s.expenses == expected.expenses + APP_ONLY
    assert s.outflow == expected.expenses + expected.unclassified_outflow + APP_ONLY
    assert s.income == expected.income

    # Dropped records are hidden from listings but still exist, with a pointer.
    visible, total = ledger.list_transactions(loaded, ledger.TransactionFilter(), limit=500)
    everything, all_total = ledger.list_transactions(
        loaded, ledger.TransactionFilter(include_duplicates=True), limit=500
    )
    dropped = [r for r in everything if r.duplicate_of_id is not None]
    assert len(dropped) == len(dataset.payapp.mirrored)
    assert all(_is_app(r) for r in dropped)
    assert all_total - total == len(dropped)

    # A later scan does not re-propose anything already decided.
    assert review.scan(loaded) == 0


def test_reimporting_after_review_adds_nothing(loaded, rules, dataset):
    for item in review.list_candidates(loaded):
        keep = item.transaction_b_id if _is_app(item.transaction_a) else item.transaction_a_id
        review.resolve(loaded, item.id, duplicate=True, keep_id=keep)
    batch = _import(loaded, rules, dataset.payapp.name, dataset.payapp.text, synthetic.PAYAPP_ACCOUNT)
    assert batch.inserted_rows == 0
    assert review.count_open(loaded) == 0


def test_decision_audit_and_undo(loaded):
    item = next(i for i in review.list_candidates(loaded) if _is_app(i.transaction_b) or _is_app(i.transaction_a))
    app_record = item.transaction_a if _is_app(item.transaction_a) else item.transaction_b
    bank_record = item.transaction_b if app_record is item.transaction_a else item.transaction_a
    before = _summary(loaded).expenses

    review.resolve(loaded, item.id, duplicate=True, keep_id=bank_record.id)
    assert app_record.duplicate_of_id == bank_record.id
    assert _summary(loaded).expenses == before - abs(ledger_amount(app_record))

    review.reopen(loaded, item.id)
    assert app_record.duplicate_of_id is None
    assert item.status == "open" and item.kept_id is None
    assert _summary(loaded).expenses == before

    actions = [
        e.action for e in loaded.scalars(
            select(AuditEvent).where(AuditEvent.entity_type == "match_candidate", AuditEvent.entity_id == item.id)
        )
    ]
    assert actions == ["match_marked_duplicate", "match_reopened"]
    record_actions = [e.action for e in ledger.audit_trail(loaded, "transaction", app_record.id)]
    assert record_actions == ["marked_duplicate", "unmarked_duplicate"]


def ledger_amount(record):
    return Decimal(record.amount_minor) / 100


def test_resolution_errors(loaded):
    item = review.list_candidates(loaded)[0]
    with pytest.raises(InvalidRequestError):
        review.resolve(loaded, item.id, duplicate=True, keep_id=999_999)
    with pytest.raises(InvalidRequestError):
        review.resolve(loaded, item.id, duplicate=False, keep_id=item.transaction_a_id)
    review.resolve(loaded, item.id, duplicate=False)
    with pytest.raises(ConflictError):
        review.resolve(loaded, item.id, duplicate=False)
    with pytest.raises(NotFoundError):
        review.resolve(loaded, 999_999, duplicate=False)
    review.reopen(loaded, item.id)
    with pytest.raises(ConflictError):
        review.reopen(loaded, item.id)  # already open


def test_three_way_match_supersedes_and_restores(session, rules):
    """A cash entry, its bank copy and its app copy: three pairs, one payment."""
    bank, _ = _manual(session, rules, "UPI/SPICE ROUTE RESTAURANT", "Savings")
    app, warnings = _manual(session, rules, "Spice Route", "PayApp")
    assert warnings and "review" in warnings[0]
    cash, _ = _manual(session, rules, "Dinner at Spice Route", "Cash", day="2026-03-06")
    items = {frozenset((i.transaction_a_id, i.transaction_b_id)): i for i in review.list_candidates(session)}
    assert set(items) == {frozenset((bank.id, app.id)), frozenset((bank.id, cash.id)), frozenset((app.id, cash.id))}

    bank_app = items[frozenset((bank.id, app.id))]
    review.resolve(session, bank_app.id, duplicate=True, keep_id=bank.id)
    # The app record is gone, so its pair with the cash entry is moot.
    assert items[frozenset((app.id, cash.id))].status == "superseded"
    assert items[frozenset((bank.id, cash.id))].status == "open"

    review.reopen(session, bank_app.id)
    assert items[frozenset((app.id, cash.id))].status == "open"
