"""Which dates each account's imported statements cover.

A statement export proves what happened on an account over a period. Outside
that period MoneyOS knows nothing about the account, and "no transactions"
must not be read as "no spending". Coverage is estimated from each import as
the span from its first to its last transaction date; the real statement
period is usually a little longer, so coverage is slightly understated.

Accounts that only have manual entries (cash, for example) have no coverage:
there is no evidence of completeness for them at all.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd


@dataclass(frozen=True, slots=True)
class Interval:
    start: date
    end: date  # inclusive

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


@dataclass(frozen=True, slots=True)
class AccountCoverage:
    account: str
    intervals: tuple[Interval, ...]
    gaps: tuple[Interval, ...] = field(default=())  # between covered intervals

    @property
    def first(self) -> date:
        return self.intervals[0].start

    @property
    def last(self) -> date:
        return self.intervals[-1].end

    def covers(self, day: date) -> bool:
        return any(i.start <= day <= i.end for i in self.intervals)


def merge(intervals: Iterable[Interval]) -> tuple[Interval, ...]:
    """Merge overlapping or touching intervals."""
    merged: list[Interval] = []
    for interval in sorted(intervals, key=lambda i: i.start):
        if merged and interval.start <= merged[-1].end + timedelta(days=1):
            last = merged[-1]
            merged[-1] = Interval(last.start, max(last.end, interval.end))
        else:
            merged.append(interval)
    return tuple(merged)


def build_coverage(spans: Iterable[tuple[str, date, date]]) -> dict[str, AccountCoverage]:
    """``spans`` are (account, first date, last date), one per imported file and account."""
    by_account: dict[str, list[Interval]] = defaultdict(list)
    for account, start, end in spans:
        by_account[account].append(Interval(min(start, end), max(start, end)))
    coverage = {}
    for account, intervals in sorted(by_account.items()):
        merged = merge(intervals)
        gaps = tuple(
            Interval(a.end + timedelta(days=1), b.start - timedelta(days=1)) for a, b in zip(merged, merged[1:])
        )
        coverage[account] = AccountCoverage(account, merged, gaps)
    return coverage


def daily_coverage(coverage: dict[str, AccountCoverage], start: date, end: date) -> pd.Series:
    """Fraction (0..1) of statement-backed accounts covering each day."""
    days = pd.date_range(start, end, freq="D")
    if not coverage:
        return pd.Series(0.0, index=days, name="coverage")
    covered = pd.DataFrame(
        {name: [c.covers(d.date()) for d in days] for name, c in coverage.items()}, index=days
    )
    return covered.mean(axis=1).rename("coverage")
