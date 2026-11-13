"""HTTP routes under /api/v1. Each handler delegates to a service function."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from sqlalchemy.orm import Session

from moneyos.api.deps import get_rules, get_session, get_settings
from moneyos.api.schemas import (
    AccountOut,
    AuditEventOut,
    DuplicateCandidateOut,
    DuplicateDecisionIn,
    ImportBatchOut,
    ImportDetailOut,
    ImportRowOut,
    ManualTransactionIn,
    ManualTransactionOut,
    ScanOut,
    SummaryOut,
    TransactionCorrectionIn,
    TransactionOut,
    TransactionPage,
)
from moneyos.config import DataMode, Settings
from moneyos.domain.classify import Rules
from moneyos.domain.importer import MAX_IMPORT_BYTES
from moneyos.domain.models import TxnType
from moneyos.domain.report import summary_dict
from moneyos.services import imports, ledger, review
from moneyos.services.errors import PayloadTooLargeError

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]
RulesDep = Annotated[Rules, Depends(get_rules)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _batch_out(session: Session, batch) -> ImportBatchOut:
    warnings = []
    if earlier := imports.same_file_imports(session, batch):
        ids = ", ".join(str(i) for i in earlier)
        warnings.append(f"This exact file was already imported (import {ids}).")
    if batch.suspected_rows:
        warnings.append(f"{batch.suspected_rows} row(s) are identical to another row in the file; please review.")
    if batch.status == "committed":
        if pending := review.count_open(session, imports.batch_transaction_ids(session, batch.id)):
            warnings.append(f"{pending} possible duplicate pair(s) involve this import; see the review list.")
    return ImportBatchOut.from_batch(batch, warnings)


def _detail(session: Session, batch) -> ImportDetailOut:
    return ImportDetailOut(
        batch=_batch_out(session, batch), rows=[ImportRowOut.from_row(r) for r in batch.rows]
    )


# ------------------------------------------------------------------ imports


@router.post("/imports/preview", response_model=ImportDetailOut, status_code=status.HTTP_201_CREATED, tags=["imports"])
async def preview_import(
    session: SessionDep,
    rules: RulesDep,
    file: Annotated[UploadFile, File(description="Statement: CSV, Excel .xlsx or text PDF")],
    account: Annotated[str | None, Form(max_length=100)] = None,
    currency: Annotated[str, Form(pattern=r"^[A-Za-z]{3}$")] = "INR",
    day_first: Annotated[bool, Form()] = True,
) -> ImportDetailOut:
    """Parse a CSV, Excel or PDF statement and stage it. Nothing is added to the ledger until commit."""
    content = await file.read(MAX_IMPORT_BYTES + 1)
    if len(content) > MAX_IMPORT_BYTES:
        raise PayloadTooLargeError(f"file is larger than {MAX_IMPORT_BYTES // (1024 * 1024)} MB")
    batch = imports.preview_import(
        session,
        filename=file.filename or "upload.csv",
        content=content,
        options=imports.ImportOptions(account=account or None, default_currency=currency, day_first=day_first),
        rules=rules,
    )
    return _detail(session, batch)


@router.post("/imports/{batch_id}/commit", response_model=ImportBatchOut, tags=["imports"])
def commit_import(batch_id: int, session: SessionDep) -> ImportBatchOut:
    return _batch_out(session, imports.commit_import(session, batch_id))


@router.post("/imports/{batch_id}/discard", response_model=ImportBatchOut, tags=["imports"])
def discard_import(batch_id: int, session: SessionDep) -> ImportBatchOut:
    return _batch_out(session, imports.discard_import(session, batch_id))


@router.get("/imports", response_model=list[ImportBatchOut], tags=["imports"])
def list_imports(session: SessionDep) -> list[ImportBatchOut]:
    return [_batch_out(session, b) for b in imports.list_batches(session)]


@router.get("/imports/inbox", tags=["imports"])
def inbox_status(request: Request, settings: SettingsDep) -> dict:
    """Whether the statement inbox is on, where it is, and what the last scan found."""
    watcher = getattr(request.app.state, "inbox_watcher", None)
    last = watcher.last if watcher else None
    return {
        "enabled": settings.watch_dir is not None,
        "folder": str(settings.watch_dir.resolve()) if settings.watch_dir else None,
        "note": last.note if last else None,
        "waiting": last.waiting if last else [],
    }


@router.get("/imports/{batch_id}", response_model=ImportDetailOut, tags=["imports"])
def get_import(batch_id: int, session: SessionDep) -> ImportDetailOut:
    return _detail(session, imports.get_batch(session, batch_id))


# ------------------------------------------------------------- transactions


def _filter(
    start: date | None = None,
    end: date | None = None,
    account: str | None = None,
    currency: str | None = None,
    txn_type: TxnType | None = None,
    category: str | None = None,
    include_duplicates: bool = False,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> ledger.TransactionFilter:
    return ledger.TransactionFilter(start, end, account, currency, txn_type, category, include_duplicates,
                                    q.strip() if q and q.strip() else None)


FilterDep = Annotated[ledger.TransactionFilter, Depends(_filter)]


@router.get("/transactions", response_model=TransactionPage, tags=["transactions"])
def list_transactions(
    session: SessionDep,
    f: FilterDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TransactionPage:
    records, total = ledger.list_transactions(session, f, limit=limit, offset=offset)
    return TransactionPage(
        total=total, limit=limit, offset=offset, items=[TransactionOut.from_record(r) for r in records]
    )


@router.post("/transactions", response_model=ManualTransactionOut, status_code=status.HTTP_201_CREATED, tags=["transactions"])
def create_transaction(body: ManualTransactionIn, session: SessionDep, rules: RulesDep) -> ManualTransactionOut:
    """Manual entry, e.g. a cash payment that no statement will ever show."""
    record, warnings = ledger.create_manual(
        session,
        occurred_on=body.date,
        description=body.description,
        amount=body.amount,
        direction=body.direction,
        currency=body.currency,
        account=body.account,
        txn_type=body.txn_type,
        category=body.category,
        rules=rules,
    )
    return ManualTransactionOut(transaction=TransactionOut.from_record(record), warnings=warnings)


@router.get("/transactions/{transaction_id}", response_model=TransactionOut, tags=["transactions"])
def get_transaction(transaction_id: int, session: SessionDep) -> TransactionOut:
    return TransactionOut.from_record(ledger.get_transaction(session, transaction_id))


@router.patch("/transactions/{transaction_id}", response_model=TransactionOut, tags=["transactions"])
def correct_transaction(transaction_id: int, body: TransactionCorrectionIn, session: SessionDep) -> TransactionOut:
    """Correct the type and/or category. The change is recorded in the audit trail."""
    record = ledger.correct_transaction(
        session, transaction_id, txn_type=body.txn_type, category=body.category
    )
    return TransactionOut.from_record(record)


@router.get("/transactions/{transaction_id}/audit", response_model=list[AuditEventOut], tags=["transactions"])
def transaction_audit(transaction_id: int, session: SessionDep) -> list[AuditEventOut]:
    ledger.get_transaction(session, transaction_id)
    return [
        AuditEventOut(occurred_at=e.occurred_at, actor=e.actor, action=e.action, details=e.details)
        for e in ledger.audit_trail(session, "transaction", transaction_id)
    ]


# ---------------------------------------------------------------- summaries


@router.get("/summary", response_model=SummaryOut, tags=["summary"])
def summary(session: SessionDep, f: FilterDep, settings: SettingsDep) -> SummaryOut:
    summaries = ledger.summarize_ledger(session, f)
    pending = review.count_open(session)
    warnings = []
    if pending:
        warnings.append(
            f"{pending} pair(s) of transactions may be the same payment recorded twice. "
            "Until they are reviewed, these totals may count them twice."
        )
    return SummaryOut(
        sample_data=settings.data_mode == DataMode.SAMPLE,
        open_duplicate_reviews=pending,
        warnings=warnings,
        currencies={currency: summary_dict(s) for currency, s in summaries.items()},
    )


# ------------------------------------------------------------ duplicate review


@router.get("/review/duplicates", response_model=list[DuplicateCandidateOut], tags=["review"])
def list_duplicate_candidates(
    session: SessionDep,
    status: Annotated[Literal["open", "duplicate", "distinct", "superseded", "all"], Query()] = "open",
) -> list[DuplicateCandidateOut]:
    """Pairs that may be the same payment, highest score first."""
    candidates = review.list_candidates(session, None if status == "all" else status)
    return [DuplicateCandidateOut.from_candidate(c) for c in candidates]


@router.post("/review/duplicates/scan", response_model=ScanOut, tags=["review"])
def scan_for_duplicates(session: SessionDep) -> ScanOut:
    """Look for new possible duplicates across the whole ledger."""
    return ScanOut(new_candidates=review.scan(session))


@router.post("/review/duplicates/{candidate_id}/resolve", response_model=DuplicateCandidateOut, tags=["review"])
def resolve_duplicate_candidate(
    candidate_id: int, body: DuplicateDecisionIn, session: SessionDep
) -> DuplicateCandidateOut:
    """Confirm a pair as one payment (keeping one record) or as two separate payments."""
    candidate = review.resolve(
        session, candidate_id, duplicate=body.decision == "duplicate", keep_id=body.keep_transaction_id
    )
    return DuplicateCandidateOut.from_candidate(candidate)


@router.post("/review/duplicates/{candidate_id}/reopen", response_model=DuplicateCandidateOut, tags=["review"])
def reopen_duplicate_candidate(candidate_id: int, session: SessionDep) -> DuplicateCandidateOut:
    """Undo a decision."""
    return DuplicateCandidateOut.from_candidate(review.reopen(session, candidate_id))


@router.get("/categories", tags=["transactions"])
def categories(session: SessionDep, rules: RulesDep) -> list[str]:
    """Every category in use or known to the rules, for pickers and filters."""
    return ledger.categories(session, rules)


@router.get("/accounts", response_model=list[AccountOut], tags=["accounts"])
def list_accounts(session: SessionDep) -> list[AccountOut]:
    return [AccountOut.from_account(a) for a in ledger.list_accounts(session)]
