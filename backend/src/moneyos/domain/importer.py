"""Read bank/card CSV exports into Transactions.

Banks disagree on column names and on how they express direction (one signed
column, separate debit/credit columns, or an amount plus a DR/CR type).
This module maps those layouts onto one model. Rows that cannot be parsed
are returned as RejectedRow with a reason; they are never dropped silently.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import TextIO

from moneyos.domain.cleaning import (
    CleaningError,
    clean_description,
    parse_amount,
    parse_date,
)
from moneyos.domain.models import UNCATEGORIZED, Basis, RejectedRow, Status, Transaction
from moneyos.domain.money import to_minor


class SchemaError(ValueError):
    """The file's header does not contain the columns needed to import it."""


_ALIASES: dict[str, tuple[str, ...]] = {
    "date": ("date", "transaction date", "txn date", "posting date", "posted date", "value date"),
    "description": (
        "description", "narration", "details", "memo", "payee", "particulars", "merchant",
        "counterparty", "paid to received from",
    ),
    "amount": ("amount", "amount inr", "amount usd", "transaction amount"),
    "debit": ("debit", "debit amount", "withdrawal", "withdrawal amt", "money out", "paid out"),
    "credit": ("credit", "credit amount", "deposit", "deposit amt", "money in", "paid in"),
    "type": ("type", "dr cr", "cr dr", "debit credit"),
    "status": ("status", "transaction status", "txn status"),
    "currency": ("currency",),
    "account": ("account", "account name", "account number"),
    "category": ("category",),
    "reference": (
        "reference", "ref", "ref no", "reference no", "transaction id", "id", "utr", "chq ref no",
        "upi ref no", "upi transaction id",
    ),
}
_DEBIT_TYPES = {"dr", "debit", "withdrawal"}
_CREDIT_TYPES = {"cr", "credit", "deposit"}
_EMPTY_REFERENCES = {"", "0", "-", "na", "n/a", "nil", "none"}
_STATUSES = {
    "posted": Status.POSTED,
    "success": Status.POSTED,
    "successful": Status.POSTED,
    "completed": Status.POSTED,
    "settled": Status.POSTED,
    "pending": Status.PENDING,
    "processing": Status.PENDING,
    "failed": Status.FAILED,
    "declined": Status.FAILED,
    "reversed": Status.REVERSED,
    "refunded": Status.REVERSED,
    "unknown": Status.UNKNOWN,
}
MAX_IMPORT_BYTES = 5 * 1024 * 1024


@dataclass(slots=True)
class FileImport:
    source_file: str
    transactions: list[Transaction] = field(default_factory=list)
    rejected: list[RejectedRow] = field(default_factory=list)
    blank_rows: int = 0

    @property
    def total_rows(self) -> int:
        return len(self.transactions) + len(self.rejected) + self.blank_rows


def _normalize_header(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", header.casefold()).strip()


def map_columns(fieldnames: list[str] | None) -> dict[str, str]:
    """Map canonical field names to the header actually used in the file."""
    if not fieldnames:
        raise SchemaError("file has no header row")
    by_normalized = {_normalize_header(h): h for h in fieldnames if h}
    mapping = {}
    for canonical, aliases in _ALIASES.items():
        for alias in aliases:
            if alias in by_normalized:
                mapping[canonical] = by_normalized[alias]
                break

    missing = [f for f in ("date", "description") if f not in mapping]
    if "amount" not in mapping and not ({"debit", "credit"} & mapping.keys()):
        missing.append("amount (or debit/credit)")
    if missing:
        raise SchemaError(
            f"missing required column(s): {', '.join(missing)}; found: {', '.join(fieldnames)}"
        )
    return mapping


def _signed_amount(get: Callable[[str], str]) -> Decimal:
    debit, credit = get("debit"), get("credit")
    if debit or credit:
        debit_value = abs(parse_amount(debit)) if debit else Decimal(0)
        credit_value = abs(parse_amount(credit)) if credit else Decimal(0)
        if debit_value and credit_value:
            raise CleaningError("both debit and credit are filled in")
        amount = credit_value - debit_value
    else:
        amount = parse_amount(get("amount"))
        kind = get("type").casefold().rstrip(".")
        if kind in _DEBIT_TYPES:
            amount = -abs(amount)
        elif kind in _CREDIT_TYPES:
            amount = abs(amount)
    if amount == 0:
        raise CleaningError("zero amount")
    return amount


def _parse_status(text: str) -> Status:
    if not text:
        return Status.UNKNOWN
    status = _STATUSES.get(text.casefold())
    if status is None:
        raise CleaningError(f"unrecognised status: {text!r}")
    return status


def decode_bytes(content: bytes) -> str:
    """Decode an uploaded file: UTF-8 (with or without BOM), else Windows-1252."""
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("cp1252")


def import_text(
    stream: TextIO,
    source_file: str,
    *,
    account: str | None = None,
    default_currency: str = "INR",
    day_first: bool = True,
) -> FileImport:
    """Import CSV text.

    ``account`` names the account for files without an account column; it
    defaults to the file name without extension.
    """
    result = FileImport(source_file=source_file)
    fallback_account = account or Path(source_file).stem
    reader = csv.DictReader(stream)
    columns = map_columns(reader.fieldnames)

    for row in reader:
        def get(field_name: str) -> str:
            header = columns.get(field_name)
            return (row.get(header) or "").strip() if header else ""

        raw = {k: v for k, v in row.items() if isinstance(k, str) and isinstance(v, str)}
        if not any(v.strip() for v in raw.values()):
            result.blank_rows += 1
            continue

        try:
            description = clean_description(get("description"))
            if not description:
                raise CleaningError("missing description")
            amount = _signed_amount(get)
            currency = (get("currency") or default_currency).upper()
            try:
                to_minor(amount, currency)
            except ValueError as error:
                raise CleaningError(str(error)) from None
            category = clean_description(get("category"))
            if category.casefold() == UNCATEGORIZED.casefold():
                category = ""
            reference = get("reference")
            transaction = Transaction(
                date=parse_date(get("date"), day_first=day_first),
                description=description,
                amount=amount,
                currency=currency,
                account=get("account") or fallback_account,
                category=category or UNCATEGORIZED,
                category_basis=Basis.SOURCE if category else Basis.NONE,
                status=_parse_status(get("status")),
                reference=None if reference.casefold() in _EMPTY_REFERENCES else reference,
                raw_description=get("description"),
                source_file=source_file,
                source_row=reader.line_num,
            )
        except CleaningError as error:
            result.rejected.append(RejectedRow(source_file, reader.line_num, str(error), raw))
            continue
        result.transactions.append(transaction)

    return result


def import_csv(
    path: str | Path,
    *,
    account: str | None = None,
    default_currency: str = "INR",
    day_first: bool = True,
) -> FileImport:
    """Import one CSV file from disk."""
    path = Path(path)
    return import_text(
        io.StringIO(decode_bytes(path.read_bytes()), newline=""),
        path.name,
        account=account,
        default_currency=default_currency,
        day_first=day_first,
    )
