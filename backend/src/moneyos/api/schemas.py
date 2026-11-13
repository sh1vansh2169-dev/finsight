"""Request and response models.

Money is always sent as a decimal string ("-120.00"), never a JSON float.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from moneyos.db.tables import Account, ImportBatch, ImportRow, MatchCandidate, TransactionRecord
from moneyos.domain.models import Basis, Direction, Status, TxnType
from moneyos.services.mapping import signed_amount

RECORDED_TOTALS_NOTE = "Recorded totals for transactions in FinSight only; not a bank balance."


class _Out(BaseModel):
    # Pydantic serialises Decimal to a JSON string; tests assert this.
    model_config = ConfigDict(use_enum_values=True)


class HealthOut(_Out):
    status: Literal["ok"] = "ok"
    version: str
    data_mode: str
    sample_data: bool


class TransactionOut(_Out):
    id: int
    date: date
    description: str
    amount: Decimal = Field(description="Signed: positive is money in, negative is money out.")
    direction: Direction
    currency: str
    account: str
    txn_type: TxnType
    type_basis: Basis
    category: str
    category_basis: Basis
    status: Status
    reference: str | None
    source: str
    import_batch_id: int | None
    source_file: str | None
    source_row: int | None
    duplicate_of_id: int | None = Field(
        default=None, description="Set when the user confirmed this record duplicates another."
    )

    @classmethod
    def from_record(cls, r: TransactionRecord) -> TransactionOut:
        return cls(
            id=r.id,
            date=r.occurred_on,
            description=r.description,
            amount=signed_amount(r),
            direction=Direction(r.direction),
            currency=r.currency,
            account=r.account.name,
            txn_type=TxnType(r.txn_type),
            type_basis=Basis(r.type_basis),
            category=r.category,
            category_basis=Basis(r.category_basis),
            status=Status(r.status),
            reference=r.external_id,
            source=r.source,
            import_batch_id=r.import_batch_id,
            source_file=r.source_file,
            source_row=r.source_row,
            duplicate_of_id=r.duplicate_of_id,
        )


class TransactionPage(_Out):
    total: int
    limit: int
    offset: int
    items: list[TransactionOut]


class ManualTransactionIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    date: date
    description: str = Field(min_length=1, max_length=500)
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2, description="Positive; see direction.")
    direction: Direction
    currency: str = Field(default="INR", pattern=r"^[A-Za-z]{3}$")
    account: str = Field(default="Cash", min_length=1, max_length=100)
    txn_type: TxnType | None = None
    category: str | None = Field(default=None, min_length=1, max_length=100)


class ManualTransactionOut(_Out):
    transaction: TransactionOut
    warnings: list[str]


class TransactionCorrectionIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    txn_type: TxnType | None = None
    category: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def _something_to_change(self) -> TransactionCorrectionIn:
        if self.txn_type is None and self.category is None:
            raise ValueError("provide txn_type and/or category")
        return self


class AuditEventOut(_Out):
    occurred_at: datetime
    actor: str
    action: str
    details: dict[str, Any]


class ImportBatchOut(_Out):
    id: int
    filename: str
    status: str
    created_at: datetime
    committed_at: datetime | None
    total_rows: int
    blank_rows: int
    rejected_rows: int
    new_rows: int
    suspected_rows: int
    duplicate_rows: int
    inserted_rows: int
    warnings: list[str] = []

    @classmethod
    def from_batch(cls, b: ImportBatch, warnings: list[str] | None = None) -> ImportBatchOut:
        fields = {name: getattr(b, name) for name in cls.model_fields if name != "warnings"}
        return cls(**fields, warnings=warnings or [])


class ImportRowOut(_Out):
    source_row: int
    outcome: str
    reason: str | None
    transaction: dict[str, Any] | None
    raw: dict[str, Any] | None

    @classmethod
    def from_row(cls, r: ImportRow) -> ImportRowOut:
        return cls(
            source_row=r.source_row, outcome=r.outcome, reason=r.reason, transaction=r.payload, raw=r.raw
        )


class ImportDetailOut(_Out):
    batch: ImportBatchOut
    rows: list[ImportRowOut]


class AccountOut(_Out):
    id: int
    name: str
    kind: str
    currency: str

    @classmethod
    def from_account(cls, a: Account) -> AccountOut:
        return cls(id=a.id, name=a.name, kind=a.kind, currency=a.currency)


class SummaryOut(_Out):
    note: str = RECORDED_TOTALS_NOTE
    sample_data: bool
    open_duplicate_reviews: int
    warnings: list[str]
    currencies: dict[str, dict[str, Any]]


class DuplicateCandidateOut(_Out):
    id: int
    score: int = Field(description="0-100, from hand-chosen weights; not a calibrated probability.")
    confidence: Literal["high", "medium"]
    reasons: list[str]
    status: Literal["open", "duplicate", "distinct", "superseded"]
    kept_transaction_id: int | None
    transactions: list[TransactionOut]

    @classmethod
    def from_candidate(cls, c: MatchCandidate) -> DuplicateCandidateOut:
        return cls(
            id=c.id,
            score=c.score,
            confidence="high" if c.score >= 80 else "medium",
            reasons=c.reasons,
            status=c.status,
            kept_transaction_id=c.kept_id,
            transactions=[TransactionOut.from_record(c.transaction_a), TransactionOut.from_record(c.transaction_b)],
        )


class DuplicateDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["duplicate", "distinct"]
    keep_transaction_id: int | None = Field(
        default=None, description="Required for 'duplicate': which of the two records to keep."
    )

    @model_validator(mode="after")
    def _keep_matches_decision(self) -> DuplicateDecisionIn:
        if self.decision == "duplicate" and self.keep_transaction_id is None:
            raise ValueError("keep_transaction_id is required when decision is 'duplicate'")
        if self.decision == "distinct" and self.keep_transaction_id is not None:
            raise ValueError("keep_transaction_id only applies to duplicates")
        return self


class ScanOut(_Out):
    new_candidates: int
