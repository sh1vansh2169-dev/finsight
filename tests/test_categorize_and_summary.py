from datetime import date
from decimal import Decimal

import pytest

from moneyos.categorize import INCOME, TRANSFER, categorize
from moneyos.models import UNCATEGORIZED
from moneyos.summary import summarize, summarize_by_currency


@pytest.mark.parametrize(
    ("description", "amount", "expected"),
    [
        ("ACME CORP SALARY", "85000.00", INCOME),
        ("RENT PAYMENT GREENVIEW APTS", "-22000.00", "Housing"),
        ("city  power electricity bill", "-1500.00", "Utilities"),
        ("FRESHMART GROCERIES", "-450.00", "Groceries"),
        ("CHAI POINT CAFE", "-60.00", "Dining"),
        ("QUICKCAB RIDE", "-300.00", "Transport"),
        ("TRANSFER TO CREDIT CARD 4321", "-5000.00", TRANSFER),
        ("PAYMENT RECEIVED THANK YOU", "5000.00", TRANSFER),
        ("SOMETHING UNKNOWN", "-10.00", UNCATEGORIZED),
        ("CABINET MAKERS", "-10.00", UNCATEGORIZED),  # "cab" must match as a whole word
        ("PARENT TEACHER FUND", "-10.00", UNCATEGORIZED),  # so must "rent"
        ("SALARY ADVANCE REPAYMENT", "-10.00", UNCATEGORIZED),  # income rules need money in
    ],
)
def test_categorize(make_txn, description, amount, expected):
    assert categorize(make_txn(description=description, amount=amount)).category == expected


def test_categorize_keeps_category_from_file(make_txn):
    txn = make_txn(description="FRESHMART GROCERIES", category="Party supplies")
    assert categorize(txn) is txn


@pytest.fixture
def ledger(make_txn):
    return [
        make_txn("2026-01-01", "SALARY", "1000.00", category=INCOME),
        make_txn("2026-01-03", "RENT", "-400.00", category="Housing"),
        make_txn("2026-01-09", "FOOD", "-50.25", category="Groceries"),
        make_txn("2026-01-20", "TO CARD", "-200.00", category=TRANSFER),
        make_txn("2026-02-01", "SALARY", "1000.00", category=INCOME),
        make_txn("2026-02-03", "RENT", "-400.00", category="Housing"),
        make_txn("2026-02-10", "FOOD", "-75.50", category="Groceries"),
        make_txn("2026-02-11", "REFUND", "20.00", category="Groceries"),
        make_txn("2026-02-21", "FROM SAVINGS", "200.00", category=TRANSFER),
    ]


def test_summary_totals(ledger):
    s = summarize(ledger)

    assert s.currency == "INR"
    assert s.transaction_count == 9
    assert (s.start_date, s.end_date) == (date(2026, 1, 1), date(2026, 2, 21))
    assert s.totals.income == Decimal("2020.00")
    assert s.totals.expenses == Decimal("925.75")
    assert s.totals.net == Decimal("1094.25")
    assert (s.transfers_in, s.transfers_out) == (Decimal("200.00"), Decimal("200.00"))


def test_summary_by_month(ledger):
    s = summarize(ledger)

    assert list(s.by_month) == ["2026-01", "2026-02"]
    january, february = s.by_month.values()
    assert (january.income, january.expenses, january.net) == (
        Decimal("1000.00"), Decimal("450.25"), Decimal("549.75"),
    )
    assert (february.income, february.expenses, february.net) == (
        Decimal("1020.00"), Decimal("475.50"), Decimal("544.50"),
    )


def test_summary_by_category_and_largest(ledger):
    s = summarize(ledger, top_n=2)

    assert s.expenses_by_category == {"Housing": Decimal("800.00"), "Groceries": Decimal("125.75")}
    assert list(s.expenses_by_category) == ["Housing", "Groceries"]  # largest first
    assert [t.amount for t in s.largest_expenses] == [Decimal("-400.00"), Decimal("-400.00")]


def test_summary_parts_add_up_to_totals(ledger):
    s = summarize(ledger)
    assert sum(s.expenses_by_category.values()) == s.totals.expenses
    assert sum(m.income for m in s.by_month.values()) == s.totals.income
    assert sum(m.expenses for m in s.by_month.values()) == s.totals.expenses
    # Net must equal the plain sum of every non-transfer amount.
    assert s.totals.net == sum(t.amount for t in ledger if t.category != TRANSFER)


def test_summary_of_nothing():
    s = summarize([])
    assert s.transaction_count == 0
    assert (s.start_date, s.end_date) == (None, None)
    assert s.totals.net == 0
    assert s.by_month == {} and s.expenses_by_category == {}


def test_mixed_currencies_are_never_added_together(make_txn):
    mixed = [make_txn(amount="-10.00"), make_txn(amount="-3.00", currency="USD")]
    with pytest.raises(ValueError, match="mixed currencies"):
        summarize(mixed)

    by_currency = summarize_by_currency(mixed)
    assert list(by_currency) == ["INR", "USD"]
    assert by_currency["INR"].totals.expenses == Decimal("10.00")
    assert by_currency["USD"].totals.expenses == Decimal("3.00")
