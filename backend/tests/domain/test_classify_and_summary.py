from datetime import date
from decimal import Decimal

import pytest

from moneyos.domain.classify import RulesError, classify, load_rules, parse_rules
from moneyos.domain.models import UNCATEGORIZED, Basis, Status, TxnType
from moneyos.domain.summary import summarize, summarize_by_currency


@pytest.fixture(scope="module")
def rules():
    return load_rules()


@pytest.mark.parametrize(
    ("description", "amount", "txn_type", "category"),
    [
        ("ACME CORP SALARY", "85000.00", TxnType.INCOME, "Salary"),
        ("RENT PAYMENT GREENVIEW APTS", "-22000.00", TxnType.EXPENSE, "Housing"),
        ("city  power electricity bill", "-1500.00", TxnType.EXPENSE, "Utilities"),
        ("CHAI POINT CAFE", "-60.00", TxnType.EXPENSE, "Dining"),
        ("TRANSFER TO CREDIT CARD 4321", "-5000.00", TxnType.TRANSFER, UNCATEGORIZED),
        ("PAYMENT RECEIVED THANK YOU", "5000.00", TxnType.TRANSFER, UNCATEGORIZED),
        ("SHOPKART REFUND", "499.00", TxnType.REFUND, "Shopping"),
        ("UPI REVERSAL 1234", "200.00", TxnType.REVERSAL, UNCATEGORIZED),
        # No evidence either way: stays unknown instead of being assumed.
        ("UPI/P2P/FRIEND-7731", "-1500.00", TxnType.UNKNOWN, UNCATEGORIZED),
        ("NEFT CR 88231 ANON", "2750.00", TxnType.UNKNOWN, UNCATEGORIZED),
        ("FUND TRANSFER 99812", "-800.00", TxnType.UNKNOWN, UNCATEGORIZED),  # bare "transfer"
        # Money in from a merchant without the word "refund" is not assumed to be one.
        ("SHOPKART ONLINE STORE", "499.00", TxnType.UNKNOWN, "Shopping"),
        # Whole-word matching.
        ("CABINET MAKERS", "-10.00", TxnType.UNKNOWN, UNCATEGORIZED),
        ("PARENT TEACHER FUND", "-10.00", TxnType.UNKNOWN, UNCATEGORIZED),
        # Income rules only apply to money coming in.
        ("SALARY ADVANCE REPAYMENT", "-10.00", TxnType.UNKNOWN, UNCATEGORIZED),
    ],
)
def test_classify(make_txn, rules, description, amount, txn_type, category):
    t = classify(make_txn(description=description, amount=amount), rules)
    assert (t.txn_type, t.category) == (txn_type, category)
    assert t.type_basis == (Basis.NONE if txn_type == TxnType.UNKNOWN else Basis.RULE)
    assert t.category_basis == (Basis.NONE if category == UNCATEGORIZED else Basis.RULE)


def test_classify_never_overrides_source_or_user_values(make_txn, rules):
    stated = make_txn(
        description="FRESHMART GROCERIES",
        category="Party supplies",
        category_basis=Basis.SOURCE,
        txn_type=TxnType.LENT,
        type_basis=Basis.USER,
    )
    assert classify(stated, rules) is stated


def test_category_from_source_makes_a_debit_an_expense(make_txn, rules):
    t = classify(make_txn(description="XYZ", category="Hobbies", category_basis=Basis.SOURCE), rules)
    assert (t.txn_type, t.type_basis, t.category_basis) == (TxnType.EXPENSE, Basis.RULE, Basis.SOURCE)


def test_custom_rules(make_txn):
    rules = parse_rules(
        """
        [[type_rules]]
        type = "lent"
        direction = "debit"
        keywords = ["loan to"]

        [[categories]]
        name = "Pets"
        keywords = ["vet"]
        """
    )
    assert rules.categories == ("Pets",)
    assert classify(make_txn(description="Loan to Sam"), rules).txn_type == TxnType.LENT
    vet = classify(make_txn(description="City Vet Clinic"), rules)
    assert (vet.category, vet.txn_type) == ("Pets", TxnType.EXPENSE)


@pytest.mark.parametrize(
    "text",
    [
        "not toml [",
        '[[type_rules]]\ntype = "salary"\nkeywords = ["x"]',
        '[[type_rules]]\ntype = "income"\ndirection = "sideways"\nkeywords = ["x"]',
        '[[categories]]\nname = "X"',
        '[[categories]]\nname = "X"\nkeywords = ["!!"]',
    ],
)
def test_bad_rules_are_rejected(text):
    with pytest.raises(RulesError):
        parse_rules(text)


# ------------------------------------------------------------------ summary


@pytest.fixture
def ledger(make_txn):
    def t(day, description, amount, txn_type, category=UNCATEGORIZED, status=Status.POSTED):
        return make_txn(day, description, amount, txn_type=txn_type, category=category, status=status)

    return [
        t("2026-01-01", "SALARY", "1000.00", TxnType.INCOME, "Salary"),
        t("2026-01-03", "RENT", "-400.00", TxnType.EXPENSE, "Housing"),
        t("2026-01-09", "FOOD", "-50.25", TxnType.EXPENSE, "Groceries"),
        t("2026-01-20", "TO CARD", "-200.00", TxnType.TRANSFER),
        t("2026-01-25", "LOAN TO SAM", "-300.00", TxnType.LENT),
        t("2026-02-01", "SALARY", "1000.00", TxnType.INCOME, "Salary"),
        t("2026-02-03", "RENT", "-400.00", TxnType.EXPENSE, "Housing"),
        t("2026-02-10", "FOOD", "-75.50", TxnType.EXPENSE, "Groceries"),
        t("2026-02-11", "REFUND", "20.00", TxnType.REFUND, "Groceries"),
        t("2026-02-12", "SAM PAID BACK", "100.00", TxnType.REPAYMENT_RECEIVED),
        t("2026-02-15", "MYSTERY CREDIT", "60.00", TxnType.UNKNOWN),
        t("2026-02-16", "MYSTERY DEBIT", "-35.00", TxnType.UNKNOWN),
        t("2026-02-17", "CASH", "-15.00", TxnType.EXPENSE),
        t("2026-02-18", "DECLINED", "-999.00", TxnType.EXPENSE, "Housing", Status.FAILED),
        t("2026-02-19", "PENDING", "-5.00", TxnType.EXPENSE, "Groceries", Status.PENDING),
        t("2026-02-21", "FROM SAVINGS", "200.00", TxnType.TRANSFER),
    ]


def test_summary_totals(ledger):
    s = summarize(ledger)

    assert s.currency == "INR"
    assert s.transaction_count == 16
    assert (s.start_date, s.end_date) == (date(2026, 1, 1), date(2026, 2, 21))
    assert s.income == Decimal("2000.00")
    assert s.expenses == Decimal("945.75")  # failed 999.00 excluded, pending 5.00 included
    assert s.refunds == Decimal("20.00")
    assert s.by_type[TxnType.LENT] == Decimal("300.00")
    assert s.by_type[TxnType.REPAYMENT_RECEIVED] == Decimal("100.00")
    assert (s.unclassified_inflow, s.unclassified_outflow) == (Decimal("60.00"), Decimal("35.00"))
    assert s.inflow == Decimal("2180.00")
    assert s.outflow == Decimal("1280.75")
    assert s.net_cash_flow == Decimal("899.25")
    assert (s.transfers_in, s.transfers_out) == (Decimal("200.00"), Decimal("200.00"))
    assert TxnType.TRANSFER not in s.by_type


def test_summary_reconciles(ledger):
    """Every included transaction is counted exactly once."""
    s = summarize(ledger)
    counted = [t for t in ledger if t.status != Status.FAILED and t.txn_type != TxnType.TRANSFER]

    assert s.net_cash_flow == sum(t.amount for t in counted)
    assert s.inflow + s.outflow == sum(s.by_type.values())
    assert sum(s.expenses_by_category.values()) == s.expenses
    assert sum(m.income for m in s.by_month.values()) == s.income
    assert sum(m.expenses for m in s.by_month.values()) == s.expenses
    assert sum(m.net_cash_flow for m in s.by_month.values()) == s.net_cash_flow


def test_summary_by_month_category_and_largest(ledger):
    s = summarize(ledger, top_n=2)

    assert list(s.by_month) == ["2026-01", "2026-02"]
    january = s.by_month["2026-01"]
    assert (january.income, january.expenses, january.net_cash_flow) == (
        Decimal("1000.00"), Decimal("450.25"), Decimal("249.75"),
    )
    assert s.expenses_by_category == {
        "Housing": Decimal("800.00"),
        "Groceries": Decimal("130.75"),
        UNCATEGORIZED: Decimal("15.00"),
    }
    assert [t.amount for t in s.largest_expenses] == [Decimal("-400.00"), Decimal("-400.00")]


def test_summary_data_quality(ledger):
    q = summarize(ledger).quality
    assert (q.unknown_type, q.uncategorized_expenses, q.pending, q.failed_excluded) == (2, 1, 1, 1)
    warnings = " ".join(q.warnings())
    assert "unknown type" in warnings and "failed" in warnings and "pending" in warnings


def test_summary_of_nothing():
    s = summarize([])
    assert s.transaction_count == 0
    assert (s.start_date, s.end_date) == (None, None)
    assert s.net_cash_flow == 0
    assert s.by_month == {} and s.expenses_by_category == {}
    assert s.quality.warnings() == []


def test_mixed_currencies_are_never_added_together(make_txn):
    mixed = [
        make_txn(amount="-10.00", txn_type=TxnType.EXPENSE),
        make_txn(amount="-3.00", currency="USD", txn_type=TxnType.EXPENSE),
    ]
    with pytest.raises(ValueError, match="mixed currencies"):
        summarize(mixed)

    by_currency = summarize_by_currency(mixed)
    assert list(by_currency) == ["INR", "USD"]
    assert by_currency["INR"].expenses == Decimal("10.00")
    assert by_currency["USD"].expenses == Decimal("3.00")


def test_refunds_reduce_spending_in_their_category(ledger, make_txn):
    s = summarize(ledger)
    # Groceries purchases 50.25 + 75.50 + 5.00 pending = 130.75, minus a 20.00 refund.
    assert s.spending == s.expenses - s.refunds == Decimal("925.75")
    assert s.spending_by_category["Groceries"] == Decimal("110.75")
    assert s.expenses_by_category["Groceries"] == Decimal("130.75")  # purchases unchanged
    assert sum(s.spending_by_category.values()) == s.spending
    assert s.by_month["2026-02"].spending == s.by_month["2026-02"].expenses - Decimal("20.00")


def test_refund_only_category_goes_negative_rather_than_vanishing(make_txn):
    refund = make_txn("2026-04-02", "SHOPKART REFUND", "300.00", txn_type=TxnType.REFUND, category="Shopping")
    s = summarize([refund])
    assert s.spending_by_category == {"Shopping": Decimal("-300.00")}
    assert s.spending == Decimal("-300.00")
