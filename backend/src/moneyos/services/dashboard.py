"""Everything the Home screen needs for one month, in one call."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from moneyos.analytics.aggregate import cash_flow_series
from moneyos.db.tables import TransactionRecord
from moneyos.domain.budgets import BudgetUse
from moneyos.domain.summary import LedgerSummary
from moneyos.services import analytics, budgets, ledger, majra, review

# Dashboard sections that need modules not built yet. Listed so a client
# can say "not available yet" instead of showing an empty or zero value.
NOT_YET_AVAILABLE = {
    "forecast": "Spending forecasts are planned for Phase 6.",
    "upcoming_commitments": "Recurring bills and commitments are planned for Phase 7.",
}


@dataclass
class Dashboard:
    month: str  # YYYY-MM
    currency: str | None
    summary: LedgerSummary | None
    daily: pd.DataFrame
    monthly: pd.DataFrame  # trailing months, including this one
    recent: list[TransactionRecord]
    budgets: list[BudgetUse]
    warnings: list[str]
    open_duplicate_reviews: int
    # Your Money Majra position in this currency (None if you have none).
    majra: majra.MajraSummary | None = None
    not_yet_available: dict[str, str] = field(default_factory=lambda: dict(NOT_YET_AVAILABLE))


def latest_month(session: Session) -> tuple[int, int]:
    """The month of the newest recorded transaction (or this month if there are none)."""
    newest = session.scalar(
        select(func.max(TransactionRecord.occurred_on)).where(TransactionRecord.duplicate_of_id.is_(None))
    )
    newest = newest or date.today()
    return newest.year, newest.month


def _months_back(year: int, month: int, count: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) - (count - 1)
    return index // 12, index % 12 + 1


def build(
    session: Session,
    *,
    year: int | None = None,
    month: int | None = None,
    currency: str | None = None,
    trailing_months: int = 6,
    as_of: date | None = None,
) -> Dashboard:
    if year is None or month is None:
        year, month = latest_month(session)
    currency = analytics.resolve_currency(session, currency)
    start, end = budgets.month_bounds(year, month)
    period = f"{year:04d}-{month:02d}"

    month_filter = ledger.TransactionFilter(start=start, end=end, currency=currency)
    summary = ledger.summarize_ledger(session, month_filter).get(currency) if currency else None

    cover = analytics.coverage(session)
    month_frame = analytics.ledger_frame(session, currency, start, end)
    daily = cash_flow_series(month_frame, "day", start, end, cover) if currency else pd.DataFrame()

    trail_start = date(*_months_back(year, month, trailing_months), 1)
    trail_frame = analytics.ledger_frame(session, currency, trail_start, end)
    monthly = cash_flow_series(trail_frame, "month", trail_start, end, cover) if currency else pd.DataFrame()

    recent, _ = ledger.list_transactions(session, ledger.TransactionFilter(currency=currency, end=end), limit=10)
    uses = [u for u in budgets.utilisation(session, year, month, as_of) if u.currency == currency]

    warnings = list(summary.quality.warnings()) if summary else []
    if not daily.empty and (daily["coverage"] < 1).any():
        uncovered = int((daily["coverage"] == 0).sum())
        partial = int(((daily["coverage"] > 0) & (daily["coverage"] < 1)).sum())
        if uncovered:
            warnings.append(f"No statement covers {uncovered} day(s) of {period}; spending on those days is unknown.")
        if partial:
            warnings.append(f"Only some accounts have statements for {partial} day(s) of {period}.")
    pending = review.count_open(session)
    if pending:
        warnings.append(f"{pending} possible duplicate pair(s) await review; totals may count them twice.")

    return Dashboard(
        month=period,
        currency=currency,
        summary=summary,
        daily=daily,
        monthly=monthly,
        recent=recent,
        budgets=uses,
        warnings=warnings,
        open_duplicate_reviews=pending,
        majra=next((s for s in majra.summary(session) if s.currency == currency), None),
    )
