"""Builds simulator inputs and recommendations from the stored ledger."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from moneyos.analytics.recurring import merchant_key
from moneyos.db.tables import MajraEntry, TransactionRecord
from moneyos.domain import simulator as sim
from moneyos.domain.budgets import BudgetUse
from moneyos.domain.models import Direction, Status, TxnType
from moneyos.domain.money import from_minor
from moneyos.domain.recommend import CategoryTrend, OwedToYou, Recommendation, Subscription, recommend
from moneyos.services import analytics, budgets, commitments, majra, review

LOOKBACK_DAYS = 180
SUBSCRIPTION_EXCLUDED = {"Housing", "Utilities", "Salary"}


def default_as_of(session: Session) -> date:
    """The newest recorded transaction date (data may be older than today)."""
    newest = session.scalar(select(func.max(TransactionRecord.occurred_on)).where(TransactionRecord.duplicate_of_id.is_(None)))
    return newest or date.today()


def _everyday(session: Session, currency: str, as_of: date, horizon: int) -> sim.Everyday:
    """Spending that is not a confirmed commitment, per covered day, over the lookback window."""
    committed = {c.merchant_key for c in commitments.list_commitments(session, currency, active_only=True)
                 if c.merchant_key}
    start = as_of - timedelta(days=LOOKBACK_DAYS - 1)
    daily: dict[date, Decimal] = defaultdict(Decimal)
    categories: dict[str, Decimal] = defaultdict(Decimal)
    for r in commitments.active_records(session, currency):
        if not start <= r.occurred_on <= as_of or r.status == Status.FAILED.value:
            continue
        if merchant_key(r.description) in committed:
            continue  # counted as a commitment instead
        amount = from_minor(r.amount_minor, currency)
        if r.txn_type == TxnType.EXPENSE.value or (r.txn_type == TxnType.UNKNOWN.value and r.direction == Direction.DEBIT.value):
            daily[r.occurred_on] += amount
            categories[r.category] += amount
        elif r.txn_type == TxnType.REFUND.value:
            daily[r.occurred_on] -= amount
            categories[r.category] -= amount
    cover = analytics.coverage(session)
    days = [start + timedelta(days=i) for i in range(LOOKBACK_DAYS)]
    if cover:
        days = [d for d in days if any(c.covers(d) for c in cover.values())]
    else:
        first = min(daily, default=as_of)
        days = [d for d in days if d >= first]
    return sim.everyday_from_history([daily.get(d, Decimal(0)) for d in days], horizon,
                                     {c: v for c, v in categories.items() if v > 0})


def inputs(session: Session, currency: str, *, as_of: date | None = None, horizon: int = 30,
           starting_balance: Decimal | None = None) -> sim.Inputs:
    as_of = as_of or default_as_of(session)
    end = as_of + timedelta(days=horizon)
    receivables, payables = [], []
    for position in majra.summary(session):
        if position.currency != currency:
            continue
        for p in position.people:
            if p.owes_you:
                receivables.append((p.person.name, from_minor(p.owes_you, currency)))
            if p.you_owe:
                payables.append((p.person.name, from_minor(p.you_owe, currency)))
    return sim.Inputs(
        start=as_of, horizon=horizon, currency=currency,
        occurrences=tuple(commitments.occurrences(session, currency, as_of + timedelta(days=1), end)),
        everyday=_everyday(session, currency, as_of, horizon),
        receivables=tuple(receivables), payables=tuple(payables), starting_balance=starting_balance,
    )


def _date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


SCENARIOS = {
    "purchase": lambda i, s: sim.purchase(i, Decimal(s["amount"]), _date(s["date"]),
                                          s.get("description", "Purchase")),
    "new_recurring": lambda i, s: sim.add_recurring(i, s["name"], Decimal(s["amount"]), s.get("cadence", "monthly"),
                                                    _date(s["first_due"]), s.get("money_in", False)),
    "reduce_category": lambda i, s: sim.reduce_category(i, s["category"], Decimal(str(s["percent"]))),
    "delay_repayment": lambda i, s: sim.delay_repayment(i, s["person"]),
    "skip_commitment": lambda i, s: sim.skip_commitment(i, s["name"]),
}


def apply_scenarios(base: sim.Inputs, scenarios: list[dict]) -> sim.Inputs:
    result = base
    for scenario in scenarios:
        result = SCENARIOS[scenario["kind"]](result, scenario)
    return result


# ---------------------------------------------------------- recommendations


def _trends(session: Session, currency: str, as_of: date) -> list[CategoryTrend]:
    """This month vs the average of up to three earlier full months, per category (after refunds)."""
    months: dict[tuple[int, int], dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for r in commitments.active_records(session, currency):
        if r.status == Status.FAILED.value or r.txn_type not in (TxnType.EXPENSE.value, TxnType.REFUND.value):
            continue
        sign = 1 if r.txn_type == TxnType.EXPENSE.value else -1
        months[(r.occurred_on.year, r.occurred_on.month)][r.category] += sign * from_minor(r.amount_minor, currency)
    this = (as_of.year, as_of.month)
    earlier = sorted(m for m in months if m < this)[-3:]
    if not earlier:
        return []
    categories = set(months[this]) | {c for m in earlier for c in months[m]}
    return [
        CategoryTrend(c, months[this].get(c, Decimal(0)),
                      sum((months[m].get(c, Decimal(0)) for m in earlier), Decimal(0)) / len(earlier), len(earlier))
        for c in sorted(categories)
    ]


def _owed(session: Session, currency: str) -> list[OwedToYou]:
    you = majra.me(session)
    out = []
    for group in majra.list_groups(session):
        if group.currency != currency:
            continue
        state = majra.group_state(session, group)
        owing = [t for t in state.plan.transfers if t.receiver == you.id]
        if not owing:
            continue
        since = session.scalar(select(func.min(MajraEntry.occurred_on)).where(
            MajraEntry.group_id == group.id, MajraEntry.voided_at.is_(None)))
        for t in owing:
            out.append(OwedToYou(majra.get_person(session, t.payer).name, from_minor(t.amount, currency), since))
    return out


def _subscriptions(session: Session, currency: str, as_of: date) -> list[Subscription]:
    found = {}
    for c in commitments.list_commitments(session, currency, active_only=True):
        if (c.cadence == "monthly" and c.direction == Direction.DEBIT.value and not c.amount_varies
                and c.category not in SUBSCRIPTION_EXCLUDED and from_minor(c.amount_minor, currency) <= Decimal(2000)):
            found[c.merchant_key or c.name] = Subscription(c.name, from_minor(c.amount_minor, currency))
    for s in commitments.detected(session, currency, as_of):
        if (s.cadence == "monthly" and s.direction == Direction.DEBIT and not s.amount_varies and s.confidence >= 85
                and not s.may_have_stopped and s.category not in SUBSCRIPTION_EXCLUDED
                and s.typical_amount <= Decimal(2000)):
            found.setdefault(s.key, Subscription(s.name, s.typical_amount))
    return sorted(found.values(), key=lambda s: s.name)


def recommendations(session: Session, currency: str, *, as_of: date | None = None) -> list[Recommendation]:
    as_of = as_of or default_as_of(session)
    uses: list[BudgetUse] = [
        u for u in budgets.utilisation(session, as_of.year, as_of.month, as_of) if u.currency == currency
    ]
    # Counted exactly as the summary counts it (failed payments excluded), so
    # the two never show different numbers for the same thing.
    unknown = session.scalar(select(func.count()).select_from(TransactionRecord).where(
        TransactionRecord.currency == currency, TransactionRecord.txn_type == TxnType.UNKNOWN.value,
        TransactionRecord.status != Status.FAILED.value, TransactionRecord.duplicate_of_id.is_(None)))
    projection = sim.project(inputs(session, currency, as_of=as_of))
    return recommend(
        currency=currency, today=as_of, trends=_trends(session, currency, as_of), budgets=uses,
        subscriptions=_subscriptions(session, currency, as_of), owed=_owed(session, currency),
        unknown_type=int(unknown or 0), open_duplicates=review.count_open(session),
        reserve=projection.reserve_for_commitments,
    )
