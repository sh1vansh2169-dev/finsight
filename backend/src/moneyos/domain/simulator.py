"""What-if simulator ("financial digital twin"): deterministic projections.

A projection of the next H days combines:

* commitments: known payments and income on their scheduled dates (facts
  the user confirmed or entered; amounts that vary use their typical value,
  with their upper end in the cautious figure);
* everyday spending: the historical average per day (experiment E2 found
  no model better than this baseline), with a range from the 10th and 90th
  percentiles of the user's own past H-day spending;
* scenario changes (a purchase, a new bill, a category cut, ...).

Money owed *to* you is never part of the estimate: it is reported
separately as "if repaid". Money you owe is reported as "if you repay".
A balance is projected only from a balance the user states; FinSight never
claims to know one. Everything is recalculated from inputs, so the same
inputs always give the same answer.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from moneyos.domain.dates import add_months

CENT = Decimal("0.01")
MIN_HISTORY_DAYS = 28


def _money(value) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def schedule(anchor: date, cadence: str, start: date, end: date, until: date | None = None) -> list[date]:
    """Dates of a commitment within [start, end], following its cadence from ``anchor``."""
    stop = min(end, until) if until else end
    if cadence == "once":
        return [anchor] if start <= anchor <= stop else []
    step_months = {"monthly": 1, "quarterly": 3, "yearly": 12}.get(cadence)
    dates, i = [], 0
    # Walk back from the anchor to before the window, then forward through it.
    while True:
        day = add_months(anchor, -i * step_months) if step_months else anchor - timedelta(days=7 * i)
        if day < start:
            break
        i += 1
    i = -i
    while True:
        day = add_months(anchor, i * step_months) if step_months else anchor + timedelta(days=7 * i)
        if day > stop:
            break
        if day >= start:
            dates.append(day)
        i += 1
    return dates


@dataclass(frozen=True, slots=True)
class Occurrence:
    on: date
    name: str
    amount: Decimal  # signed: positive money in, negative money out
    high: Decimal | None = None  # for varying payments: the largest likely outflow (positive)


@dataclass(frozen=True, slots=True)
class Everyday:
    """Everyday spending (commitments excluded) over the horizon, as positive amounts."""

    mid: Decimal
    low: Decimal | None
    high: Decimal | None
    per_day: Decimal
    history_days: int
    category_shares: dict[str, float] = field(default_factory=dict)


def everyday_from_history(daily: Sequence[Decimal], horizon: int, category_totals: dict[str, Decimal]) -> Everyday:
    """Historical-average estimate with a percentile range from past H-day windows."""
    days = len(daily)
    if days == 0:
        return Everyday(Decimal(0), None, None, Decimal(0), 0)
    per_day = sum(daily, Decimal(0)) / days
    windows = [sum(daily[i: i + horizon], Decimal(0)) for i in range(days - horizon + 1)] if days >= 2 * horizon else []
    low = high = None
    if len(windows) >= 2:
        q = statistics.quantiles([float(w) for w in windows], n=10, method="inclusive")
        low, high = _money(q[0]), _money(q[-1])
    total = sum(category_totals.values(), Decimal(0))
    shares = {c: float(v / total) for c, v in category_totals.items()} if total > 0 else {}
    return Everyday(_money(per_day * horizon), low, high, _money(per_day), days, shares)


@dataclass(frozen=True, slots=True)
class Inputs:
    start: date  # the projection covers the days after this date
    horizon: int
    currency: str
    occurrences: tuple[Occurrence, ...]
    everyday: Everyday
    receivables: tuple[tuple[str, Decimal], ...] = ()  # owed to you: (who, amount)
    payables: tuple[tuple[str, Decimal], ...] = ()  # you owe: (to whom, amount)
    starting_balance: Decimal | None = None
    changes: tuple[str, ...] = ()  # scenario changes applied, in words

    @property
    def end(self) -> date:
        return self.start + timedelta(days=self.horizon)


@dataclass(frozen=True, slots=True)
class Projection:
    start: date
    end: date
    currency: str
    commitments_in: Decimal
    commitments_out: Decimal
    commitments_out_high: Decimal
    everyday: Everyday
    net_change: Decimal  # central estimate
    net_change_low: Decimal | None  # cautious
    net_change_high: Decimal | None  # hopeful
    if_repaid: Decimal  # owed to you: not included above
    if_you_repay: Decimal  # you owe: not included above
    reserve_for_commitments: Decimal
    balance: Decimal | None  # only from a balance the user stated
    balance_low: Decimal | None
    balance_high: Decimal | None
    path: tuple[tuple[date, Decimal], ...]  # cumulative central change per day
    occurrences: tuple[Occurrence, ...]
    assumptions: tuple[str, ...]
    changes: tuple[str, ...]


def project(inputs: Inputs) -> Projection:
    window = [o for o in inputs.occurrences if inputs.start < o.on <= inputs.end]
    c_in = sum((o.amount for o in window if o.amount > 0), Decimal(0))
    c_out = -sum((o.amount for o in window if o.amount < 0), Decimal(0))
    c_out_high = sum((o.high if o.high is not None else -o.amount for o in window if o.amount < 0), Decimal(0))
    e = inputs.everyday
    central = c_in - c_out - e.mid
    low = c_in - c_out_high - e.high if e.high is not None else None
    high = c_in - c_out - e.low if e.low is not None else None

    by_day: dict[date, Decimal] = {}
    for o in window:
        by_day[o.on] = by_day.get(o.on, Decimal(0)) + o.amount
    path, running = [], Decimal(0)
    for i in range(1, inputs.horizon + 1):
        day = inputs.start + timedelta(days=i)
        running += by_day.get(day, Decimal(0)) - e.mid / inputs.horizon
        path.append((day, _money(running)))

    sb = inputs.starting_balance
    assumptions = [
        f"Everyday spending is the average of your last {e.history_days} recorded days "
        f"({e.per_day:,.2f} {inputs.currency} a day); it is an estimate, not a forecast you can rely on.",
        "Commitments are the ones you confirmed or added; their payments are left out of everyday spending, "
        "so nothing is counted twice.",
        "Income that is not a commitment (gifts, irregular work) is not included.",
        "Money others owe you is not included: see 'if repaid'.",
        "Money you owe others is not included: see 'if you repay'.",
    ]
    if e.high is None:
        assumptions.append(
            f"Less than {2 * inputs.horizon} days of history, so no range can be given for everyday spending."
        )
    if sb is None:
        assumptions.append("No current balance was given, so only the change over the period is shown.")
    else:
        assumptions.append("The starting balance is the one you entered; FinSight does not know your bank balance.")

    return Projection(
        start=inputs.start, end=inputs.end, currency=inputs.currency,
        commitments_in=_money(c_in), commitments_out=_money(c_out), commitments_out_high=_money(c_out_high),
        everyday=e, net_change=_money(central),
        net_change_low=_money(low) if low is not None else None,
        net_change_high=_money(high) if high is not None else None,
        if_repaid=_money(sum((a for _, a in inputs.receivables), Decimal(0))),
        if_you_repay=_money(sum((a for _, a in inputs.payables), Decimal(0))),
        reserve_for_commitments=_money(c_out_high),
        balance=_money(sb + central) if sb is not None else None,
        balance_low=_money(sb + low) if sb is not None and low is not None else None,
        balance_high=_money(sb + high) if sb is not None and high is not None else None,
        path=tuple(path), occurrences=tuple(sorted(window, key=lambda o: (o.on, o.name))),
        assumptions=tuple(assumptions), changes=inputs.changes,
    )


# ---------------------------------------------------------------- scenarios


def purchase(inputs: Inputs, amount: Decimal, on: date, description: str = "Purchase") -> Inputs:
    if amount <= 0:
        raise ValueError("amount must be positive")
    if not inputs.start < on <= inputs.end:
        # Outside the window it would change nothing, while being listed as a change.
        raise ValueError(f"the date must be between {inputs.start + timedelta(days=1):%d %b %Y} and {inputs.end:%d %b %Y}")
    return replace(inputs, occurrences=inputs.occurrences + (Occurrence(on, description, -amount),),
                   changes=inputs.changes + (f"One-off: {description}, {amount:,.2f} on {on:%d %b}",))


def add_recurring(inputs: Inputs, name: str, amount: Decimal, cadence: str, first_due: date,
                  money_in: bool = False) -> Inputs:
    if amount <= 0:
        raise ValueError("amount must be positive")
    signed = amount if money_in else -amount
    new = tuple(Occurrence(d, name, signed) for d in schedule(first_due, cadence, first_due, inputs.end)
                if d > inputs.start)
    if not new:
        raise ValueError(f"no payment of it would fall between {inputs.start + timedelta(days=1):%d %b %Y} "
                         f"and {inputs.end:%d %b %Y}")
    return replace(inputs, occurrences=inputs.occurrences + new,
                   changes=inputs.changes + (f"New {cadence} {'income' if money_in else 'payment'}: {name}, "
                                             f"{amount:,.2f} from {first_due:%d %b}",))


def reduce_category(inputs: Inputs, category: str, percent: Decimal) -> Inputs:
    if not 0 < percent <= 100:
        raise ValueError("percent must be between 0 and 100")
    share = Decimal(str(inputs.everyday.category_shares.get(category, 0.0)))
    if share == 0:
        raise ValueError(f"no everyday spending in {category!r} to reduce")
    factor = 1 - share * percent / 100
    e = inputs.everyday
    scaled = replace(e, mid=_money(e.mid * factor), per_day=_money(e.per_day * factor),
                     low=_money(e.low * factor) if e.low is not None else None,
                     high=_money(e.high * factor) if e.high is not None else None)
    return replace(inputs, everyday=scaled,
                   changes=inputs.changes + (f"{category} spending reduced by {percent}% "
                                             f"({share:.0%} of everyday spending)",))


def delay_repayment(inputs: Inputs, person: str) -> Inputs:
    if person not in {p for p, _ in inputs.receivables}:
        raise ValueError(f"{person} does not owe you anything")
    return replace(inputs, receivables=tuple((p, a) for p, a in inputs.receivables if p != person),
                   changes=inputs.changes + (f"{person}'s repayment arrives after this period",))


def skip_commitment(inputs: Inputs, name: str) -> Inputs:
    if name not in {o.name for o in inputs.occurrences}:
        raise ValueError(f"no commitment called {name!r} in this period")
    return replace(inputs, occurrences=tuple(o for o in inputs.occurrences if o.name != name),
                   changes=inputs.changes + (f"Without: {name}",))
