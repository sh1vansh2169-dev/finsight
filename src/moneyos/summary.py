"""Financial summaries over cleaned, de-duplicated transactions.

Definitions:

* income   = sum of positive amounts, excluding transfers
* expenses = sum of negative amounts (reported as a positive number),
             excluding transfers
* net      = income - expenses

Transfers between your own accounts are reported separately because they are
neither income nor spending. A refund is a positive amount and so counts as
income rather than reducing its category's spend.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from moneyos.categorize import TRANSFER
from moneyos.models import Transaction

_ZERO = Decimal("0.00")


@dataclass(frozen=True, slots=True)
class PeriodTotals:
    income: Decimal = _ZERO
    expenses: Decimal = _ZERO

    @property
    def net(self) -> Decimal:
        return self.income - self.expenses


@dataclass(frozen=True, slots=True)
class Summary:
    currency: str
    transaction_count: int
    start_date: date | None
    end_date: date | None
    totals: PeriodTotals
    transfers_in: Decimal
    transfers_out: Decimal
    # "YYYY-MM" -> totals, in chronological order.
    by_month: dict[str, PeriodTotals] = field(default_factory=dict)
    # Category -> spend (positive), largest first. Sums to totals.expenses.
    expenses_by_category: dict[str, Decimal] = field(default_factory=dict)
    largest_expenses: list[Transaction] = field(default_factory=list)


def summarize(transactions: Iterable[Transaction], *, top_n: int = 5) -> Summary:
    """Summarise transactions that all share one currency."""
    transactions = list(transactions)
    currencies = {t.currency for t in transactions}
    if len(currencies) > 1:
        raise ValueError(
            f"cannot add up mixed currencies {sorted(currencies)}; use summarize_by_currency"
        )

    income = expenses = transfers_in = transfers_out = _ZERO
    months: dict[str, list[Decimal]] = defaultdict(lambda: [_ZERO, _ZERO])
    categories: dict[str, Decimal] = defaultdict(lambda: _ZERO)
    spending = []

    for t in transactions:
        if t.category == TRANSFER:
            if t.amount > 0:
                transfers_in += t.amount
            else:
                transfers_out -= t.amount
            continue
        month = months[t.date.strftime("%Y-%m")]
        if t.amount > 0:
            income += t.amount
            month[0] += t.amount
        else:
            expenses -= t.amount
            month[1] -= t.amount
            categories[t.category] -= t.amount
            spending.append(t)

    return Summary(
        currency=currencies.pop() if currencies else "",
        transaction_count=len(transactions),
        start_date=min((t.date for t in transactions), default=None),
        end_date=max((t.date for t in transactions), default=None),
        totals=PeriodTotals(income, expenses),
        transfers_in=transfers_in,
        transfers_out=transfers_out,
        by_month={m: PeriodTotals(*months[m]) for m in sorted(months)},
        expenses_by_category=dict(
            sorted(categories.items(), key=lambda item: (-item[1], item[0]))
        ),
        largest_expenses=sorted(spending, key=lambda t: (t.amount, t.date))[:top_n],
    )


def summarize_by_currency(
    transactions: Iterable[Transaction], *, top_n: int = 5
) -> dict[str, Summary]:
    grouped: dict[str, list[Transaction]] = defaultdict(list)
    for t in transactions:
        grouped[t.currency].append(t)
    return {c: summarize(grouped[c], top_n=top_n) for c in sorted(grouped)}
