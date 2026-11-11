"""Routes and response models for analytics, budgets and the dashboard.

Values that are unknown (periods no statement covers, sections not built
yet) are ``null`` in JSON, never 0.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

import pandas as pd
from fastapi import APIRouter, Query, status
from pydantic import BaseModel, ConfigDict, Field

from moneyos.analytics.frame import to_money
from moneyos.api.routes import SessionDep, SettingsDep
from moneyos.api.schemas import RECORDED_TOTALS_NOTE, TransactionOut
from moneyos.config import DataMode
from moneyos.domain.budgets import BudgetUse
from moneyos.domain.money import from_minor
from moneyos.domain.report import summary_dict
from moneyos.services import analytics, budgets, dashboard
from moneyos.services.errors import InvalidRequestError

router = APIRouter()
COVERAGE_NOTE = (
    "coverage is the share of statement-backed accounts covering the period (0-1). "
    "Periods with coverage 0 have null amounts: nothing is known about them."
)


class SeriesPointOut(BaseModel):
    period: str
    start: date
    end: date
    income: Decimal | None
    expenses: Decimal | None
    inflow: Decimal | None
    outflow: Decimal | None
    net_cash_flow: Decimal | None
    coverage: float


class CashFlowOut(BaseModel):
    currency: str | None
    granularity: str
    note: str = COVERAGE_NOTE
    points: list[SeriesPointOut]


class BudgetIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    category: str = Field(min_length=1, max_length=100)
    currency: str = Field(default="INR", pattern=r"^[A-Za-z]{3}$")
    monthly_limit: Decimal = Field(gt=0, max_digits=15, decimal_places=2)


class BudgetOut(BaseModel):
    id: int
    category: str
    currency: str
    monthly_limit: Decimal


class BudgetUseOut(BaseModel):
    category: str
    currency: str
    limit: Decimal
    spent: Decimal
    remaining: Decimal
    percent_used: int
    state: Literal["on_track", "close", "over"]
    projected_month_total: Decimal | None = Field(
        description="Estimate: spending so far scaled to the whole month. Null when not meaningful."
    )
    message: str

    @classmethod
    def from_use(cls, u: BudgetUse) -> BudgetUseOut:
        return cls(
            category=u.category, currency=u.currency, limit=u.limit, spent=u.spent, remaining=u.remaining,
            percent_used=u.percent_used, state=u.state.value, projected_month_total=u.projected_month_total,
            message=u.message(),
        )


class DashboardOut(BaseModel):
    month: str
    currency: str | None
    sample_data: bool
    note: str = RECORDED_TOTALS_NOTE
    summary: dict[str, Any] | None
    daily: list[SeriesPointOut]
    monthly: list[SeriesPointOut]
    recent_transactions: list[TransactionOut]
    budgets: list[BudgetUseOut]
    warnings: list[str]
    open_duplicate_reviews: int
    not_yet_available: dict[str, str]


def _points(series: pd.DataFrame, currency: str | None) -> list[SeriesPointOut]:
    if series.empty or currency is None:
        return []
    return [
        SeriesPointOut(
            period=str(period),
            start=period.start_time.date(),
            end=period.end_time.date(),
            coverage=round(float(row["coverage"]), 4),
            **{k: to_money(row[k], currency) for k in ("income", "expenses", "inflow", "outflow", "net_cash_flow")},
        )
        for period, row in series.iterrows()
    ]


def _month(value: str | None) -> tuple[int | None, int | None]:
    if value is None:
        return None, None
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
        raise InvalidRequestError("month must look like 2026-03")
    year, month = value.split("-")
    return int(year), int(month)


CurrencyQuery = Annotated[str | None, Query(pattern=r"^[A-Za-z]{3}$")]
MonthQuery = Annotated[str | None, Query(description="YYYY-MM; defaults to the month of the newest transaction")]


@router.get("/dashboard", response_model=DashboardOut, tags=["dashboard"])
def get_dashboard(session: SessionDep, settings: SettingsDep, month: MonthQuery = None, currency: CurrencyQuery = None):
    """One month at a glance. Sections that are not built yet are listed in ``not_yet_available``."""
    year, number = _month(month)
    d = dashboard.build(session, year=year, month=number, currency=currency)
    return DashboardOut(
        month=d.month,
        currency=d.currency,
        sample_data=settings.data_mode == DataMode.SAMPLE,
        summary=summary_dict(d.summary) if d.summary else None,
        daily=_points(d.daily, d.currency),
        monthly=_points(d.monthly, d.currency),
        recent_transactions=[TransactionOut.from_record(r) for r in d.recent],
        budgets=[BudgetUseOut.from_use(u) for u in d.budgets],
        warnings=d.warnings,
        open_duplicate_reviews=d.open_duplicate_reviews,
        not_yet_available=d.not_yet_available,
    )


@router.get("/analytics/cash-flow", response_model=CashFlowOut, tags=["analytics"])
def cash_flow(
    session: SessionDep,
    granularity: Literal["day", "week", "month"] = "month",
    start: date | None = None,
    end: date | None = None,
    currency: CurrencyQuery = None,
):
    """Income, spending and net cash flow per day, week (Mon-Sun) or month, with coverage."""
    currency, series = analytics.cash_flow(session, granularity, currency, start, end)
    return CashFlowOut(currency=currency, granularity=granularity, points=_points(series, currency))


@router.get("/analytics/spending", tags=["analytics"])
def spending(
    session: SessionDep, start: date | None = None, end: date | None = None, currency: CurrencyQuery = None
) -> dict[str, Any]:
    """Descriptive statistics of past spending. Describes; does not predict."""
    stats = analytics.spending(session, currency, start, end)
    if stats is None:
        return {"currency": None, "count": 0}
    c = stats.currency

    def money(value):
        return str(to_money(value, c)) if value is not None and not pd.isna(value) else None

    def money_round(value):
        # Means and medians can fall between paise; round half up for display.
        if value is None or pd.isna(value):
            return None
        return str(from_minor(int(Decimal(str(value)).quantize(Decimal(1), rounding="ROUND_HALF_UP")), c))

    return {
        "currency": c,
        "count": stats.count,
        "total": money(stats.total_minor),
        "mean": money_round(stats.mean_minor),
        "median": money_round(stats.median_minor),
        "standard_deviation": money_round(stats.std_minor),
        "p90": money_round(stats.p90_minor),
        "by_category": [
            {"category": name, "count": int(r["count"]), "total": money(r["total"]),
             "median": money_round(r["median"]), "share": round(float(r["share"]), 4)}
            for name, r in stats.by_category.iterrows()
        ],
        "top_merchants": [
            {"merchant": name, "count": int(r["count"]), "total": money(r["total"])}
            for name, r in stats.top_merchants.iterrows()
        ],
        "by_weekday": [
            {"weekday": name, "total": money(r["total"]), "covered_days": int(r["covered_days"]),
             "average_per_day": money_round(r["average_per_day"])}
            for name, r in stats.by_weekday.iterrows()
        ],
        "month_over_month": {
            "months": list(stats.month_over_month.attrs.get("months", ())),
            "categories": [
                {"category": name, "previous": money(r["previous"]), "latest": money(r["latest"]),
                 "change": money(r["change"])}
                for name, r in stats.month_over_month.iterrows()
            ],
        },
    }


@router.get("/analytics/quality", tags=["analytics"])
def quality(session: SessionDep, currency: CurrencyQuery = None) -> dict[str, Any]:
    """What is missing, inferred, uncertain or not covered by any statement."""
    report = analytics.quality(session, analytics.resolve_currency(session, currency))
    return {
        "transactions": report.transactions,
        "fields": [
            {"field": g.field, "missing": g.missing, "total": g.total, "share": round(g.share, 4), "meaning": g.meaning}
            for g in report.field_gaps
        ],
        "type_decided_by": report.type_basis,
        "coverage": [
            {"account": c.account, "first": c.first, "last": c.last,
             "covered": [{"start": i.start, "end": i.end} for i in c.intervals],
             "gaps": [{"start": g.start, "end": g.end, "days": g.days} for g in c.gaps]}
            for c in report.coverage.values()
        ],
        "accounts_without_statements": list(report.uncovered_accounts),
        "rejected_rows": report.rejected_rows,
        "confirmed_duplicates": report.confirmed_duplicates,
        "open_duplicate_reviews": report.open_duplicate_reviews,
        "warnings": list(report.warnings),
    }


# ------------------------------------------------------------------ budgets


@router.get("/budgets", response_model=list[BudgetOut], tags=["budgets"])
def list_budgets(session: SessionDep):
    return [
        BudgetOut(id=b.id, category=b.category, currency=b.currency, monthly_limit=from_minor(b.limit_minor, b.currency))
        for b in budgets.list_budgets(session)
    ]


@router.put("/budgets", response_model=BudgetOut, tags=["budgets"])
def set_budget(body: BudgetIn, session: SessionDep):
    """Create a monthly limit for a category, or replace the existing one."""
    b = budgets.set_budget(session, body.category, body.currency, body.monthly_limit)
    return BudgetOut(id=b.id, category=b.category, currency=b.currency, monthly_limit=from_minor(b.limit_minor, b.currency))


@router.delete("/budgets/{budget_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["budgets"])
def delete_budget(budget_id: int, session: SessionDep) -> None:
    budgets.delete_budget(session, budget_id)


@router.get("/budgets/usage", response_model=list[BudgetUseOut], tags=["budgets"])
def budget_usage(session: SessionDep, month: MonthQuery = None):
    year, number = _month(month)
    if year is None:
        year, number = dashboard.latest_month(session)
    return [BudgetUseOut.from_use(u) for u in budgets.utilisation(session, year, number)]
