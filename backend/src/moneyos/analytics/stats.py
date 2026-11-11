"""Descriptive statistics of spending. Describes the past; predicts nothing."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from moneyos.analytics.frame import counted, one_currency
from moneyos.domain.cleaning import normalize_key
from moneyos.domain.models import TxnType

_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@dataclass(frozen=True, slots=True)
class SpendingStats:
    currency: str
    count: int
    total_minor: int
    mean_minor: float | None
    median_minor: float | None
    std_minor: float | None  # sample standard deviation (n - 1)
    p90_minor: float | None
    by_category: pd.DataFrame  # count, total, mean, median, share; largest first
    top_merchants: pd.DataFrame  # count, total; largest first
    by_weekday: pd.DataFrame  # total and average per *covered* weekday
    month_over_month: pd.DataFrame  # per category: previous, latest, change


def expenses_only(frame: pd.DataFrame) -> pd.DataFrame:
    rows = counted(frame)
    rows = rows[rows["txn_type"] == TxnType.EXPENSE.value].copy()
    rows["spend_minor"] = -rows["amount_minor"]
    return rows


def spending_stats(
    frame: pd.DataFrame, *, covered_days: pd.DatetimeIndex | None = None, top_n: int = 5
) -> SpendingStats:
    """Statistics over expense transactions.

    ``covered_days`` (days with statement coverage) is used for the weekday
    average, so uncovered days do not count as zero-spending days. Without
    it, every day from the first to the last expense counts.
    """
    currency = one_currency(frame)
    spend = expenses_only(frame)
    values = spend["spend_minor"]
    n = len(values)

    by_category = (
        spend.groupby("category")["spend_minor"]
        .agg(count="count", total="sum", mean="mean", median="median")
        .sort_values(["total", "count"], ascending=False)
    )
    by_category["share"] = by_category["total"] / values.sum() if n else 0.0

    merchants = spend.assign(merchant=spend["description"].map(normalize_key))
    top_merchants = (
        merchants.groupby("merchant")["spend_minor"]
        .agg(count="count", total="sum")
        .sort_values(["total", "count"], ascending=False)
        .head(top_n)
    )

    if covered_days is None and n:
        covered_days = pd.date_range(spend["date"].min(), spend["date"].max(), freq="D")
    covered_days = covered_days if covered_days is not None else pd.DatetimeIndex([])
    weekday_totals = spend.groupby(spend["date"].dt.day_of_week)["spend_minor"].sum()
    weekday_counts = pd.Series(covered_days.day_of_week).value_counts()
    by_weekday = pd.DataFrame(
        {
            "total": weekday_totals.reindex(range(7), fill_value=0),
            "covered_days": weekday_counts.reindex(range(7), fill_value=0),
        }
    )
    by_weekday["average_per_day"] = by_weekday["total"] / by_weekday["covered_days"].replace(0, np.nan)
    by_weekday.index = list(_WEEKDAYS)

    monthly = spend.groupby([spend["date"].dt.to_period("M"), "category"])["spend_minor"].sum().unstack(fill_value=0)
    if len(monthly) >= 2:
        previous, latest = monthly.iloc[-2], monthly.iloc[-1]
        month_over_month = pd.DataFrame({"previous": previous, "latest": latest})
        month_over_month["change"] = month_over_month["latest"] - month_over_month["previous"]
        month_over_month.attrs["months"] = (str(monthly.index[-2]), str(monthly.index[-1]))
        month_over_month = month_over_month.sort_values("change", ascending=False)
    else:
        month_over_month = pd.DataFrame(columns=["previous", "latest", "change"])

    return SpendingStats(
        currency=currency,
        count=n,
        total_minor=int(values.sum()),
        mean_minor=float(values.mean()) if n else None,
        median_minor=float(values.median()) if n else None,
        std_minor=float(values.std(ddof=1)) if n > 1 else None,
        p90_minor=float(values.quantile(0.9)) if n else None,
        by_category=by_category,
        top_merchants=top_merchants,
        by_weekday=by_weekday,
        month_over_month=month_over_month,
    )
