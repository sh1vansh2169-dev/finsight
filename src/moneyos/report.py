"""Render a PipelineResult as text, JSON-ready data, or a cleaned CSV."""

from __future__ import annotations

import csv
from pathlib import Path

from moneyos.models import Transaction
from moneyos.pipeline import PipelineResult
from moneyos.summary import Summary

_EXPORT_FIELDS = (
    "date", "description", "amount", "currency", "account",
    "category", "reference", "source_file", "source_row",
)


def _money(value) -> str:
    return f"{value:,.2f}"


def _transaction_dict(t: Transaction) -> dict:
    return {
        "date": t.date.isoformat(),
        "description": t.description,
        "amount": str(t.amount),
        "currency": t.currency,
        "account": t.account,
        "category": t.category,
        "reference": t.reference or "",
        "source_file": t.source_file,
        "source_row": t.source_row,
    }


def _summary_dict(s: Summary) -> dict:
    return {
        "transaction_count": s.transaction_count,
        "start_date": s.start_date.isoformat() if s.start_date else None,
        "end_date": s.end_date.isoformat() if s.end_date else None,
        "income": str(s.totals.income),
        "expenses": str(s.totals.expenses),
        "net": str(s.totals.net),
        "transfers_in": str(s.transfers_in),
        "transfers_out": str(s.transfers_out),
        "by_month": {
            month: {"income": str(p.income), "expenses": str(p.expenses), "net": str(p.net)}
            for month, p in s.by_month.items()
        },
        "expenses_by_category": {c: str(v) for c, v in s.expenses_by_category.items()},
        "largest_expenses": [_transaction_dict(t) for t in s.largest_expenses],
    }


def to_dict(result: PipelineResult) -> dict:
    return {
        "files": [
            {
                "source_file": f.source_file,
                "parsed": len(f.transactions),
                "rejected": len(f.rejected),
                "blank_rows": f.blank_rows,
            }
            for f in result.files
        ],
        "transactions": [_transaction_dict(t) for t in result.transactions],
        "duplicates": [_transaction_dict(t) for t in result.duplicates],
        "suspected_duplicates": [_transaction_dict(t) for t in result.suspected_duplicates],
        "rejected": [
            {"source_file": r.source_file, "source_row": r.source_row, "reason": r.reason, "raw": r.raw}
            for r in result.rejected
        ],
        "summaries": {c: _summary_dict(s) for c, s in result.summaries.items()},
    }


def render_text(result: PipelineResult) -> str:
    lines = ["IMPORT"]
    for f in result.files:
        lines.append(
            f"  {f.source_file}: {len(f.transactions)} parsed, "
            f"{len(f.rejected)} rejected, {f.blank_rows} blank"
        )
    lines.append(
        f"  -> {len(result.transactions)} unique transactions, "
        f"{len(result.duplicates)} duplicates removed"
    )

    if result.rejected:
        lines += ["", "REJECTED ROWS (not imported)"]
        lines += [f"  {r.source_file}:{r.source_row}  {r.reason}" for r in result.rejected]

    if result.suspected_duplicates:
        lines += ["", "POSSIBLE DUPLICATES (kept; identical rows in one file, please review)"]
        lines += [
            f"  {t.source_file}:{t.source_row}  {t.date}  {_money(t.amount)}  {t.description}"
            for t in result.suspected_duplicates
        ]

    for currency, s in result.summaries.items():
        lines += [
            "",
            f"SUMMARY ({currency})  {s.start_date} to {s.end_date}",
            f"  Income    {_money(s.totals.income):>14}",
            f"  Expenses  {_money(s.totals.expenses):>14}",
            f"  Net       {_money(s.totals.net):>14}",
            f"  Transfers in {_money(s.transfers_in)}, out {_money(s.transfers_out)} (excluded above)",
            "",
            "  By month         income       expenses            net",
        ]
        lines += [
            f"  {month}  {_money(p.income):>14} {_money(p.expenses):>14} {_money(p.net):>14}"
            for month, p in s.by_month.items()
        ]
        lines += ["", "  Expenses by category"]
        lines += [
            f"  {category:<16}{_money(value):>14}"
            for category, value in s.expenses_by_category.items()
        ]
        lines += ["", "  Largest expenses"]
        lines += [
            f"  {t.date}  {_money(-t.amount):>12}  {t.description}"
            for t in s.largest_expenses
        ]
    return "\n".join(lines)


def export_csv(result: PipelineResult, path: str | Path) -> None:
    """Write the unique, cleaned transactions to one CSV file."""
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_EXPORT_FIELDS)
        writer.writeheader()
        writer.writerows(_transaction_dict(t) for t in result.transactions)
