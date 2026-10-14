"""Financial summaries over cleaned, de-duplicated transactions.

These are *recorded* totals: they cover only the transactions MoneyOS has
seen and are not a bank balance.

Definitions (all amounts are positive magnitudes unless noted):

* Failed transactions are excluded from every total and counted separately.
* Transfers between your own accounts are excluded from inflow, outflow and
  net, and reported separately.
* inflow / outflow = all other money in / out, whatever its type.
* net cash flow    = inflow - outflow (signed).
* income, expenses, refunds, lent, ... = per-type totals. Money whose type is
  unknown is reported as unclassified inflow/outflow, never folded into
  income or expenses. Hence: inflow = income + refunds + borrowed +
  repayments received + reversals in + unclassified in, and likewise for
  outflow.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from moneyos.domain.models import UNCATEGORIZED, Direction, Status, Transaction, TxnType

ZERO = Decimal("0.00")


@dataclass(frozen=True, slots=True)
class MonthSummary:
    income: Decimal = ZERO
    expenses: Decimal = ZERO
    inflow: Decimal = ZERO
    outflow: Decimal = ZERO

    @property
    def net_cash_flow(self) -> Decimal:
        return self.inflow - self.outflow


@dataclass(frozen=True, slots=True)
class DataQuality:
    unknown_type: int = 0
    uncategorized_expenses: int = 0
    pending: int = 0
    reversed_status: int = 0
    unknown_status: int = 0
    failed_excluded: int = 0

    def warnings(self) -> list[str]:
        messages = []
        if self.unknown_type:
            messages.append(
                f"{self.unknown_type} transaction(s) have an unknown type and are shown as "
                "unclassified, not as income or expenses."
            )
        if self.uncategorized_expenses:
            messages.append(f"{self.uncategorized_expenses} expense(s) have no category.")
        if self.pending:
            messages.append(f"{self.pending} transaction(s) are still pending and may change.")
        if self.reversed_status:
            messages.append(
                f"{self.reversed_status} transaction(s) are marked reversed by the source; "
                "check that a matching reversal entry exists so the money is not counted twice."
            )
        if self.failed_excluded:
            messages.append(f"{self.failed_excluded} failed transaction(s) were excluded from totals.")
        return messages


@dataclass(frozen=True, slots=True)
class LedgerSummary:
    currency: str
    transaction_count: int
    start_date: date | None
    end_date: date | None
    inflow: Decimal
    outflow: Decimal
    transfers_in: Decimal
    transfers_out: Decimal
    # TxnType -> total magnitude, excluding transfers and failed transactions.
    by_type: dict[TxnType, Decimal] = field(default_factory=dict)
    by_month: dict[str, MonthSummary] = field(default_factory=dict)
    # Category -> spend, largest first. Sums to ``expenses``.
    expenses_by_category: dict[str, Decimal] = field(default_factory=dict)
    largest_expenses: list[Transaction] = field(default_factory=list)
    quality: DataQuality = field(default_factory=DataQuality)
    unclassified_inflow: Decimal = ZERO
    unclassified_outflow: Decimal = ZERO

    @property
    def net_cash_flow(self) -> Decimal:
        return self.inflow - self.outflow

    @property
    def income(self) -> Decimal:
        return self.by_type.get(TxnType.INCOME, ZERO)

    @property
    def expenses(self) -> Decimal:
        return self.by_type.get(TxnType.EXPENSE, ZERO)

    @property
    def refunds(self) -> Decimal:
        return self.by_type.get(TxnType.REFUND, ZERO)


def summarize(transactions: Iterable[Transaction], *, top_n: int = 5) -> LedgerSummary:
    """Summarise transactions that all share one currency."""
    transactions = list(transactions)
    currencies = {t.currency for t in transactions}
    if len(currencies) > 1:
        raise ValueError(
            f"cannot add up mixed currencies {sorted(currencies)}; use summarize_by_currency"
        )

    inflow = outflow = transfers_in = transfers_out = ZERO
    unclassified_in = unclassified_out = ZERO
    by_type: dict[TxnType, Decimal] = defaultdict(lambda: ZERO)
    months: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    categories: dict[str, Decimal] = defaultdict(lambda: ZERO)
    spending: list[Transaction] = []
    quality = defaultdict(int)

    for t in transactions:
        if t.status == Status.FAILED:
            quality["failed_excluded"] += 1
            continue
        if t.status == Status.PENDING:
            quality["pending"] += 1
        elif t.status == Status.REVERSED:
            quality["reversed_status"] += 1
        elif t.status == Status.UNKNOWN:
            quality["unknown_status"] += 1

        magnitude = abs(t.amount)
        if t.txn_type == TxnType.TRANSFER:
            if t.direction == Direction.CREDIT:
                transfers_in += magnitude
            else:
                transfers_out += magnitude
            continue

        month = months[t.date.strftime("%Y-%m")]
        by_type[t.txn_type] += magnitude
        if t.direction == Direction.CREDIT:
            inflow += magnitude
            month["inflow"] += magnitude
        else:
            outflow += magnitude
            month["outflow"] += magnitude

        if t.txn_type == TxnType.INCOME:
            month["income"] += magnitude
        elif t.txn_type == TxnType.EXPENSE:
            month["expenses"] += magnitude
            categories[t.category] += magnitude
            spending.append(t)
            if t.category == UNCATEGORIZED:
                quality["uncategorized_expenses"] += 1
        elif t.txn_type == TxnType.UNKNOWN:
            quality["unknown_type"] += 1
            if t.direction == Direction.CREDIT:
                unclassified_in += magnitude
            else:
                unclassified_out += magnitude

    return LedgerSummary(
        currency=currencies.pop() if currencies else "",
        transaction_count=len(transactions),
        start_date=min((t.date for t in transactions), default=None),
        end_date=max((t.date for t in transactions), default=None),
        inflow=inflow,
        outflow=outflow,
        transfers_in=transfers_in,
        transfers_out=transfers_out,
        by_type=dict(by_type),
        by_month={m: MonthSummary(**months[m]) for m in sorted(months)},
        expenses_by_category=dict(
            sorted(categories.items(), key=lambda item: (-item[1], item[0]))
        ),
        largest_expenses=sorted(spending, key=lambda t: (t.amount, t.date))[:top_n],
        quality=DataQuality(**quality),
        unclassified_inflow=unclassified_in,
        unclassified_outflow=unclassified_out,
    )


def summarize_by_currency(
    transactions: Iterable[Transaction], *, top_n: int = 5
) -> dict[str, LedgerSummary]:
    grouped: dict[str, list[Transaction]] = defaultdict(list)
    for t in transactions:
        grouped[t.currency].append(t)
    return {c: summarize(grouped[c], top_n=top_n) for c in sorted(grouped)}
