"""Duplicate detection across overlapping statement exports.

The hard case is telling a re-imported row apart from two genuinely identical
purchases (two 120.00 coffees on the same day). The rule used here:

* Rows with a bank reference/ID are identified by (account, reference). A
  repeated reference is always a duplicate, even inside one file.
* Rows without one are identified by (account, date, amount, currency,
  normalised description) plus their occurrence number within the batch.
  If a batch contains two identical coffees, both are kept. A later batch
  containing the same two coffees has both dropped; if it contained three,
  the third would be kept as a new transaction.

Identical rows kept from the same batch are also reported as "suspected" so
a person can review them. Nothing in that list has been removed.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from moneyos.domain.cleaning import normalize_key
from moneyos.domain.models import Transaction


@dataclass(slots=True)
class DedupeResult:
    unique: list[Transaction] = field(default_factory=list)
    duplicates: list[Transaction] = field(default_factory=list)
    suspected: list[Transaction] = field(default_factory=list)


def fingerprint(transaction: Transaction) -> tuple:
    """Identity key for a transaction; see the module docstring."""
    if transaction.reference:
        return ("ref", transaction.account, transaction.reference.casefold())
    return (
        "row",
        transaction.account,
        transaction.date,
        transaction.amount,
        transaction.currency,
        normalize_key(transaction.description),
    )


def deduplicate(
    batches: Iterable[Sequence[Transaction]],
    existing: Iterable[Transaction] = (),
) -> DedupeResult:
    """Merge batches (one per source file, in import order) without duplicates.

    ``existing`` are transactions already accepted earlier, e.g. loaded from
    storage; they are treated as a prior batch and are not returned.
    """
    result = DedupeResult()
    seen: Counter[tuple] = Counter(fingerprint(t) for t in existing)

    for batch in batches:
        in_batch: Counter[tuple] = Counter()
        for transaction in batch:
            key = fingerprint(transaction)
            in_batch[key] += 1
            occurrence = in_batch[key]
            if occurrence <= seen[key] or (key[0] == "ref" and occurrence > 1):
                result.duplicates.append(transaction)
                continue
            result.unique.append(transaction)
            if occurrence > 1:
                result.suspected.append(transaction)
        for key, count in in_batch.items():
            seen[key] = max(seen[key], count)

    return result
