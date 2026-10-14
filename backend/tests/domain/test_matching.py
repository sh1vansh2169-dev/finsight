from decimal import Decimal

import pytest

from moneyos.domain import synthetic
from moneyos.domain.classify import classify
from moneyos.domain.importer import import_csv
from moneyos.domain.matching import MatchConfig, description_similarity, find_candidates, score_pair
from moneyos.domain.models import Status
from moneyos.domain.pipeline import run_pipeline


@pytest.fixture
def bank(make_txn):
    return make_txn(
        day="2026-02-10", description="UPI/SPICE ROUTE RESTAURANT/4471", amount="-860.00", account="Savings"
    )


@pytest.fixture
def app(make_txn):
    return make_txn(day="2026-02-09", description="Spice Route", amount="-860.00", account="PayApp", reference="PA1")


# ------------------------------------------------------------ similarity


@pytest.mark.parametrize(
    ("a", "b", "low", "high"),
    [
        ("Spice Route", "UPI/SPICE ROUTE RESTAURANT/4471", 1.0, 1.0),  # containment
        ("QuickCab", "quickcab  ride", 1.0, 1.0),
        ("FRESHMART GROCERIES", "FreshMart Groceries #12", 1.0, 1.0),  # numbers ignored
        ("NEFT payment to ACME", "ACME", 1.0, 1.0),
        # Different rail words on both sides would otherwise dilute the match.
        ("UPI SPICE ROUTE", "Spice Route payment received", 1.0, 1.0),
        ("Corner Kirana Store", "FIBERNET BROADBAND", 0.0, 0.4),
        ("Chai Point", "Spice Route", 0.0, 0.4),
    ],
)
def test_description_similarity(a, b, low, high):
    assert low <= description_similarity(a, b) <= high


# --------------------------------------------------------------- scoring


def test_cross_source_pair_is_proposed_with_reasons(bank, app):
    result = score_pair(bank, app)
    assert result is not None
    assert result.score == 87  # 0.30*0.75 + 0.55*1.0 + 0.15*0.6
    assert result.confidence == "high"
    assert result.reasons == (
        "Same amount: 860.00 INR money out",
        "Dates 1 day apart",
        'Descriptions 100% similar: "UPI/SPICE ROUTE RESTAURANT/4471" and "Spice Route"',
        "Different accounts (Savings and PayApp); one payment can appear in two sources",
    )
    assert score_pair(app, bank).score == result.score  # symmetric


@pytest.mark.parametrize(
    "change",
    [
        {"amount": "-860.01"},
        {"amount": "860.00"},  # opposite direction
        {"currency": "USD"},
        {"day": "2026-02-14"},  # 4 days from the bank entry
        {"status": Status.FAILED},  # no money moved
    ],
)
def test_gates(bank, app, make_txn, change):
    fields = {"day": "2026-02-09", "description": "Spice Route", "amount": "-860.00", "account": "PayApp", **change}
    assert score_pair(bank, make_txn(**fields)) is None


def test_conflicting_references_on_the_same_account_are_never_proposed(make_txn):
    a = make_txn(description="SHOPKART", reference="CC1")
    b = make_txn(description="SHOPKART", reference="CC2")
    assert score_pair(a, b) is None
    # On different accounts the references come from different systems.
    assert score_pair(a, make_txn(description="SHOPKART", reference="CC2", account="Other")) is not None


def test_unrelated_payments_with_the_same_amount_and_day_are_not_proposed(make_txn):
    bill = make_txn(day="2026-02-12", description="FIBERNET BROADBAND", amount="-999.00")
    shop = make_txn(day="2026-02-12", description="Corner Kirana Store", amount="-999.00", account="PayApp")
    assert score_pair(bill, shop) is None
    assert score_pair(bill, shop, MatchConfig(threshold=0)).score < 60


def test_identical_rows_score_100(make_txn):
    a, b = make_txn(description="CHAI POINT CAFE"), make_txn(description="CHAI POINT CAFE")
    assert score_pair(a, b).score == 100


def test_find_candidates_windows_and_orders(make_txn):
    rows = [
        make_txn(day="2026-01-01", description="Shop A", amount="-50.00"),
        make_txn(day="2026-01-03", description="SHOP A", amount="-50.00", account="App"),  # 2 days
        make_txn(day="2026-01-01", description="Shop A", amount="-50.00", account="App2"),  # same day
        make_txn(day="2026-01-09", description="Shop A", amount="-50.00", account="App3"),  # too far
        make_txn(day="2026-01-01", description="Shop A", amount="-51.00", account="App4"),  # other amount
    ]
    matches = find_candidates(list(enumerate(rows)))
    pairs = [frozenset((a, b)) for a, b, _ in matches]
    assert set(pairs) == {frozenset((0, 2)), frozenset((0, 1)), frozenset((1, 2))}
    assert pairs[0] == frozenset((0, 2))  # same day ranks first
    scores = [m.score for _, _, m in matches]
    assert scores == sorted(scores, reverse=True) == [94, 79, 79]
    assert find_candidates([]) == []


# ------------------------------------------- evaluation on synthetic truth


@pytest.mark.parametrize("seed", [2026, 1, 7, 99, 12345])
def test_synthetic_cross_source_matching(seed, tmp_path, rules):
    """Every true app/bank pair is proposed; the only other proposal is the
    deliberately identical pair of chai purchases, which needs a human."""
    data = synthetic.generate(seed)
    statements = run_pipeline(data.write(tmp_path))
    app = import_csv(tmp_path / data.payapp.name, account=synthetic.PAYAPP_ACCOUNT)
    assert app.rejected == []
    transactions = statements.transactions + [classify(t, rules) for t in app.transactions]
    by_key = dict(enumerate(transactions))

    truth = {(m.app_reference, m.bank_date, m.bank_description, m.amount) for m in data.payapp.mirrored}

    def is_true_pair(a, b):
        app_side, bank_side = (a, b) if a.account == synthetic.PAYAPP_ACCOUNT else (b, a)
        key = (app_side.reference, bank_side.date, bank_side.description.upper(), bank_side.amount)
        return key in truth

    matches = find_candidates(list(by_key.items()))
    found = [(by_key[a], by_key[b]) for a, b, _ in matches]
    true_found = [pair for pair in found if is_true_pair(*pair)]
    others = [pair for pair in found if not is_true_pair(*pair)]

    assert len(true_found) == len(truth)  # recall 100% on this data
    assert len(others) == 1
    (a, b), = others
    assert a.description.upper() == b.description.upper() == "CHAI POINT CAFE"
    assert a.amount == b.amount == Decimal("-120.00")

    failed = [t for t in app.transactions if t.status == Status.FAILED]
    assert len(failed) == data.payapp.failed
    assert not any(t in pair for pair in found for t in failed)
