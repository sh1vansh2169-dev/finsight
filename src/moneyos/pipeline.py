"""End-to-end import: read -> clean -> categorise -> de-duplicate -> summarise."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from moneyos.categorize import categorize
from moneyos.dedupe import deduplicate
from moneyos.importer import FileImport, import_csv
from moneyos.models import RejectedRow, Transaction
from moneyos.summary import Summary, summarize_by_currency


@dataclass(slots=True)
class PipelineResult:
    files: list[FileImport] = field(default_factory=list)
    transactions: list[Transaction] = field(default_factory=list)
    duplicates: list[Transaction] = field(default_factory=list)
    suspected_duplicates: list[Transaction] = field(default_factory=list)
    rejected: list[RejectedRow] = field(default_factory=list)
    summaries: dict[str, Summary] = field(default_factory=dict)


def run_pipeline(
    paths: Iterable[str | Path],
    *,
    account: str | None = None,
    default_currency: str = "INR",
    day_first: bool = True,
    existing: Iterable[Transaction] = (),
) -> PipelineResult:
    """Import the given CSV files in order and return the combined result."""
    files = [
        import_csv(p, account=account, default_currency=default_currency, day_first=day_first)
        for p in paths
    ]
    for imported in files:
        imported.transactions = [categorize(t) for t in imported.transactions]

    deduped = deduplicate((f.transactions for f in files), existing=existing)
    transactions = sorted(
        deduped.unique, key=lambda t: (t.date, t.source_file, t.source_row)
    )
    return PipelineResult(
        files=files,
        transactions=transactions,
        duplicates=deduped.duplicates,
        suspected_duplicates=deduped.suspected,
        rejected=[r for f in files for r in f.rejected],
        summaries=summarize_by_currency(transactions),
    )
