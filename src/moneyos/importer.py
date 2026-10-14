"""Read bank/card CSV exports into Transactions.

Banks disagree on column names and on how they express direction (one signed
column, separate debit/credit columns, or an amount plus a DR/CR type).
This module maps those layouts onto one model. Rows that cannot be parsed
are returned as RejectedRow with a reason; they are never dropped silently.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from moneyos.cleaning import CleaningError, clean_description, parse_amount, parse_date
from moneyos.models import UNCATEGORIZED, RejectedRow, Transaction


class SchemaError(ValueError):
    """The file's header does not contain the columns needed to import it."""


_ALIASES: dict[str, tuple[str, ...]] = {
    "date": ("date", "transaction date", "txn date", "posting date", "posted date", "value date"),
    "description": ("description", "narration", "details", "memo", "payee", "particulars", "merchant"),
    "amount": ("amount", "amount inr", "amount usd", "transaction amount"),
    "debit": ("debit", "debit amount", "withdrawal", "withdrawal amt", "money out", "paid out"),
    "credit": ("credit", "credit amount", "deposit", "deposit amt", "money in", "paid in"),
    "type": ("type", "transaction type", "dr cr", "cr dr"),
    "currency": ("currency",),
    "account": ("account", "account name", "account number"),
    "category": ("category",),
    "reference": ("reference", "ref", "ref no", "reference no", "transaction id", "id", "utr", "chq ref no"),
}
_DEBIT_TYPES = {"dr", "debit", "withdrawal"}
_CREDIT_TYPES = {"cr", "credit", "deposit"}
_EMPTY_REFERENCES = {"", "0", "-", "na", "n/a", "nil", "none"}


@dataclass(slots=True)
class FileImport:
    source_file: str
    transactions: list[Transaction] = field(default_factory=list)
    rejected: list[RejectedRow] = field(default_factory=list)
    blank_rows: int = 0


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


def _signed_amount(get) -> Decimal:
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


def _open_text(path: Path):
    try:
        with path.open(encoding="utf-8-sig") as probe:
            probe.read()
        return path.open(encoding="utf-8-sig", newline="")
    except UnicodeDecodeError:
        return path.open(encoding="cp1252", newline="")


def import_csv(
    path: str | Path,
    *,
    account: str | None = None,
    default_currency: str = "INR",
    day_first: bool = True,
) -> FileImport:
    """Import one CSV file.

    ``account`` names the account for files without an account column; it
    defaults to the file name without extension.
    """
    path = Path(path)
    result = FileImport(source_file=path.name)
    fallback_account = account or path.stem

    with _open_text(path) as handle:
        reader = csv.DictReader(handle)
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
                reference = get("reference")
                transaction = Transaction(
                    date=parse_date(get("date"), day_first=day_first),
                    description=description,
                    amount=_signed_amount(get),
                    currency=(get("currency") or default_currency).upper(),
                    account=get("account") or fallback_account,
                    category=clean_description(get("category")) or UNCATEGORIZED,
                    reference=None if reference.casefold() in _EMPTY_REFERENCES else reference,
                    raw_description=get("description"),
                    source_file=path.name,
                    source_row=reader.line_num,
                )
            except CleaningError as error:
                result.rejected.append(
                    RejectedRow(path.name, reader.line_num, str(error), raw)
                )
                continue
            result.transactions.append(transaction)

    return result
