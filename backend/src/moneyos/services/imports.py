"""CSV import workflow: preview -> commit (or discard), with history.

Preview parses, validates, classifies and checks duplicates, then stages
every row with its outcome. Nothing reaches the ledger until commit, which
re-runs duplicate detection against the ledger as it is *then* (another
import may have been committed in between) inside one database transaction.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import PurePath

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from moneyos.db.tables import Account, AuditEvent, ImportBatch, ImportRow, TransactionRecord, utc_now
from moneyos.domain.classify import Rules, classify
from moneyos.domain.dedupe import deduplicate
from moneyos.domain.importer import MAX_IMPORT_BYTES
from moneyos.domain.statements import import_bytes
from moneyos.domain.models import Transaction
from moneyos.services import review
from moneyos.services.errors import ConflictError, NotFoundError, PayloadTooLargeError
from moneyos.services.mapping import from_payload, get_or_create_account, to_domain, to_payload, to_record

NEW, SUSPECTED, DUPLICATE, REJECTED = "new", "suspected", "duplicate", "rejected"


@dataclass(frozen=True, slots=True)
class ImportOptions:
    account: str | None = None
    default_currency: str = "INR"
    day_first: bool = True


def _existing_for(session: Session, accounts: set[str]) -> list[Transaction]:
    if not accounts:
        return []
    records = session.scalars(
        select(TransactionRecord)
        .join(Account)
        .where(Account.name.in_(accounts))
        .options(selectinload(TransactionRecord.account))
    )
    return [to_domain(r) for r in records]


def _outcomes(session: Session, transactions: list[Transaction]) -> list[tuple[str, str | None]]:
    """Classify each transaction as new, suspected or duplicate vs the ledger."""
    existing = _existing_for(session, {t.account for t in transactions})
    result = deduplicate([transactions], existing=existing)
    duplicate_ids = {id(t) for t in result.duplicates}
    suspected_ids = {id(t) for t in result.suspected}

    outcomes = []
    for t in transactions:
        if id(t) in duplicate_ids:
            reason = (
                f"reference {t.reference} is already recorded or repeated in this file"
                if t.reference
                else "same account, date, amount and description as a recorded transaction"
            )
            outcomes.append((DUPLICATE, reason))
        elif id(t) in suspected_ids:
            outcomes.append((SUSPECTED, "identical to an earlier row in this file; kept, please review"))
        else:
            outcomes.append((NEW, None))
    return outcomes


def _count(batch: ImportBatch) -> None:
    by_outcome = {NEW: 0, SUSPECTED: 0, DUPLICATE: 0, REJECTED: 0}
    for row in batch.rows:
        by_outcome[row.outcome] += 1
    batch.new_rows = by_outcome[NEW]
    batch.suspected_rows = by_outcome[SUSPECTED]
    batch.duplicate_rows = by_outcome[DUPLICATE]
    batch.rejected_rows = by_outcome[REJECTED]


def preview_import(
    session: Session,
    *,
    filename: str,
    content: bytes,
    options: ImportOptions,
    rules: Rules,
) -> ImportBatch:
    """Parse and stage a file. Raises SchemaError if the columns are unusable."""
    if len(content) > MAX_IMPORT_BYTES:
        raise PayloadTooLargeError(f"file is larger than {MAX_IMPORT_BYTES // (1024 * 1024)} MB")
    # Keep only the base name of whatever the client sent.
    filename = PurePath(filename.replace("\\", "/")).name[:255] or "upload.csv"

    imported = import_bytes(
        content,
        filename,
        account=options.account,
        default_currency=options.default_currency,
        day_first=options.day_first,
    )
    transactions = [classify(t, rules) for t in imported.transactions]

    batch = ImportBatch(
        filename=filename,
        file_sha256=hashlib.sha256(content).hexdigest(),
        status="previewed",
        account_override=options.account,
        default_currency=options.default_currency.upper(),
        day_first=options.day_first,
        total_rows=imported.total_rows,
        blank_rows=imported.blank_rows,
    )
    rows = [
        ImportRow(
            source_row=t.source_row, outcome=outcome, reason=reason, payload=to_payload(t),
            raw=imported.raw_rows.get(t.source_row),
        )
        for t, (outcome, reason) in zip(transactions, _outcomes(session, transactions))
    ]
    rows += [
        ImportRow(source_row=r.source_row, outcome=REJECTED, reason=r.reason, raw=r.raw)
        for r in imported.rejected
    ]
    batch.rows = sorted(rows, key=lambda r: r.source_row)
    _count(batch)
    session.add(batch)
    session.commit()
    return batch


def get_batch(session: Session, batch_id: int) -> ImportBatch:
    batch = session.get(ImportBatch, batch_id, options=[selectinload(ImportBatch.rows)])
    if batch is None:
        raise NotFoundError(f"import {batch_id} not found")
    return batch


def list_batches(session: Session) -> list[ImportBatch]:
    return list(session.scalars(select(ImportBatch).order_by(ImportBatch.id.desc())))


def same_file_imports(session: Session, batch: ImportBatch) -> list[int]:
    """Committed imports of byte-identical files, other than this one."""
    return list(
        session.scalars(
            select(ImportBatch.id).where(
                ImportBatch.file_sha256 == batch.file_sha256,
                ImportBatch.status == "committed",
                ImportBatch.id != batch.id,
            )
        )
    )


def commit_import(session: Session, batch_id: int) -> ImportBatch:
    """Write the batch's new and suspected rows to the ledger."""
    batch = get_batch(session, batch_id)
    if batch.status != "previewed":
        raise ConflictError(f"import {batch_id} is already {batch.status}")

    valid_rows = [r for r in batch.rows if r.outcome != REJECTED]
    transactions = [from_payload(r.payload) for r in valid_rows]
    accounts: dict[str, Account] = {}
    inserted = 0
    for row, t, (outcome, reason) in zip(valid_rows, transactions, _outcomes(session, transactions)):
        row.outcome, row.reason = outcome, reason
        if outcome == DUPLICATE:
            continue
        if t.account not in accounts:
            accounts[t.account] = get_or_create_account(session, t.account, t.currency)
        session.add(to_record(t, accounts[t.account], source="file_import", import_batch_id=batch.id))
        inserted += 1

    session.flush()
    # Near-duplicates of what was just added go to the review queue; they
    # stay in the ledger until the user decides.
    review.find_new_candidates(session)

    _count(batch)
    batch.inserted_rows = inserted
    batch.status = "committed"
    batch.committed_at = utc_now()
    session.add(
        AuditEvent(
            actor="user",
            action="import_committed",
            entity_type="import_batch",
            entity_id=batch.id,
            details={"inserted": inserted, "duplicates_skipped": batch.duplicate_rows},
        )
    )
    session.commit()
    return batch


def batch_transaction_ids(session: Session, batch_id: int) -> list[int]:
    return list(session.scalars(select(TransactionRecord.id).where(TransactionRecord.import_batch_id == batch_id)))


def discard_import(session: Session, batch_id: int) -> ImportBatch:
    """Drop a preview. Staged rows are deleted; the history entry stays."""
    batch = get_batch(session, batch_id)
    if batch.status != "previewed":
        raise ConflictError(f"import {batch_id} is already {batch.status}")
    batch.rows.clear()
    batch.status = "discarded"
    session.add(
        AuditEvent(actor="user", action="import_discarded", entity_type="import_batch", entity_id=batch.id)
    )
    session.commit()
    return batch
