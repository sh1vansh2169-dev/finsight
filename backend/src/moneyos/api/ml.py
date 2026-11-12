"""Routes for model-based suggestions. Models are loaded lazily from settings.models_dir."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from moneyos.api.routes import SessionDep
from moneyos.api.schemas import TransactionOut
from moneyos.services import categorize
from moneyos.services.errors import NotFoundError

router = APIRouter(prefix="/ml", tags=["machine learning"])
NO_MODEL = "No categorisation model has been trained yet. Run `moneyos ml categorization` first."


def _model(request: Request):
    state = request.app.state
    if getattr(state, "categorizer", None) is None:
        from moneyos.ml.categorizer import load_latest

        state.categorizer, state.categorizer_card = load_latest(state.settings.models_dir)
    if state.categorizer is None:
        raise NotFoundError(NO_MODEL)
    return state.categorizer, state.categorizer_card


class AlternativeOut(BaseModel):
    category: str
    confidence: float


class SuggestionOut(BaseModel):
    transaction: TransactionOut
    category: str
    confidence: float = Field(description="The model's probability for its top choice (0-1); not a guarantee.")
    confident: bool = Field(description="At or above the threshold used in the evaluation.")
    alternatives: list[AlternativeOut]


class SuggestionsOut(BaseModel):
    model_version: str
    threshold: float
    note: str = (
        "Suggestions only. Trained on synthetic data so far; accept one with PATCH /api/v1/transactions/{id}."
    )
    suggestions: list[SuggestionOut]


class ApplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_confidence: float = Field(default=0.9, ge=categorize.DEFAULT_THRESHOLD, le=1)


@router.get("/categorizer")
def model_card(request: Request) -> dict[str, Any]:
    """What the current model is, what it was trained on, and how it scored."""
    return _model(request)[1]


@router.get("/category-suggestions", response_model=SuggestionsOut)
def suggestions(request: Request, session: SessionDep, limit: int = Query(default=50, ge=1, le=500)):
    """Category suggestions for transactions that still have none."""
    model, card = _model(request)
    threshold = card.get("preregistered", {}).get("confidence_threshold", categorize.DEFAULT_THRESHOLD)
    return SuggestionsOut(
        model_version=card["version"],
        threshold=threshold,
        suggestions=[
            SuggestionOut(
                transaction=TransactionOut.from_record(s.record), category=s.category,
                confidence=round(s.confidence, 4), confident=s.confident(threshold),
                alternatives=[AlternativeOut(category=c, confidence=round(p, 4)) for c, p in s.alternatives],
            )
            for s in categorize.suggest(session, model, limit=limit)
        ],
    )


@router.post("/category-suggestions/apply")
def apply_suggestions(body: ApplyIn, request: Request, session: SessionDep) -> dict[str, Any]:
    """Apply suggestions at or above ``min_confidence``. They are marked as model-inferred and audited."""
    model, card = _model(request)
    count = categorize.apply(session, model, card["version"], min_confidence=body.min_confidence)
    return {"applied": count, "model_version": card["version"], "basis": "model"}


# ------------------------------------------------------- unusual spending


class UnusualOut(BaseModel):
    transaction: TransactionOut
    reason: str
    score: float = Field(description="How far above your usual amount, in robust standard deviations.")


class UnusualListOut(BaseModel):
    method: str
    note: str
    payments: list[UnusualOut]


class DismissIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    note: str | None = Field(default=None, max_length=200)


@router.get("/unusual", response_model=UnusualListOut, tags=["insights"])
def unusual_payments(session: SessionDep, start: date | None = None, end: date | None = None,
                     currency: str | None = Query(default=None, pattern=r"^[A-Za-z]{3}$")):
    """Payments that are unusually large for you, with the reason. Not a fraud check."""
    from moneyos.services import analytics, insights

    currency = analytics.resolve_currency(session, currency)
    found = insights.unusual(session, currency, start, end) if currency else []
    return UnusualListOut(
        method=insights.METHOD, note=insights.NOTE,
        payments=[UnusualOut(transaction=TransactionOut.from_record(u.record), reason=u.reason,
                             score=round(u.score, 2)) for u in found],
    )


@router.post("/unusual/{transaction_id}/dismiss", status_code=204, tags=["insights"])
def dismiss_unusual(transaction_id: int, body: DismissIn, session: SessionDep) -> None:
    """"This was expected": recorded in the audit log; the payment is not flagged again."""
    from moneyos.services import insights

    insights.dismiss(session, transaction_id, body.note)
