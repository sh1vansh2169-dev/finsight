import tempfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from moneyos.analytics.recurring import detect, merchant_key, next_after
from moneyos.domain import simulator as sim
from moneyos.domain import synthetic
from moneyos.domain.dates import add_months
from moneyos.domain.models import Direction, Status, TxnType
from moneyos.domain.pipeline import run_pipeline

D = Decimal

# ------------------------------------------------------------- recurring


def test_detects_the_sample_commitments():
    result = run_pipeline(synthetic.generate(2026).write(Path(tempfile.mkdtemp())))
    found = {s.key: s for s in detect(list(enumerate(result.transactions)), as_of=date(2026, 3, 31))}
    for key in ("acme corp salary", "rent greenview apts", "fibernet broadband", "streamflix subscription",
                "city power electricity bill"):
        assert found[key].cadence == "monthly", key
    assert found["acme corp salary"].direction == Direction.CREDIT
    assert found["rent greenview apts"].typical_amount == D("22000.00") and not found["rent greenview apts"].amount_varies
    assert found["city power electricity bill"].amount_varies
    assert found["rent greenview apts"].next_expected == date(2026, 4, 3)
    assert not any("transfer" in k for k in found)  # own-account transfers are not commitments


def _series(make_txn, days, amount="-499.00", description="STREAMFLIX"):
    return [(i, make_txn(d, description, amount)) for i, d in enumerate(days)]


def test_cadences_and_rejections(make_txn):
    weekly = [date(2026, 1, 5) + timedelta(days=7 * i) for i in range(5)]
    assert detect(_series(make_txn, [d.isoformat() for d in weekly]), as_of=date(2026, 2, 10))[0].cadence == "weekly"
    irregular = ["2026-01-02", "2026-01-09", "2026-02-20", "2026-02-22", "2026-04-30"]
    assert detect(_series(make_txn, irregular), as_of=date(2026, 5, 1)) == []
    two = ["2026-01-05", "2026-02-05"]
    assert detect(_series(make_txn, two), as_of=date(2026, 3, 1)) == []  # too few to tell
    # 4 of 5 gaps are monthly, so only the same-day rule rejects this (two payments on one day: a habit).
    same_day = ["2026-01-05", "2026-01-05", "2026-02-05", "2026-03-05", "2026-04-05", "2026-05-05"]
    assert detect(_series(make_txn, same_day), as_of=date(2026, 5, 6)) == []


def test_a_series_that_stopped_is_marked(make_txn):
    (s,) = detect(_series(make_txn, ["2026-01-05", "2026-02-05", "2026-03-05"]), as_of=date(2026, 6, 1))
    assert s.may_have_stopped and any("may have stopped" in r for r in s.reasons)


def test_failed_payments_do_not_count(make_txn):
    items = _series(make_txn, ["2026-01-05", "2026-02-05"])
    items.append((9, make_txn("2026-03-05", "STREAMFLIX", "-499.00", status=Status.FAILED)))
    assert detect(items, as_of=date(2026, 3, 6)) == []


def test_merchant_key_and_months():
    assert merchant_key("ACME CORP SALARY JAN") == merchant_key("acme corp salary  march") == "acme corp salary"
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert next_after(date(2026, 1, 31), "quarterly") == date(2026, 4, 30)


# ------------------------------------------------------------- schedules


def test_schedule():
    start, end = date(2026, 3, 31), date(2026, 4, 30)
    assert sim.schedule(date(2026, 1, 3), "monthly", start, end) == [date(2026, 4, 3)]
    assert sim.schedule(date(2026, 1, 31), "monthly", date(2026, 2, 1), date(2026, 4, 30)) == [
        date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]  # never drifts to the 28th
    assert len(sim.schedule(date(2026, 4, 2), "weekly", start, end)) == 5
    assert sim.schedule(date(2026, 4, 15), "once", start, end) == [date(2026, 4, 15)]
    assert sim.schedule(date(2026, 6, 1), "once", start, end) == []
    assert sim.schedule(date(2026, 1, 3), "monthly", start, end, until=date(2026, 4, 1)) == []
    assert sim.schedule(date(2025, 6, 10), "yearly", date(2026, 6, 1), date(2026, 6, 30)) == [date(2026, 6, 10)]


# -------------------------------------------------------------- projection


@pytest.fixture
def inputs():
    everyday = sim.everyday_from_history([D(400)] * 30 + [D(800)] * 30, 30, {"Dining": D(6000), "Groceries": D(12000)})
    start = date(2026, 3, 31)
    occurrences = (
        sim.Occurrence(date(2026, 4, 1), "Salary", D("85000")),
        sim.Occurrence(date(2026, 4, 3), "Rent", D("-22000")),
        sim.Occurrence(date(2026, 4, 10), "Electricity", D("-1200"), high=D("1500")),
        sim.Occurrence(date(2026, 5, 3), "Rent", D("-22000")),  # outside the 30 days
    )
    return sim.Inputs(start, 30, "INR", occurrences, everyday,
                      receivables=(("Sam", D("500")),), payables=(("Ria", D("150")),))


def test_everyday_estimate_and_range():
    e = sim.everyday_from_history([D(400)] * 30 + [D(800)] * 30, 30, {"Dining": D(1), "Groceries": D(3)})
    assert (e.per_day, e.mid) == (D("600.00"), D("18000.00"))
    # 31 windows rising evenly from 12,000 (all 400s) to 24,000 (all 800s): 10th/90th percentiles.
    assert e.low == D("13200.00") and e.high == D("22800.00")
    assert e.category_shares == {"Dining": 0.25, "Groceries": 0.75}
    short = sim.everyday_from_history([D(100)] * 40, 30, {})
    assert short.low is None and short.high is None  # not enough history for a range
    assert sim.everyday_from_history([], 30, {}).mid == 0


def test_projection_numbers(inputs):
    p = sim.project(inputs)
    assert (p.commitments_in, p.commitments_out, p.commitments_out_high) == (D("85000.00"), D("23200.00"), D("23500.00"))
    assert p.net_change == D("43800.00")  # 85,000 - 23,200 - 18,000
    assert p.net_change_low == D("38700.00")  # 85,000 - 23,500 - 22,800
    assert p.net_change_high == D("48600.00")  # 85,000 - 23,200 - 13,200
    assert (p.if_repaid, p.if_you_repay) == (D("500.00"), D("150.00"))  # kept out of the estimate
    assert p.reserve_for_commitments == D("23500.00")
    assert p.balance is None and any("No current balance" in a for a in p.assumptions)
    assert len(p.path) == 30 and p.path[-1][1] == p.net_change
    assert [o.name for o in p.occurrences] == ["Salary", "Rent", "Electricity"]


def test_balance_only_from_a_stated_balance(inputs):
    from dataclasses import replace

    p = sim.project(replace(inputs, starting_balance=D("10000")))
    assert (p.balance, p.balance_low, p.balance_high) == (D("53800.00"), D("48700.00"), D("58600.00"))
    assert any("you entered" in a for a in p.assumptions)


def test_scenarios(inputs):
    base = sim.project(inputs).net_change
    bought = sim.project(sim.purchase(inputs, D("3000"), date(2026, 4, 5), "Headphones"))
    assert bought.net_change == base - 3000 and "Headphones" in bought.changes[0]

    cut = sim.project(sim.reduce_category(inputs, "Dining", D("15")))
    assert cut.net_change == base + D("900.00")  # Dining is 6,000 of 18,000 (a third); 15% of a third of 18,000

    bill = sim.project(sim.add_recurring(inputs, "Gym", D("1500"), "monthly", date(2026, 4, 15)))
    assert bill.net_change == base - 1500  # only one due date falls inside the 30 days

    delayed = sim.project(sim.delay_repayment(inputs, "Sam"))
    assert delayed.if_repaid == 0 and delayed.net_change == base  # was never counted as money you have

    no_rent = sim.project(sim.skip_commitment(inputs, "Rent"))
    assert no_rent.net_change == base + 22000

    with pytest.raises(ValueError):
        sim.reduce_category(inputs, "Travel", D("10"))
    with pytest.raises(ValueError):
        sim.delay_repayment(inputs, "Nobody")
    with pytest.raises(ValueError):
        sim.purchase(inputs, D("0"), date(2026, 4, 5))


def test_same_inputs_same_answer(inputs):
    assert sim.project(inputs) == sim.project(inputs)
