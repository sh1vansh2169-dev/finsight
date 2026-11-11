"""Data-quality report: what is missing, inferred, uncertain or uncovered.

Four different kinds of "missing" are kept apart, because they mean
different things and have different fixes:

* missing *fields* in recorded transactions (no category, unknown type)
* missing *records* inside a covered period cannot be detected from the data
  alone and are not claimed here
* *gaps between imported periods* for an account (a statement never imported)
* *uncovered sources*: accounts with only manual entries, e.g. cash
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from moneyos.analytics.coverage import AccountCoverage
from moneyos.domain.models import UNCATEGORIZED, Basis, Status, TxnType


@dataclass(frozen=True, slots=True)
class FieldGap:
    field: str
    missing: int
    total: int
    meaning: str  # completes "N of M transactions ..."
    actionable: bool  # can the user fix it? Only these become warnings.

    @property
    def share(self) -> float:
        return self.missing / self.total if self.total else 0.0


@dataclass(frozen=True, slots=True)
class QualityReport:
    transactions: int
    field_gaps: tuple[FieldGap, ...]
    # How the transaction type was decided: basis -> count.
    type_basis: dict[str, int]
    coverage: dict[str, AccountCoverage]
    uncovered_accounts: tuple[str, ...]  # only manual entries; no statement evidence
    rejected_rows: int = 0
    confirmed_duplicates: int = 0
    open_duplicate_reviews: int = 0
    warnings: tuple[str, ...] = field(default=())


def quality_report(
    frame: pd.DataFrame,
    coverage: dict[str, AccountCoverage],
    *,
    rejected_rows: int = 0,
    confirmed_duplicates: int = 0,
    open_duplicate_reviews: int = 0,
) -> QualityReport:
    total = len(frame)
    expenses = frame["txn_type"] == TxnType.EXPENSE.value
    gaps = (
        FieldGap("txn_type", int((frame["txn_type"] == TxnType.UNKNOWN.value).sum()), total,
                 "have an unknown type, so they count as unclassified rather than income or spending",
                 actionable=True),
        FieldGap("category", int((expenses & (frame["category"] == UNCATEGORIZED)).sum()), int(expenses.sum()),
                 "spending payments have no category", actionable=True),
        FieldGap("status", int((frame["status"] == Status.UNKNOWN.value).sum()), total,
                 "do not say whether the payment completed", actionable=False),
        FieldGap("reference", int(frame["reference"].isna().sum()), total,
                 "have no bank reference, so duplicates can only be matched by their details", actionable=False),
    )
    type_basis = {b.value: int((frame["type_basis"] == b.value).sum()) for b in Basis}
    accounts = set(frame["account"].dropna().unique())
    uncovered = tuple(sorted(accounts - set(coverage)))

    warnings = []
    for account, c in coverage.items():
        for gap in c.gaps:
            warnings.append(
                f"{account}: no statement imported for {gap.start:%d %b %Y} to {gap.end:%d %b %Y} "
                f"({gap.days} days). Totals for that time are incomplete."
            )
    for account in uncovered:
        warnings.append(
            f"{account} has only manually entered records, so there is no way to tell what is missing."
        )
    if open_duplicate_reviews:
        warnings.append(
            f"{open_duplicate_reviews} possible duplicate pair(s) await review; totals may count them twice."
        )
    if rejected_rows:
        warnings.append(f"{rejected_rows} imported row(s) were rejected and are not in any total.")
    for gap in gaps:
        if gap.missing and gap.actionable:
            noun = "" if gap.field == "category" else " transactions"
            warnings.append(f"{gap.missing} of {gap.total}{noun} {gap.meaning}.")

    return QualityReport(
        transactions=total,
        field_gaps=gaps,
        type_basis=type_basis,
        coverage=coverage,
        uncovered_accounts=uncovered,
        rejected_rows=rejected_rows,
        confirmed_duplicates=confirmed_duplicates,
        open_duplicate_reviews=open_duplicate_reviews,
        warnings=tuple(warnings),
    )
