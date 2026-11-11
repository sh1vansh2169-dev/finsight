"""A reproducible Markdown analytics report with PNG charts."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from moneyos.analytics import charts
from moneyos.analytics.frame import to_money
from moneyos.domain.synthetic import SAMPLE_MARKER
from moneyos.services import analytics, ledger


def _money(minor, currency: str) -> str:
    if minor is None or pd.isna(minor):
        return "unknown"
    value = Decimal(str(minor)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return f"{to_money(int(value), currency):,.2f}"


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def write_report(session: Session, out: Path, *, currency: str | None = None, sample: bool = False) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    currency = analytics.resolve_currency(session, currency)
    lines = ["# MoneyOS analytics report", ""]
    if sample:
        lines += [f"> **{SAMPLE_MARKER}**", ""]
    lines += [f"Generated {date.today():%d %b %Y}. Recorded transactions only; these totals are not a bank balance.", ""]
    if currency is None:
        lines += ["No transactions recorded yet."]
        path = out / "report.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    (summary,) = ledger.summarize_ledger(session, ledger.TransactionFilter(currency=currency)).values()
    lines += [
        f"## Summary ({currency}, {summary.start_date:%d %b %Y} to {summary.end_date:%d %b %Y})", "",
        *_table(["", "Amount"], [
            ["Money in", f"{summary.inflow:,.2f}"],
            ["of which income", f"{summary.income:,.2f}"],
            ["of which unclassified", f"{summary.unclassified_inflow:,.2f}"],
            ["Money out", f"{summary.outflow:,.2f}"],
            ["of which purchases", f"{summary.expenses:,.2f}"],
            ["of which unclassified", f"{summary.unclassified_outflow:,.2f}"],
            ["Net cash flow", f"{summary.net_cash_flow:,.2f}"],
            ["Spending after refunds", f"{summary.spending:,.2f}"],
        ]),
        "",
    ]

    quality = analytics.quality(session, currency)
    lines += ["## Data quality", ""]
    lines += [f"- {w}" for w in quality.warnings] or ["- No issues found."]
    lines += ["", "### Missing details", ""]
    lines += _table(
        ["Detail", "Missing", "Of", "Meaning"],
        [[g.field, str(g.missing), str(g.total), g.meaning] for g in quality.field_gaps],
    )
    lines += ["", "### Statement coverage", ""]
    lines += _table(
        ["Account", "Covered", "Gaps"],
        [
            [c.account, ", ".join(f"{i.start:%d %b} - {i.end:%d %b %Y}" for i in c.intervals),
             ", ".join(f"{g.days} days from {g.start:%d %b %Y}" for g in c.gaps) or "none"]
            for c in quality.coverage.values()
        ] + [[a, "no statements (manual entries only)", "unknown"] for a in quality.uncovered_accounts],
    )
    lines += ["", "### How transaction types were decided", ""]
    lines += _table(["Decided by", "Transactions"], [[k, str(v)] for k, v in quality.type_basis.items() if v])

    _, monthly = analytics.cash_flow(session, "month", currency, None, None)
    _, daily = analytics.cash_flow(session, "day", currency, None, None)
    stats = analytics.spending(session, currency, None, None)
    charts.monthly_in_out(monthly, currency, out / "monthly_in_out.png")
    charts.daily_spending(daily, currency, out / "daily_spending.png")
    lines += ["", "## Over time", "", "![Income and spending by month](monthly_in_out.png)", "",
              "![Daily spending](daily_spending.png)", ""]

    if stats and stats.count:
        charts.spending_by_category(stats.by_category, currency, out / "spending_by_category.png")
        lines += [
            "## Spending", "", "![Spending by category](spending_by_category.png)", "",
            f"{stats.count} payments. Typical (median) payment {_money(stats.median_minor, currency)}; "
            f"average {_money(stats.mean_minor, currency)}; 9 in 10 payments were at most "
            f"{_money(stats.p90_minor, currency)}.", "",
        ]
        lines += _table(
            ["Category", "Payments", "Purchases", "Refunds", "Spending", "Share"],
            [[name, str(int(r["count"])), _money(r["total"], currency), _money(r["refunds"], currency),
              _money(r["net"], currency), f"{r['share']:.1%}"]
             for name, r in stats.by_category.iterrows()],
        )
        lines += ["", "### By day of the week (days with statement coverage only)", ""]
        lines += _table(
            ["Day", "Covered days", "Average per day"],
            [[name, str(int(r["covered_days"])), _money(r["average_per_day"], currency)]
             for name, r in stats.by_weekday.iterrows()],
        )
        if months := stats.month_over_month.attrs.get("months"):
            lines += ["", f"### Change from {months[0]} to {months[1]}", ""]
            lines += _table(
                ["Category", months[0], months[1], "Change"],
                [[name, _money(r["previous"], currency), _money(r["latest"], currency), _money(r["change"], currency)]
                 for name, r in stats.month_over_month.iterrows()],
            )

    lines += [
        "", "## What this report cannot tell you", "",
        "- Spending on days or accounts with no imported statement (shown as unknown, not zero).",
        "- Cash or other payments never recorded in MoneyOS.",
        "- Whether open duplicate pairs are double-counted until they are reviewed.",
        "- Anything about the future: these are descriptions of the past, not forecasts.",
    ]
    path = out / "report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
