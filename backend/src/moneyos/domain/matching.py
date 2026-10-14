"""Explainable near-duplicate detection.

Exact duplicates (same bank reference, or same account/date/amount/
description) are removed at import time by ``dedupe``. This module finds the
harder cases, where the same real-world payment appears twice with
different details: a payment app's export and the bank statement for the
linked account, a pending and a posted copy, a manual cash entry later
imported from a statement.

It never decides. It proposes pairs with a 0-100 score and the reasons for
it; a person confirms or rejects each pair.

Scoring (hand-chosen weights, **not calibrated against real data**):

* Gate: same currency, same direction, same amount, dates at most
  ``max_days`` apart, neither transaction failed, and no conflicting bank
  references on the same account. Pairs failing the gate are never proposed.
* date closeness  30%  (same day = 1, then linearly down to the window edge)
* description     55%  (token containment or fuzzy similarity, after
                        dropping payment-rail words like "UPI" and numbers)
* same account    15%  (different accounts score 0.6: cross-source
                        duplicates are the main use case)
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from difflib import SequenceMatcher

from moneyos.domain.cleaning import normalize_key
from moneyos.domain.models import Status, Transaction

# Words that describe the payment rail, not the counterparty.
_NOISE = frozenset(
    "upi neft imps rtgs pos ach nach ecs txn ref no id payment paid pay to from via "
    "received debit credit dr cr bill purchase online the and of".split()
)
_WEIGHTS = {"date": Decimal("0.30"), "description": Decimal("0.55"), "account": Decimal("0.15")}


@dataclass(frozen=True, slots=True)
class MatchConfig:
    max_days: int = 3
    threshold: int = 60  # minimum score to propose a pair


@dataclass(frozen=True, slots=True)
class MatchScore:
    score: int
    reasons: tuple[str, ...]

    @property
    def confidence(self) -> str:
        return "high" if self.score >= 80 else "medium"


def _tokens(text: str) -> set[str]:
    return {t for t in normalize_key(text).split() if t not in _NOISE and not re.search(r"\d", t)}


def description_similarity(a: str, b: str) -> float:
    """0..1. Containment handles "Spice Route" vs "UPI/SPICE ROUTE RESTAURANT"."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return SequenceMatcher(None, normalize_key(a), normalize_key(b)).ratio()
    containment = len(ta & tb) / min(len(ta), len(tb))
    fuzzy = SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio()
    return max(containment, fuzzy)


def score_pair(a: Transaction, b: Transaction, config: MatchConfig = MatchConfig()) -> MatchScore | None:
    """Score two transactions, or None if they cannot be the same payment."""
    if a.currency != b.currency or a.amount != b.amount:
        return None
    if Status.FAILED in (a.status, b.status):
        return None
    days = abs((a.date - b.date).days)
    if days > config.max_days:
        return None
    same_account = a.account == b.account
    if same_account and a.reference and b.reference:
        return None  # the bank says these are different (or exact) transactions

    # Decimal arithmetic with half-up rounding, so a score of 86.5 is always
    # 87 (float rounding would give 86, or 87, depending on representation).
    date_score = 1 - Decimal(days) / (config.max_days + 1)
    text_score = description_similarity(a.description, b.description)
    account_score = Decimal(1) if same_account else Decimal("0.6")
    raw = 100 * (
        _WEIGHTS["date"] * date_score
        + _WEIGHTS["description"] * Decimal(str(round(text_score, 4)))
        + _WEIGHTS["account"] * account_score
    )
    score = int(raw.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if score < config.threshold:
        return None

    direction = "money in" if a.amount > 0 else "money out"
    reasons = [
        f"Same amount: {abs(a.amount):,.2f} {a.currency} {direction}",
        "Same date" if days == 0 else f"Dates {days} day{'s' if days > 1 else ''} apart",
        f"Descriptions {round(text_score * 100)}% similar: \"{a.description}\" and \"{b.description}\"",
        "Same account"
        if same_account
        else f"Different accounts ({a.account} and {b.account}); one payment can appear in two sources",
    ]
    return MatchScore(score, tuple(reasons))


def find_candidates(
    items: Sequence[tuple[Hashable, Transaction]],
    config: MatchConfig = MatchConfig(),
) -> list[tuple[Hashable, Hashable, MatchScore]]:
    """All pairs worth reviewing, highest score first.

    ``items`` pairs each transaction with a key (e.g. a database id) that is
    returned with the match. Only transactions with the same amount can
    match, so items are bucketed by amount first.
    """
    buckets: dict[tuple, list[tuple[Hashable, Transaction]]] = defaultdict(list)
    for key, t in items:
        buckets[(t.currency, t.amount)].append((key, t))

    matches = []
    for bucket in buckets.values():
        bucket.sort(key=lambda item: item[1].date)
        for i, (key_a, a) in enumerate(bucket):
            for key_b, b in bucket[i + 1:]:
                if (b.date - a.date).days > config.max_days:
                    break
                if (result := score_pair(a, b, config)) is not None:
                    matches.append((key_a, key_b, result))
    return sorted(matches, key=lambda m: -m[2].score)
