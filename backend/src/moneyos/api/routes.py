"""HTTP routes under /api/v1. Each handler delegates to a service function."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.orm import Session

from moneyos.api.deps import get_rules, get_session, get_settings
from moneyos.api.schemas import (
    AccountOut,
    AuditEventOut,
    ImportBatchOut,
    ImportDetailOut,
    ImportRowOut,
    ManualTransactionIn,
    ManualTransactionOut,
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
from moneyos.services import imports, ledger
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
    file: Annotated[UploadFile, File(description="Statement CSV")],
    account: Annotated[str | None, Form(max_length=100)] = None,
    currency: Annotated[str, Form(pattern=r"^[A-Za-z]{3}$")] = "INR",
    day_first: Annotated[bool, Form()] = True,
) -> ImportDetailOut:
    """Parse a CSV and stage it. Nothing is added to the ledger until commit."""
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
) -> ledger.TransactionFilter:
    return ledger.TransactionFilter(start, end, account, currency, txn_type, category)


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
    return SummaryOut(
        sample_data=settings.data_mode == DataMode.SAMPLE,
        currencies={currency: summary_dict(s) for currency, s in summaries.items()},
    )


@router.get("/accounts", response_model=list[AccountOut], tags=["accounts"])
def list_accounts(session: SessionDep) -> list[AccountOut]:
    return [AccountOut.from_account(a) for a in ledger.list_accounts(session)]
