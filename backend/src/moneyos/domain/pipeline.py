"""File-based import: read -> clean -> classify -> de-duplicate -> summarise.

Used by the command line. The API goes through ``moneyos.services.imports``,
which runs the same steps against the database.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from moneyos.domain.classify import Rules, classify, load_rules
from moneyos.domain.dedupe import deduplicate
from moneyos.domain.importer import FileImport, import_csv
from moneyos.domain.matching import MatchScore, find_candidates
from moneyos.domain.models import RejectedRow, Transaction
from moneyos.domain.summary import LedgerSummary, summarize_by_currency


@dataclass(slots=True)
class PipelineResult:
    files: list[FileImport] = field(default_factory=list)
    transactions: list[Transaction] = field(default_factory=list)
    duplicates: list[Transaction] = field(default_factory=list)
    suspected_duplicates: list[Transaction] = field(default_factory=list)
    rejected: list[RejectedRow] = field(default_factory=list)
    summaries: dict[str, LedgerSummary] = field(default_factory=dict)
    # Possible duplicates the exact rules could not settle. Not removed.
    candidates: list[tuple[Transaction, Transaction, MatchScore]] = field(default_factory=list)


def run_pipeline(
    paths: Iterable[str | Path],
    *,
    account: str | None = None,
    default_currency: str = "INR",
    day_first: bool = True,
    existing: Iterable[Transaction] = (),
    rules: Rules | None = None,
) -> PipelineResult:
    """Import the given CSV files in order and return the combined result."""
    rules = rules or load_rules()
    files = [
        import_csv(p, account=account, default_currency=default_currency, day_first=day_first)
        for p in paths
    ]
    for imported in files:
        imported.transactions = [classify(t, rules) for t in imported.transactions]

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
        candidates=[
            (transactions[a], transactions[b], score)
            for a, b, score in find_candidates(list(enumerate(transactions)))
        ],
    )
