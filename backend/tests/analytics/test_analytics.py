import statistics
from datetime import date
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from moneyos.analytics.aggregate import cash_flow_series
from moneyos.analytics.coverage import Interval, build_coverage, daily_coverage, merge
from moneyos.analytics.frame import counted, transactions_frame
from moneyos.analytics.quality import quality_report
from moneyos.analytics.stats import spending_stats
from moneyos.domain import synthetic
from moneyos.domain.budgets import BudgetState, budget_use
from moneyos.domain.models import Status, TxnType
from moneyos.domain.pipeline import run_pipeline
from moneyos.domain.summary import summarize


def _t(make_txn, day, amount, txn_type=TxnType.EXPENSE, **kw):
    return make_txn(day, kw.pop("description", "X"), amount, txn_type=txn_type, **kw)


# ------------------------------------------------------------------ frame


def test_frame_keeps_money_exact(make_txn):
    frame = transactions_frame([_t(make_txn, "2026-01-01", "-0.10"), _t(make_txn, "2026-01-01", "-0.20")])
    assert frame["amount_minor"].dtype == "int64"
    assert frame["amount_minor"].sum() == -30  # exactly 0.30, no float drift
    assert transactions_frame([]).empty


def test_counted_excludes_failed_and_transfers(make_txn):
    frame = transactions_frame([
        _t(make_txn, "2026-01-01", "-1.00"),
        _t(make_txn, "2026-01-01", "-2.00", status=Status.FAILED),
        _t(make_txn, "2026-01-01", "-3.00", TxnType.TRANSFER),
    ])
    assert counted(frame)["amount_minor"].tolist() == [-100]


# -------------------------------------------- aggregation, cross-validated


@pytest.mark.parametrize("seed", [2026, 7, 12345])
def test_monthly_series_agrees_with_the_ledger_summary(seed, tmp_path):
    """Two independent implementations (Pandas here, plain Python in
    domain/summary.py) must give identical monthly figures."""
    result = run_pipeline(synthetic.generate(seed).write(tmp_path))
    summary = result.summaries["INR"]
    frame = transactions_frame(result.transactions)
    monthly = cash_flow_series(frame, "month", date(2026, 1, 1), date(2026, 3, 31))

    assert [str(p) for p in monthly.index] == list(summary.by_month)
    for period, row in monthly.iterrows():
        expected = summary.by_month[str(period)]
        assert row["income"] == expected.income * 100
        assert row["expenses"] == expected.expenses * 100
        assert row["net_cash_flow"] == expected.net_cash_flow * 100
        assert row["refunds"] == expected.refunds * 100
        assert row["spending"] == expected.spending * 100
    assert monthly["net_cash_flow"].sum() == summary.net_cash_flow * 100


def test_daily_and_weekly_add_up_to_monthly(tmp_path):
    frame = transactions_frame(run_pipeline(synthetic.generate(2026).write(tmp_path)).transactions)
    start, end = date(2026, 1, 1), date(2026, 3, 31)
    daily = cash_flow_series(frame, "day", start, end)
    weekly = cash_flow_series(frame, "week", start, end)
    monthly = cash_flow_series(frame, "month", start, end)
    assert len(daily) == 90
    for column in ("income", "expenses", "net_cash_flow"):
        assert daily[column].sum() == weekly[column].sum() == monthly[column].sum()
    # ISO weeks: 1 Jan 2026 is a Thursday, so the first week runs Mon 29 Dec - Sun 4 Jan.
    first = weekly.index[0]
    assert (first.start_time.date(), first.end_time.date()) == (date(2025, 12, 29), date(2026, 1, 4))
    assert weekly["days"].iloc[0] == 4  # only 1-4 Jan fall inside the requested range


# ------------------------------------------------------------- coverage


def test_merge_and_gaps():
    assert merge([Interval(date(2026, 1, 1), date(2026, 1, 10)), Interval(date(2026, 1, 11), date(2026, 1, 20))]) == (
        Interval(date(2026, 1, 1), date(2026, 1, 20)),
    )
    coverage = build_coverage([
        ("Bank", date(2026, 3, 1), date(2026, 3, 31)),
        ("Bank", date(2026, 1, 1), date(2026, 1, 31)),
        ("Bank", date(2026, 1, 15), date(2026, 2, 5)),  # overlaps the first
        ("Card", date(2026, 1, 1), date(2026, 3, 31)),
    ])
    bank = coverage["Bank"]
    assert bank.intervals == (Interval(date(2026, 1, 1), date(2026, 2, 5)), Interval(date(2026, 3, 1), date(2026, 3, 31)))
    assert bank.gaps == (Interval(date(2026, 2, 6), date(2026, 2, 28)),)
    assert bank.gaps[0].days == 23
    assert coverage["Card"].gaps == ()


def test_uncovered_periods_are_missing_not_zero(make_txn):
    frame = transactions_frame([
        _t(make_txn, "2026-01-05", "-100.00", account="Bank"),
        _t(make_txn, "2026-03-05", "-300.00", account="Bank"),
    ])
    coverage = build_coverage([("Bank", date(2026, 1, 1), date(2026, 1, 31)), ("Bank", date(2026, 3, 1), date(2026, 3, 31))])
    monthly = cash_flow_series(frame, "month", date(2026, 1, 1), date(2026, 3, 31), coverage)

    assert monthly["expenses"].tolist()[0] == 10000
    assert np.isnan(monthly["expenses"].iloc[1])  # February: no statement, so unknown
    assert monthly["coverage"].tolist() == [1.0, 0.0, 1.0]
    # Averages skip the unknown month instead of counting it as zero spending.
    assert monthly["expenses"].mean() == 20000

    daily = daily_coverage(coverage, date(2026, 1, 31), date(2026, 2, 1))
    assert daily.tolist() == [1.0, 0.0]


def test_partial_coverage_is_reported_as_a_fraction():
    coverage = build_coverage([("Bank", date(2026, 1, 1), date(2026, 1, 31)), ("Card", date(2026, 1, 16), date(2026, 1, 31))])
    days = daily_coverage(coverage, date(2026, 1, 1), date(2026, 1, 31))
    assert days.iloc[0] == 0.5 and days.iloc[-1] == 1.0


def test_synthetic_coverage(tmp_path):
    data = synthetic.generate(2026)
    result = run_pipeline(data.write(tmp_path))
    spans = []
    for f in result.files:
        for account in {t.account for t in f.transactions}:
            dates = [t.date for t in f.transactions if t.account == account]
            spans.append((account, min(dates), max(dates)))
    coverage = build_coverage(spans)
    savings = coverage["Sample Savings 0001"]
    assert savings.gaps == ()  # the two statements overlap
    assert savings.first == date(2026, 1, 1)


# ----------------------------------------------------------- quality


def test_quality_report(make_txn):
    frame = transactions_frame([
        _t(make_txn, "2026-01-05", "-10.00", account="Bank", category="Food", reference="R1", status=Status.POSTED),
        _t(make_txn, "2026-01-06", "-20.00", account="Bank"),  # uncategorised, unknown status, no reference
        _t(make_txn, "2026-01-07", "5.00", TxnType.UNKNOWN, account="Bank"),
        _t(make_txn, "2026-01-08", "-7.00", account="Cash", category="Food"),
    ])
    coverage = build_coverage([("Bank", date(2026, 1, 1), date(2026, 1, 10)), ("Bank", date(2026, 1, 20), date(2026, 1, 31))])
    report = quality_report(frame, coverage, rejected_rows=2, open_duplicate_reviews=1)

    gaps = {g.field: (g.missing, g.total) for g in report.field_gaps}
    assert gaps == {"txn_type": (1, 4), "category": (1, 3), "status": (3, 4), "reference": (3, 4)}
    assert report.uncovered_accounts == ("Cash",)
    text = " | ".join(report.warnings)
    assert "11 Jan 2026 to 19 Jan 2026 (9 days)" in text
    assert "Cash has only manually entered records" in text
    assert "1 possible duplicate pair(s)" in text and "2 imported row(s) were rejected" in text


# ------------------------------------------------------------- stats


def test_spending_stats_against_the_statistics_module(make_txn):
    amounts = ["-100.00", "-200.00", "-300.00", "-400.00"]
    rows = [_t(make_txn, f"2026-01-0{i + 5}", a, category="Food" if i < 3 else "Rent") for i, a in enumerate(amounts)]
    rows.append(_t(make_txn, "2026-01-09", "999.00", TxnType.INCOME))  # not spending
    stats = spending_stats(transactions_frame(rows))
    values = [10000, 20000, 30000, 40000]

    assert (stats.count, stats.total_minor) == (4, 100000)
    assert stats.mean_minor == statistics.mean(values)
    assert stats.median_minor == statistics.median(values)
    assert stats.std_minor == pytest.approx(statistics.stdev(values))
    assert stats.p90_minor == pytest.approx(np.quantile(values, 0.9))
    assert stats.by_category["total"].to_dict() == {"Food": 60000, "Rent": 40000}
    assert stats.by_category["share"].sum() == pytest.approx(1.0)


def test_weekday_average_uses_covered_days_only(make_txn):
    # Two Mondays of data, but only one of them was covered by a statement.
    rows = [_t(make_txn, "2026-01-05", "-70.00"), _t(make_txn, "2026-01-12", "-30.00")]
    covered = pd.date_range("2026-01-05", "2026-01-11", freq="D")  # one week: one Monday
    stats = spending_stats(transactions_frame(rows), covered_days=covered)
    monday = stats.by_weekday.loc["Monday"]
    assert (monday["total"], monday["covered_days"], monday["average_per_day"]) == (10000, 1, 10000)


def test_month_over_month(make_txn):
    rows = [
        _t(make_txn, "2026-01-05", "-100.00", category="Food"),
        _t(make_txn, "2026-02-05", "-150.00", category="Food"),
        _t(make_txn, "2026-02-06", "-40.00", category="Fun"),
    ]
    mom = spending_stats(transactions_frame(rows)).month_over_month
    assert mom.attrs["months"] == ("2026-01", "2026-02")
    assert mom.loc["Food"].tolist() == [10000, 15000, 5000]
    assert mom.loc["Fun"].tolist() == [0, 4000, 4000]


def test_mixed_currencies_are_refused(make_txn):
    frame = transactions_frame([_t(make_txn, "2026-01-01", "-1.00"), _t(make_txn, "2026-01-01", "-1.00", currency="USD")])
    with pytest.raises(ValueError, match="mixed currencies"):
        spending_stats(frame)
    with pytest.raises(ValueError, match="mixed currencies"):
        cash_flow_series(frame, "day", date(2026, 1, 1), date(2026, 1, 1))


# ------------------------------------------------------------ budgets


@pytest.mark.parametrize(
    ("spent", "state", "percent"),
    [("0.00", BudgetState.ON_TRACK, 0), ("3960.00", BudgetState.ON_TRACK, 79), ("4000.00", BudgetState.CLOSE, 80),
     ("5000.00", BudgetState.CLOSE, 100), ("5000.01", BudgetState.OVER, 100), ("7500.00", BudgetState.OVER, 150)],
)
def test_budget_states(spent, state, percent):
    use = budget_use("Groceries", "INR", Decimal("5000.00"), Decimal(spent), (2026, 3), date(2026, 4, 2))
    assert (use.state, use.percent_used) == (state, percent)
    assert use.projected_month_total is None  # the month is over


def test_budget_state_follows_the_amount_not_the_rounded_percent():
    # 79.9% rounds to 80% for display, but is still under the 80% line.
    use = budget_use("Groceries", "INR", Decimal("5000.00"), Decimal("3995.00"), (2026, 3), date(2026, 4, 2))
    assert use.percent_used == 80
    assert use.state == BudgetState.ON_TRACK


def test_budget_pace_is_an_estimate_with_minimum_history():
    early = budget_use("Dining", "INR", Decimal("3000"), Decimal("1500"), (2026, 3), date(2026, 3, 5))
    assert early.projected_month_total is None  # too few days to project
    mid = budget_use("Dining", "INR", Decimal("3000"), Decimal("1500"), (2026, 3), date(2026, 3, 10))
    assert mid.projected_month_total == Decimal("4650.00")  # 1500 / 10 * 31
    assert "an estimate" in mid.message()
    over = budget_use("Dining", "INR", Decimal("3000"), Decimal("3600"), (2026, 3), date(2026, 3, 31))
    assert over.message() == "120% of the Dining budget used; 600.00 INR over the limit."
    for use in (early, mid, over):
        assert "overspent" not in use.message().lower()
    with pytest.raises(ValueError):
        budget_use("Dining", "INR", Decimal("0"), Decimal("1"), (2026, 3), date(2026, 3, 1))


def test_only_actionable_gaps_become_warnings(make_txn):
    frame = transactions_frame([_t(make_txn, "2026-01-05", "-10.00", category="Food")])  # no status, no reference
    report = quality_report(frame, {})
    gaps = {g.field: g.missing for g in report.field_gaps}
    assert gaps["status"] == 1 and gaps["reference"] == 1
    assert not any("completed" in w or "reference" in w for w in report.warnings)


def test_charts_render_with_and_without_gaps(tmp_path, make_txn):
    from moneyos.analytics import charts

    frame = transactions_frame([
        _t(make_txn, "2026-01-05", "-100.00", account="Bank", category="Food"),
        _t(make_txn, "2026-01-06", "500.00", TxnType.INCOME, account="Bank"),
        _t(make_txn, "2026-03-05", "-300.00", account="Bank", category="Rent"),
    ])
    coverage = build_coverage([("Bank", date(2026, 1, 1), date(2026, 1, 31)), ("Bank", date(2026, 3, 1), date(2026, 3, 20))])
    for cover in (None, coverage):
        monthly = cash_flow_series(frame, "month", date(2026, 1, 1), date(2026, 3, 31), cover)
        daily = cash_flow_series(frame, "day", date(2026, 1, 1), date(2026, 3, 31), cover)
        paths = [
            charts.monthly_in_out(monthly, "INR", tmp_path / "m.png"),
            charts.daily_spending(daily, "INR", tmp_path / "d.png"),
            charts.spending_by_category(spending_stats(frame).by_category, "INR", tmp_path / "c.png"),
        ]
        for path in paths:
            assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_stats_net_refunds_per_category(make_txn):
    rows = [
        _t(make_txn, "2026-01-05", "-500.00", category="Shopping"),
        _t(make_txn, "2026-01-06", "120.00", TxnType.REFUND, category="Shopping"),
        _t(make_txn, "2026-01-07", "80.00", TxnType.REFUND, category="Travel"),  # refund with no purchase
        _t(make_txn, "2026-01-08", "-300.00", category="Food"),
    ]
    by_category = spending_stats(transactions_frame(rows)).by_category
    assert by_category.loc["Shopping", ["total", "refunds", "net"]].tolist() == [50000, 12000, 38000]
    assert by_category.loc["Travel", ["count", "total", "refunds", "net"]].tolist() == [0, 0, 8000, -8000]
    assert list(by_category.index) == ["Shopping", "Food", "Travel"]  # by net, largest first
    assert by_category["share"].sum() == pytest.approx(1.0)


def test_month_over_month_is_after_refunds(make_txn):
    rows = [
        _t(make_txn, "2026-01-05", "-100.00", category="Shopping"),
        _t(make_txn, "2026-02-05", "-100.00", category="Shopping"),
        _t(make_txn, "2026-02-09", "60.00", TxnType.REFUND, category="Shopping"),
    ]
    mom = spending_stats(transactions_frame(rows)).month_over_month
    assert mom.loc["Shopping"].tolist() == [10000, 4000, -6000]
