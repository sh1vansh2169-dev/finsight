"""Routes: recurring payments, commitments, the what-if simulator, recommendations."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, ConfigDict, Field

from moneyos.api.routes import SessionDep
from moneyos.db.tables import Commitment
from moneyos.domain import simulator as sim
from moneyos.domain.models import Direction
from moneyos.domain.money import from_minor
from moneyos.services import analytics, commitments, planning
from moneyos.services.errors import InvalidRequestError

router = APIRouter()
ESTIMATE_NOTE = (
    "Estimates, not promises. Everyday spending is your historical average; the range comes from your own past "
    "spending. Money others owe you is never counted as money you have."
)
CurrencyQuery = Annotated[str | None, Query(pattern=r"^[A-Za-z]{3}$")]


class _In(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class RecurringOut(BaseModel):
    key: str
    name: str
    direction: Direction
    cadence: str
    typical_amount: Decimal
    low: Decimal
    high: Decimal
    amount_varies: bool
    occurrences: int
    last: date
    next_expected: date
    category: str
    confidence: int
    reasons: list[str]
    may_have_stopped: bool
    is_commitment: bool


class CommitmentOut(BaseModel):
    id: int
    name: str
    direction: Direction
    amount: Decimal
    amount_varies: bool
    high: Decimal | None
    currency: str
    cadence: str
    next_due: date
    end_date: date | None
    category: str
    source: str
    status: str

    @classmethod
    def of(cls, c: Commitment) -> CommitmentOut:
        return cls(id=c.id, name=c.name, direction=Direction(c.direction), amount=from_minor(c.amount_minor, c.currency),
                   amount_varies=c.amount_varies, high=from_minor(c.high_minor, c.currency) if c.high_minor else None,
                   currency=c.currency, cadence=c.cadence, next_due=c.next_due, end_date=c.end_date,
                   category=c.category, source=c.source, status=c.status)


class ConfirmIn(_In):
    key: str = Field(min_length=1, max_length=200, description="The `key` of a detected recurring payment.")
    name: str | None = Field(default=None, max_length=100)
    currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")


class CommitmentIn(_In):
    name: str = Field(min_length=1, max_length=100)
    direction: Direction = Direction.DEBIT
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    currency: str = Field(default="INR", pattern=r"^[A-Za-z]{3}$")
    cadence: Literal["once", "weekly", "monthly", "quarterly", "yearly"] = "monthly"
    next_due: date
    end_date: date | None = None
    category: str = Field(default="Uncategorized", min_length=1, max_length=100)


class CommitmentPatch(_In):
    status: Literal["active", "paused", "ended"] | None = None
    amount: Decimal | None = Field(default=None, gt=0, max_digits=15, decimal_places=2)
    next_due: date | None = None
    end_date: date | None = None


class OccurrenceOut(BaseModel):
    date: date
    name: str
    amount: Decimal = Field(description="Positive: money in. Negative: money out.")
    up_to: Decimal | None = Field(default=None, description="For amounts that vary: the largest recent payment.")


class UpcomingOut(BaseModel):
    currency: str | None
    start: date
    end: date
    reserve: Decimal = Field(description="Confirmed payments due in the period, using the high end of varying ones.")
    occurrences: list[OccurrenceOut]


# ---------------------------------------------------------------- scenarios


class Purchase(_In):
    kind: Literal["purchase"]
    amount: Decimal = Field(gt=0, decimal_places=2)
    date: date
    description: str = Field(default="Purchase", max_length=100)


class NewRecurring(_In):
    kind: Literal["new_recurring"]
    name: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(gt=0, decimal_places=2)
    cadence: Literal["once", "weekly", "monthly", "quarterly", "yearly"] = "monthly"
    first_due: date
    money_in: bool = False


class ReduceCategory(_In):
    kind: Literal["reduce_category"]
    category: str = Field(min_length=1, max_length=100)
    percent: Decimal = Field(gt=0, le=100)


class DelayRepayment(_In):
    kind: Literal["delay_repayment"]
    person: str = Field(min_length=1, max_length=100)


class SkipCommitment(_In):
    kind: Literal["skip_commitment"]
    name: str = Field(min_length=1, max_length=100)


Scenario = Annotated[Purchase | NewRecurring | ReduceCategory | DelayRepayment | SkipCommitment,
                     Field(discriminator="kind")]


class SimulateIn(_In):
    horizon_days: int = Field(default=30, ge=7, le=90)
    starting_balance: Decimal | None = Field(
        default=None, max_digits=15, decimal_places=2,
        description="Your current balance, if you want a projected balance. MoneyOS does not know it otherwise.",
    )
    as_of: date | None = Field(default=None, description="Defaults to the date of your newest transaction.")
    currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")
    scenarios: list[Scenario] = Field(default_factory=list, max_length=10)


def _projection(p: sim.Projection) -> dict[str, Any]:
    e = p.everyday
    return {
        "start": p.start, "end": p.end, "currency": p.currency,
        "net_change": {"estimate": p.net_change, "cautious": p.net_change_low, "hopeful": p.net_change_high},
        "balance": None if p.balance is None else {"estimate": p.balance, "cautious": p.balance_low,
                                                    "hopeful": p.balance_high},
        "commitments": {"money_in": p.commitments_in, "money_out": p.commitments_out,
                        "money_out_high": p.commitments_out_high},
        "everyday_spending": {"estimate": e.mid, "low": e.low, "high": e.high, "per_day": e.per_day,
                              "history_days": e.history_days},
        "not_included": {"if_others_repay_you": p.if_repaid, "if_you_repay_others": p.if_you_repay},
        "reserve_for_commitments": p.reserve_for_commitments,
        "occurrences": [{"date": o.on, "name": o.name, "amount": o.amount} for o in p.occurrences],
        "path": [{"date": d, "net_change": v} for d, v in p.path],
        "assumptions": list(p.assumptions),
        "changes": list(p.changes),
    }


def _currency(session, currency):
    resolved = analytics.resolve_currency(session, currency)
    if resolved is None:
        raise InvalidRequestError("no transactions recorded yet")
    return resolved


# ------------------------------------------------------------------- routes


@router.get("/recurring", response_model=list[RecurringOut], tags=["commitments"])
def recurring(session: SessionDep, currency: CurrencyQuery = None, as_of: date | None = None):
    """Payments that look regular. Suggestions only: confirm one to make it a commitment."""
    currency = _currency(session, currency)
    as_of = as_of or planning.default_as_of(session)
    committed = {c.merchant_key for c in commitments.list_commitments(session, currency) if c.status != "ended"}
    return [RecurringOut(**{k: getattr(s, k) for k in RecurringOut.model_fields if k != "reasons" and hasattr(s, k)},
                         reasons=list(s.reasons), is_commitment=s.key in committed)
            for s in commitments.detected(session, currency, as_of)]


@router.get("/commitments", response_model=list[CommitmentOut], tags=["commitments"])
def list_commitments(session: SessionDep):
    return [CommitmentOut.of(c) for c in commitments.list_commitments(session)]


@router.post("/commitments/confirm", response_model=CommitmentOut, status_code=status.HTTP_201_CREATED, tags=["commitments"])
def confirm(body: ConfirmIn, session: SessionDep):
    currency = _currency(session, body.currency)
    return CommitmentOut.of(commitments.confirm_detected(session, body.key, currency, planning.default_as_of(session),
                                                         name=body.name))


@router.post("/commitments", response_model=CommitmentOut, status_code=status.HTTP_201_CREATED, tags=["commitments"])
def add(body: CommitmentIn, session: SessionDep):
    return CommitmentOut.of(commitments.add_manual(
        session, name=body.name, direction=body.direction, amount=body.amount, currency=body.currency,
        cadence=body.cadence, next_due=body.next_due, category=body.category, end_date=body.end_date))


@router.patch("/commitments/{commitment_id}", response_model=CommitmentOut, tags=["commitments"])
def patch(commitment_id: int, body: CommitmentPatch, session: SessionDep):
    return CommitmentOut.of(commitments.update(session, commitment_id, status=body.status, amount=body.amount,
                                               next_due=body.next_due, end_date=body.end_date))


@router.get("/commitments/upcoming", response_model=UpcomingOut, tags=["commitments"])
def upcoming(session: SessionDep, days: int = Query(default=30, ge=1, le=366), currency: CurrencyQuery = None,
             as_of: date | None = None):
    """Confirmed payments and income due soon, and how much to keep aside for them."""
    currency = analytics.resolve_currency(session, currency)
    start = as_of or planning.default_as_of(session)
    end = start + timedelta(days=days)
    found = commitments.occurrences(session, currency, start + timedelta(days=1), end) if currency else []
    reserve = sum((o.high if o.high is not None else -o.amount for o in found if o.amount < 0), Decimal(0))
    return UpcomingOut(currency=currency, start=start, end=end, reserve=reserve,
                       occurrences=[OccurrenceOut(date=o.on, name=o.name, amount=o.amount, up_to=o.high) for o in found])


@router.post("/simulate", tags=["what-if"])
def simulate(body: SimulateIn, session: SessionDep) -> dict[str, Any]:
    """Project the next days, and optionally compare with what-if changes. Deterministic: same input, same answer."""
    currency = _currency(session, body.currency)
    base_inputs = planning.inputs(session, currency, as_of=body.as_of, horizon=body.horizon_days,
                                  starting_balance=body.starting_balance)
    base = sim.project(base_inputs)
    result: dict[str, Any] = {"note": ESTIMATE_NOTE, "baseline": _projection(base)}
    if body.scenarios:
        try:
            changed = sim.project(planning.apply_scenarios(base_inputs, [s.model_dump() for s in body.scenarios]))
        except ValueError as error:
            raise InvalidRequestError(str(error)) from None
        result["scenario"] = _projection(changed)
        result["difference"] = {
            "net_change": changed.net_change - base.net_change,
            "balance": (changed.balance - base.balance) if base.balance is not None else None,
        }
    return result


@router.get("/recommendations", tags=["recommendations"])
def recommendations(session: SessionDep, currency: CurrencyQuery = None, as_of: date | None = None) -> list[dict[str, Any]]:
    """Plain, evidence-backed suggestions. Rule-based; nothing is done automatically."""
    currency = _currency(session, currency)
    return [{"kind": r.kind, "priority": r.priority, "title": r.title, "message": r.message,
             "evidence": r.evidence, "action": r.action}
            for r in planning.recommendations(session, currency, as_of=as_of)]
