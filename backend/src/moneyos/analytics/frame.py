"""Turn domain transactions into a typed DataFrame."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

import pandas as pd

from moneyos.domain.models import Status, Transaction, TxnType
from moneyos.domain.money import from_minor, to_minor

COLUMNS = {
    "date": "datetime64[ns]",
    "account": "string",
    "currency": "string",
    "amount_minor": "int64",  # signed: positive is money in
    "txn_type": "string",
    "type_basis": "string",
    "category": "string",
    "category_basis": "string",
    "status": "string",
    "description": "string",
    "reference": "string",
}


def transactions_frame(transactions: Iterable[Transaction]) -> pd.DataFrame:
    rows = [
        {
            "date": t.date,
            "account": t.account,
            "currency": t.currency,
            "amount_minor": to_minor(t.amount, t.currency),
            "txn_type": t.txn_type.value,
            "type_basis": t.type_basis.value,
            "category": t.category,
            "category_basis": t.category_basis.value,
            "status": t.status.value,
            "description": t.description,
            "reference": t.reference,
        }
        for t in transactions
    ]
    frame = pd.DataFrame(rows, columns=list(COLUMNS))
    return frame.astype(COLUMNS)


def counted(frame: pd.DataFrame) -> pd.DataFrame:
    """Rows that move money and count towards totals: not failed, not own-account transfers."""
    return frame[(frame["status"] != Status.FAILED.value) & (frame["txn_type"] != TxnType.TRANSFER.value)]


def one_currency(frame: pd.DataFrame) -> str:
    currencies = frame["currency"].dropna().unique()
    if len(currencies) > 1:
        raise ValueError(f"cannot add up mixed currencies {sorted(currencies)}; filter by currency first")
    return str(currencies[0]) if len(currencies) else ""


def to_money(minor: int | float, currency: str) -> Decimal | None:
    """int64/NaN from pandas -> Decimal (None for missing)."""
    if pd.isna(minor):
        return None
    return from_minor(int(minor), currency)
