"""Core data types shared by every pipeline stage.

These are plain, immutable values with no database or web dependencies, so
the financial logic can be tested in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum

UNCATEGORIZED = "Uncategorized"


class Direction(StrEnum):
    DEBIT = "debit"  # money out
    CREDIT = "credit"  # money in


class TxnType(StrEnum):
    """What a transaction means economically, independent of its direction."""

    EXPENSE = "expense"
    INCOME = "income"
    TRANSFER = "transfer"  # between your own accounts
    REFUND = "refund"
    LENT = "lent"
    BORROWED = "borrowed"
    REPAYMENT_RECEIVED = "repayment_received"
    REPAYMENT_MADE = "repayment_made"
    REVERSAL = "reversal"
    UNKNOWN = "unknown"


# Directions each type can have. A debit can never be income, and so on.
ALLOWED_DIRECTIONS: dict[TxnType, frozenset[Direction]] = {
    TxnType.EXPENSE: frozenset({Direction.DEBIT}),
    TxnType.INCOME: frozenset({Direction.CREDIT}),
    TxnType.REFUND: frozenset({Direction.CREDIT}),
    TxnType.LENT: frozenset({Direction.DEBIT}),
    TxnType.BORROWED: frozenset({Direction.CREDIT}),
    TxnType.REPAYMENT_RECEIVED: frozenset({Direction.CREDIT}),
    TxnType.REPAYMENT_MADE: frozenset({Direction.DEBIT}),
    TxnType.TRANSFER: frozenset(Direction),
    TxnType.REVERSAL: frozenset(Direction),
    TxnType.UNKNOWN: frozenset(Direction),
}


class Status(StrEnum):
    POSTED = "posted"
    PENDING = "pending"
    FAILED = "failed"
    REVERSED = "reversed"
    UNKNOWN = "unknown"  # the source did not say


class Basis(StrEnum):
    """How a field's value was decided. Lets the ledger separate facts from guesses."""

    SOURCE = "source"  # stated by the imported file
    USER = "user"  # entered or confirmed by the user
    RULE = "rule"  # inferred by a keyword rule
    MODEL = "model"  # inferred by an ML model (not used yet)
    NONE = "none"  # not known


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
    category_basis: Basis = Basis.NONE
    txn_type: TxnType = TxnType.UNKNOWN
    type_basis: Basis = Basis.NONE
    status: Status = Status.UNKNOWN
    reference: str | None = None
    raw_description: str = ""
    source_file: str = ""
    source_row: int = 0

    @property
    def direction(self) -> Direction:
        return Direction.CREDIT if self.amount > 0 else Direction.DEBIT


@dataclass(frozen=True, slots=True)
class RejectedRow:
    """A source row that could not be turned into a Transaction."""

    source_file: str
    source_row: int
    reason: str
    raw: dict[str, str] = field(default_factory=dict)
