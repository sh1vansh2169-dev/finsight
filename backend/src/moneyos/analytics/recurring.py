"""Detect recurring payments (rent, bills, subscriptions, salary) from history.

A detection is a *suggestion*: the user confirms it to make it a
commitment. Each comes with a confidence score and reasons.

Method, per merchant (description with digits, payment-rail words and month
names removed):

* at least ``MIN_OCCURRENCES`` payments in the same direction;
* the gaps between consecutive payments fit one cadence (weekly, monthly,
  quarterly, yearly) within a tolerance, for at least 75% of gaps;
* amounts are summarised by their median and range; amounts that move by
  more than 10% are marked as varying (an electricity bill), and very
  irregular amounts lower the confidence.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from moneyos.domain.dates import add_months
from moneyos.domain.models import Direction, Status, Transaction, TxnType
from moneyos.ml.text import prepare

MIN_OCCURRENCES = 3
REGULAR_SHARE = 0.75
# cadence -> (typical gap in days, tolerance in days)
CADENCES = {"weekly": (7.0, 2.0), "monthly": (30.44, 4.0), "quarterly": (91.3, 8.0), "yearly": (365.25, 12.0)}
_MONTHS = frozenset("jan feb mar apr may jun jul aug sep sept oct nov dec january february march april june "
                    "july august september october november december".split())


def merchant_key(description: str) -> str:
    return " ".join(w for w in prepare(description).split() if w not in _MONTHS)


def next_after(last: date, cadence: str) -> date:
    if cadence == "monthly":
        return add_months(last, 1)
    if cadence == "quarterly":
        return add_months(last, 3)
    if cadence == "yearly":
        return add_months(last, 12)
    return last + timedelta(days=7)


@dataclass(frozen=True, slots=True)
class RecurringSeries:
    key: str
    name: str
    direction: Direction
    currency: str
    cadence: str
    typical_amount: Decimal  # median, positive
    low: Decimal
    high: Decimal
    amount_varies: bool
    occurrences: int
    first: date
    last: date
    next_expected: date
    category: str
    txn_type: TxnType
    confidence: int  # 0-100
    reasons: tuple[str, ...]
    may_have_stopped: bool
    members: tuple[Hashable, ...]  # keys of the transactions in the series


def _cadence(gaps: list[int]) -> tuple[str, float] | None:
    best = None
    for name, (typical, tolerance) in CADENCES.items():
        share = sum(abs(g - typical) <= tolerance for g in gaps) / len(gaps)
        if share >= REGULAR_SHARE and (best is None or share > best[1]):
            best = (name, share)
    return best


def detect(
    items: Sequence[tuple[Hashable, Transaction]], *, as_of: date, min_occurrences: int = MIN_OCCURRENCES
) -> list[RecurringSeries]:
    """Recurring series among the given transactions, most confident first.

    Failed payments and own-account transfers are ignored.
    """
    groups: dict[tuple, list[tuple[Hashable, Transaction]]] = defaultdict(list)
    for key, t in items:
        if t.status == Status.FAILED or t.txn_type == TxnType.TRANSFER:
            continue
        name = merchant_key(t.description)
        if name:
            groups[(name, t.direction, t.currency)].append((key, t))

    found = []
    for (name, direction, currency), members in groups.items():
        if len(members) < min_occurrences:
            continue
        members.sort(key=lambda m: m[1].date)
        dates = [t.date for _, t in members]
        gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
        if min(gaps) == 0:  # several payments on one day: a habit, not a schedule
            continue
        cadence = _cadence(gaps)
        if cadence is None:
            continue
        cadence_name, regular_share = cadence

        amounts = sorted(abs(t.amount) for _, t in members)
        median = Decimal(statistics.median(amounts)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        spread = (amounts[-1] - amounts[0]) / median if median else Decimal(0)
        varies = spread > Decimal("0.10")
        stability = max(Decimal(0), 1 - spread / 2)  # 1 for fixed amounts, 0 when the range is 2x the median
        confidence = round(100 * (0.5 * regular_share + 0.3 * float(min(stability, 1)) + 0.2 * min(len(members), 6) / 6))

        last = dates[-1]
        typical_gap, tolerance = CADENCES[cadence_name]
        stopped = (as_of - last).days > typical_gap * 1.5 + tolerance
        latest = members[-1][1]
        reasons = [
            f"{len(members)} payments, {regular_share:.0%} of them about {cadence_name.replace('ly', '')} apart"
            if cadence_name != "monthly" else f"{len(members)} payments, {regular_share:.0%} of them about a month apart",
            f"amount {'varies from ' + f'{amounts[0]:,.2f} to {amounts[-1]:,.2f}' if varies else f'steady at about {median:,.2f}'}",
        ]
        if stopped:
            reasons.append(f"nothing since {last:%d %b %Y}: it may have stopped")
        found.append(RecurringSeries(
            key=name, name=latest.description, direction=direction, currency=currency, cadence=cadence_name,
            typical_amount=median, low=amounts[0], high=amounts[-1], amount_varies=varies,
            occurrences=len(members), first=dates[0], last=last, next_expected=next_after(last, cadence_name),
            category=latest.category, txn_type=latest.txn_type, confidence=confidence, reasons=tuple(reasons),
            may_have_stopped=stopped, members=tuple(k for k, _ in members),
        ))
    return sorted(found, key=lambda s: (-s.confidence, s.key))
