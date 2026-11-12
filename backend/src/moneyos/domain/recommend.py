"""Rule-based recommendations: transparent, evidence-backed, never judgemental.

Each recommendation states what was noticed (with the numbers) and offers
an optional next step. Wording is neutral: it describes, it does not
blame. Inputs are computed elsewhere; this module only applies the rules.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from moneyos.domain.budgets import BudgetState, BudgetUse

RISE_THRESHOLD = Decimal("1.30")  # this month at least 30% above the recent average...
RISE_MINIMUM = Decimal("500")  # ...and at least this much more, so tiny categories stay quiet
SUBSCRIPTION_MAX = Decimal("2000")  # a small, fixed monthly payment
OWED_REMINDER_DAYS = 30


@dataclass(frozen=True, slots=True)
class Recommendation:
    kind: str
    priority: int  # 1 = most useful first
    title: str
    message: str
    evidence: dict = field(default_factory=dict)
    action: str | None = None  # a hint for the client, e.g. which screen helps


@dataclass(frozen=True, slots=True)
class CategoryTrend:
    category: str
    this_month: Decimal
    recent_average: Decimal  # average of earlier full months
    months_compared: int


@dataclass(frozen=True, slots=True)
class Subscription:
    name: str
    monthly_amount: Decimal


@dataclass(frozen=True, slots=True)
class OwedToYou:
    person: str
    amount: Decimal
    since: date


def recommend(
    *,
    currency: str,
    today: date,
    trends: Sequence[CategoryTrend] = (),
    budgets: Sequence[BudgetUse] = (),
    subscriptions: Sequence[Subscription] = (),
    owed: Sequence[OwedToYou] = (),
    unknown_type: int = 0,
    open_duplicates: int = 0,
    reserve: Decimal | None = None,
) -> list[Recommendation]:
    out: list[Recommendation] = []

    for t in trends:
        if t.months_compared < 2 or t.recent_average <= 0:
            continue
        if t.this_month >= t.recent_average * RISE_THRESHOLD and t.this_month - t.recent_average >= RISE_MINIMUM:
            rise = (t.this_month / t.recent_average - 1) * 100
            out.append(Recommendation(
                "category_rising", 2, f"{t.category} is higher than usual",
                f"{t.category} spending this month is {t.this_month:,.2f} {currency}, about {rise:.0f}% above your "
                f"recent average of {t.recent_average:,.2f}. If that wasn't planned, a {t.category} budget can help "
                "you keep an eye on it.",
                {"this_month": str(t.this_month), "recent_average": str(t.recent_average),
                 "months_compared": t.months_compared}, "budgets"))

    for b in budgets:
        if b.state in (BudgetState.CLOSE, BudgetState.OVER):
            out.append(Recommendation(
                "budget", 1 if b.state == BudgetState.OVER else 2, f"{b.category} budget", b.message(),
                {"limit": str(b.limit), "spent": str(b.spent), "percent_used": b.percent_used}, "budgets"))

    if len(subscriptions) >= 2:
        total = sum((s.monthly_amount for s in subscriptions), Decimal(0))
        listed = ", ".join(f"{s.name} ({s.monthly_amount:,.0f})" for s in subscriptions)
        out.append(Recommendation(
            "subscriptions", 3, "Your regular subscriptions",
            f"You have {len(subscriptions)} regular subscriptions adding up to {total:,.2f} {currency} a month: "
            f"{listed}. Worth a quick check that you still use all of them.",
            {"count": len(subscriptions), "monthly_total": str(total)}, "commitments"))

    for o in owed:
        days = (today - o.since).days
        if days >= OWED_REMINDER_DAYS:
            out.append(Recommendation(
                "owed_to_you", 2, f"{o.person} owes you {o.amount:,.2f}",
                f"{o.person} has owed you {o.amount:,.2f} {currency} since {o.since:%d %b %Y} ({days} days). "
                "A friendly reminder might help; MoneyOS never contacts anyone for you.",
                {"amount": str(o.amount), "since": o.since.isoformat()}, "money_majra"))

    if reserve is not None and reserve > 0:
        out.append(Recommendation(
            "reserve", 2, "Set aside for upcoming commitments",
            f"Your confirmed payments over the next 30 days come to about {reserve:,.2f} {currency}. "
            "Keeping that amount aside covers them.",
            {"reserve": str(reserve)}, "commitments"))

    if open_duplicates:
        out.append(Recommendation(
            "review_duplicates", 1, "Possible duplicates to review",
            f"{open_duplicates} pair(s) of transactions may be the same payment. Reviewing them makes your totals "
            "accurate.", {"open": open_duplicates}, "review"))
    if unknown_type:
        out.append(Recommendation(
            "classify", 3, "Some payments need a type",
            f"{unknown_type} payment(s) don't have a type yet, so they aren't counted as income or spending. "
            "Marking them gives you more accurate numbers.", {"count": unknown_type}, "transactions"))

    return sorted(out, key=lambda r: (r.priority, r.kind, r.title))
