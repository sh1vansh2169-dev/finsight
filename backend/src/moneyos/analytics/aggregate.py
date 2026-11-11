"""Daily / weekly / monthly cash-flow series, coverage-aware.

Each period gets income, expenses (purchases), refunds, spending
(purchases minus refunds), inflow, outflow and net cash flow (in minor
units), plus ``coverage``: the average fraction of statement-backed
accounts covering the period's days. Periods with zero coverage get missing
values (NaN) rather than zero, because nothing is known about them; partly
covered periods keep their observed totals, which may be understated.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

import numpy as np
import pandas as pd

from moneyos.analytics.coverage import AccountCoverage, daily_coverage
from moneyos.analytics.frame import counted, one_currency
from moneyos.domain.models import TxnType

Granularity = Literal["day", "week", "month"]
# Weeks start on Monday (ISO); months are calendar months.
_PERIOD = {"day": "D", "week": "W-SUN", "month": "M"}
VALUE_COLUMNS = ["income", "expenses", "refunds", "spending", "inflow", "outflow", "net_cash_flow"]


def _daily_values(frame: pd.DataFrame, days: pd.DatetimeIndex) -> pd.DataFrame:
    rows = counted(frame)
    amount = rows["amount_minor"]
    parts = pd.DataFrame(
        {
            "date": rows["date"],
            "income": amount.where(rows["txn_type"] == TxnType.INCOME.value, 0),
            "expenses": (-amount).where(rows["txn_type"] == TxnType.EXPENSE.value, 0),
            "refunds": amount.where(rows["txn_type"] == TxnType.REFUND.value, 0),
            "inflow": amount.clip(lower=0),
            "outflow": (-amount).clip(lower=0),
            "net_cash_flow": amount,
        }
    )
    parts["spending"] = parts["expenses"] - parts["refunds"]
    daily = parts.groupby("date").sum()
    return daily.reindex(days, fill_value=0).astype("int64")[VALUE_COLUMNS]


def cash_flow_series(
    frame: pd.DataFrame,
    granularity: Granularity,
    start: date,
    end: date,
    coverage: dict[str, AccountCoverage] | None = None,
) -> pd.DataFrame:
    """One row per period between ``start`` and ``end`` (inclusive).

    Without ``coverage`` every day is treated as observed (coverage 1.0).
    """
    one_currency(frame)
    days = pd.date_range(start, end, freq="D")
    daily = _daily_values(frame, days)
    daily["coverage"] = 1.0 if coverage is None else daily_coverage(coverage, start, end).to_numpy()

    period = days.to_period(_PERIOD[granularity])
    grouped = daily.groupby(period)
    series = grouped[VALUE_COLUMNS].sum()
    series["coverage"] = grouped["coverage"].mean()
    series["days"] = grouped.size()

    unobserved = series["coverage"] == 0
    series[VALUE_COLUMNS] = series[VALUE_COLUMNS].astype("float64")
    series.loc[unobserved, VALUE_COLUMNS] = np.nan
    series.index.name = "period"
    return series
