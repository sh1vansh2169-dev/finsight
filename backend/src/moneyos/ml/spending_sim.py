"""Simulated daily spending histories for forecasting experiments.

**Synthetic.** Each profile is a made-up person with their own parameters.
Daily spending = scheduled commitments + everyday spending + rare one-offs:

* commitments: rent (monthly), a utility bill (monthly, amount varies),
  1-3 subscriptions. Their *expected* amounts and dates are known in
  advance and stored separately (``scheduled``), as a user would record
  upcoming bills.
* everyday spending: a Poisson number of purchases per day with log-normal
  amounts, scaled by weekday, days since payday, festive season (Oct-Nov,
  and December) and a slow linear trend.
* one-offs: on about 1 day in 60, a large purchase nobody could predict.

Forecasting results on this data show which methods capture these
patterns; they say nothing about how real people spend.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class Profile:
    seed: int
    salary_day: int
    rent: float
    rent_day: int
    utility: float
    subscriptions: tuple[tuple[int, float], ...]  # (day of month, amount)
    purchases_per_day: float
    purchase_log_mean: float
    purchase_log_sd: float
    weekend_factor: float
    payday_boost: float
    festive_factor: float
    yearly_growth: float
    one_off_rate: float
    one_off_log_mean: float


def make_profile(seed: int) -> Profile:
    rng = np.random.default_rng(seed)
    return Profile(
        seed=seed,
        salary_day=int(rng.choice([1, 5, 7, 10, 28])),
        rent=float(rng.choice([0, 9000, 12000, 15000, 18000, 22000, 30000])),
        rent_day=int(rng.integers(1, 6)),
        utility=float(rng.uniform(800, 3000)),
        subscriptions=tuple((int(rng.integers(1, 28)), float(rng.choice([149, 199, 299, 499, 649])))
                            for _ in range(int(rng.integers(1, 4)))),
        purchases_per_day=float(rng.uniform(1.0, 4.0)),
        purchase_log_mean=float(rng.uniform(5.0, 6.3)),  # median purchase about 150-550
        purchase_log_sd=float(rng.uniform(0.6, 1.0)),
        weekend_factor=float(rng.uniform(1.1, 1.7)),
        payday_boost=float(rng.uniform(0.0, 0.6)),
        festive_factor=float(rng.uniform(1.0, 1.4)),
        yearly_growth=float(rng.uniform(-0.05, 0.15)),
        one_off_rate=float(rng.uniform(1 / 120, 1 / 40)),
        one_off_log_mean=float(rng.uniform(8.5, 10.0)),  # about 5,000-22,000
    )


def _clamp_day(year: int, month: int, day: int) -> int:
    return min(day, calendar.monthrange(year, month)[1])


def simulate(profile: Profile, start: date = date(2024, 1, 1), days: int = 730) -> pd.DataFrame:
    """Columns: scheduled (expected commitments), commitments (actual), everyday,
    one_off, total. Index: daily dates. Amounts in rupees (float; this is
    simulation input, not ledger money)."""
    rng = np.random.default_rng(profile.seed + 10_000)
    index = pd.date_range(start, periods=days, freq="D")
    scheduled = np.zeros(days)
    actual = np.zeros(days)
    for i, d in enumerate(index):
        y, m, dom = d.year, d.month, d.day
        if profile.rent and dom == _clamp_day(y, m, profile.rent_day):
            scheduled[i] += profile.rent
            actual[i] += profile.rent
        if dom == _clamp_day(y, m, 10):
            scheduled[i] += profile.utility
            actual[i] += profile.utility * rng.uniform(0.8, 1.25)  # the bill varies
        for sub_day, amount in profile.subscriptions:
            if dom == _clamp_day(y, m, sub_day):
                scheduled[i] += amount
                actual[i] += amount

    t = np.arange(days)
    weekday = index.day_of_week.to_numpy()
    rate = np.full(days, profile.purchases_per_day)
    rate *= np.where(weekday >= 5, profile.weekend_factor, 1.0)
    days_since_pay = np.array([(d.day - profile.salary_day) % calendar.monthrange(d.year, d.month)[1] for d in index])
    rate *= 1 + profile.payday_boost * np.exp(-days_since_pay / 5)
    month = index.month.to_numpy()
    rate *= np.where(np.isin(month, [10, 11]), profile.festive_factor, np.where(month == 12, 1 + (profile.festive_factor - 1) / 2, 1.0))
    rate *= 1 + profile.yearly_growth * t / 365

    counts = rng.poisson(rate)
    everyday = np.array([rng.lognormal(profile.purchase_log_mean, profile.purchase_log_sd, n).sum() for n in counts])
    one_off = np.where(rng.random(days) < profile.one_off_rate, rng.lognormal(profile.one_off_log_mean, 0.5, days), 0.0)

    frame = pd.DataFrame(
        {"scheduled": scheduled, "commitments": actual, "everyday": everyday, "one_off": one_off}, index=index
    )
    frame["total"] = frame["commitments"] + frame["everyday"] + frame["one_off"]
    return frame.round(2)
