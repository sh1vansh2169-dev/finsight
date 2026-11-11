"""Monthly category budgets and how much of each has been used.

Wording is deliberately neutral ("over the limit", not "overspent"): the app
reports, it does not judge.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

# A pace projection from only a few days of a month is mostly noise.
MIN_DAYS_FOR_PACE = 7


class BudgetState(StrEnum):
    ON_TRACK = "on_track"  # under 80% used
    CLOSE = "close"  # 80-100%
    OVER = "over"  # above the limit


@dataclass(frozen=True, slots=True)
class BudgetUse:
    category: str
    currency: str
    limit: Decimal
    spent: Decimal
    state: BudgetState
    percent_used: int
    # Estimate: spending so far scaled to the whole month. None when the
    # month is finished or fewer than MIN_DAYS_FOR_PACE days have passed.
    projected_month_total: Decimal | None

    @property
    def remaining(self) -> Decimal:
        return self.limit - self.spent

    def message(self) -> str:
        used = f"{self.percent_used}% of the {self.category} budget used"
        if self.state == BudgetState.OVER:
            return f"{used}; {-self.remaining:,.2f} {self.currency} over the limit."
        text = f"{used}; {self.remaining:,.2f} {self.currency} left."
        if self.projected_month_total is not None and self.projected_month_total > self.limit:
            text += (
                f" At the pace so far the month would end near {self.projected_month_total:,.2f} "
                f"{self.currency} (an estimate)."
            )
        return text


def budget_use(
    category: str,
    currency: str,
    limit: Decimal,
    spent: Decimal,
    month: tuple[int, int],
    as_of: date,
) -> BudgetUse:
    """Compare spending in ``month`` (year, month) with ``limit``, as known on ``as_of``."""
    if limit <= 0:
        raise ValueError("budget limit must be positive")
    # The state comes from exact amounts; the percentage is rounded for display
    # only (79.9% shows as 80% but is still on track).
    percent = int((spent / limit * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if spent > limit:
        state = BudgetState.OVER
    elif spent * 5 >= limit * 4:  # spent >= 80% of limit, without division
        state = BudgetState.CLOSE
    else:
        state = BudgetState.ON_TRACK

    year, number = month
    days_in_month = calendar.monthrange(year, number)[1]
    in_month = date(year, number, 1) <= as_of <= date(year, number, days_in_month)
    projected = None
    if in_month and as_of.day >= MIN_DAYS_FOR_PACE and as_of.day < days_in_month:
        projected = (spent / as_of.day * days_in_month).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return BudgetUse(category, currency, limit, spent, state, percent, projected)
