"""Analytics over the stored ledger: loads data, then calls moneyos.analytics."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from moneyos.analytics.aggregate import Granularity, cash_flow_series
from moneyos.analytics.coverage import AccountCoverage, build_coverage
from moneyos.analytics.frame import transactions_frame
from moneyos.analytics.quality import QualityReport, quality_report
from moneyos.analytics.stats import SpendingStats, spending_stats
from moneyos.db.tables import ImportBatch, ImportRow, TransactionRecord
from moneyos.services import review
from moneyos.services.errors import InvalidRequestError
from moneyos.services.mapping import to_domain


def currencies(session: Session) -> list[str]:
    return list(
        session.scalars(
            select(TransactionRecord.currency)
            .where(TransactionRecord.duplicate_of_id.is_(None))
            .group_by(TransactionRecord.currency)
            .order_by(func.count().desc())
        )
    )


def resolve_currency(session: Session, currency: str | None) -> str | None:
    """The requested currency, or the only one in the ledger. Amounts in
    different currencies are never added together."""
    present = currencies(session)
    if currency:
        return currency.upper()
    if len(present) > 1:
        raise InvalidRequestError(f"the ledger has several currencies ({', '.join(present)}); choose one")
    return present[0] if present else None


def ledger_frame(session: Session, currency: str | None, start: date | None = None, end: date | None = None) -> pd.DataFrame:
    """Active transactions (confirmed duplicates excluded) as a DataFrame."""
    query = (
        select(TransactionRecord)
        .where(TransactionRecord.duplicate_of_id.is_(None))
        .options(selectinload(TransactionRecord.account))
    )
    if currency:
        query = query.where(TransactionRecord.currency == currency)
    if start:
        query = query.where(TransactionRecord.occurred_on >= start)
    if end:
        query = query.where(TransactionRecord.occurred_on <= end)
    return transactions_frame(to_domain(r) for r in session.scalars(query))


def coverage(session: Session) -> dict[str, AccountCoverage]:
    """Coverage from every valid row of every committed import, duplicates
    included: re-importing a file is still evidence about that period."""
    spans: dict[tuple[int, str], list[date]] = defaultdict(list)
    rows = session.execute(
        select(ImportRow.batch_id, ImportRow.payload)
        .join(ImportBatch)
        .where(ImportBatch.status == "committed", ImportRow.outcome != "rejected")
    )
    for batch_id, payload in rows:
        spans[(batch_id, payload["account"])].append(date.fromisoformat(payload["date"]))
    return build_coverage((account, min(days), max(days)) for (_, account), days in spans.items())


def quality(session: Session, currency: str | None) -> QualityReport:
    frame = ledger_frame(session, currency)
    # The same bad row in a re-imported file is one problem, not two.
    rejected = session.scalar(
        select(func.count()).select_from(
            select(ImportBatch.file_sha256, ImportRow.source_row)
            .join(ImportBatch)
            .where(ImportBatch.status == "committed", ImportRow.outcome == "rejected")
            .distinct()
            .subquery()
        )
    )
    confirmed = session.scalar(
        select(func.count()).select_from(TransactionRecord).where(TransactionRecord.duplicate_of_id.is_not(None))
    )
    return quality_report(
        frame,
        coverage(session),
        rejected_rows=int(rejected),
        confirmed_duplicates=int(confirmed),
        open_duplicate_reviews=review.count_open(session),
    )


def _range(frame: pd.DataFrame, start: date | None, end: date | None) -> tuple[date, date] | None:
    if frame.empty and (start is None or end is None):
        return None
    start = start or frame["date"].min().date()
    end = end or frame["date"].max().date()
    if start > end:
        raise InvalidRequestError("start must not be after end")
    return start, end


def cash_flow(
    session: Session, granularity: Granularity, currency: str | None, start: date | None, end: date | None
) -> tuple[str | None, pd.DataFrame]:
    currency = resolve_currency(session, currency)
    frame = ledger_frame(session, currency, start, end)
    bounds = _range(frame, start, end)
    if bounds is None:
        return currency, pd.DataFrame()
    return currency, cash_flow_series(frame, granularity, *bounds, coverage(session))


def spending(session: Session, currency: str | None, start: date | None, end: date | None) -> SpendingStats | None:
    currency = resolve_currency(session, currency)
    frame = ledger_frame(session, currency, start, end)
    bounds = _range(frame, start, end)
    if bounds is None:
        return None
    days = pd.date_range(*bounds, freq="D")
    cover = coverage(session)
    covered = days[[any(c.covers(d.date()) for c in cover.values()) for d in days]] if cover else days
    return spending_stats(frame, covered_days=covered)
