"""Core data types shared by every pipeline stage."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

UNCATEGORIZED = "Uncategorized"


@dataclass(frozen=True, slots=True)
class Transaction:
    """One cleaned transaction.

    ``amount`` is signed: positive is money in, negative is money out.
    """

    date: date
    description: str
    amount: Decimal
    currency: str
    account: str
    category: str = UNCATEGORIZED
    reference: str | None = None
    raw_description: str = ""
    source_file: str = ""
    source_row: int = 0


@dataclass(frozen=True, slots=True)
class RejectedRow:
    """A source row that could not be turned into a Transaction."""

    source_file: str
    source_row: int
    reason: str
    raw: dict[str, str] = field(default_factory=dict)
