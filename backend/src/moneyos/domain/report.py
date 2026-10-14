"""Render a PipelineResult as text, JSON-ready data, or a cleaned CSV."""

from __future__ import annotations

import csv
from pathlib import Path

from moneyos.domain.models import Transaction
from moneyos.domain.pipeline import PipelineResult
from moneyos.domain.summary import LedgerSummary

_EXPORT_FIELDS = (
    "date", "description", "amount", "currency", "account", "txn_type", "type_basis",
    "category", "category_basis", "status", "reference", "source_file", "source_row",
)


def _money(value) -> str:
    return f"{value:,.2f}"


def transaction_dict(t: Transaction) -> dict:
    return {
        "date": t.date.isoformat(),
        "description": t.description,
        "amount": str(t.amount),
        "currency": t.currency,
        "account": t.account,
        "txn_type": t.txn_type.value,
        "type_basis": t.type_basis.value,
        "category": t.category,
        "category_basis": t.category_basis.value,
        "status": t.status.value,
        "reference": t.reference or "",
        "source_file": t.source_file,
        "source_row": t.source_row,
    }


def summary_dict(s: LedgerSummary) -> dict:
    return {
        "label": "Recorded totals for imported transactions only; not a bank balance.",
        "transaction_count": s.transaction_count,
        "start_date": s.start_date.isoformat() if s.start_date else None,
        "end_date": s.end_date.isoformat() if s.end_date else None,
        "inflow": str(s.inflow),
        "outflow": str(s.outflow),
        "net_cash_flow": str(s.net_cash_flow),
        "income": str(s.income),
        "expenses": str(s.expenses),
        "refunds": str(s.refunds),
        "unclassified_inflow": str(s.unclassified_inflow),
        "unclassified_outflow": str(s.unclassified_outflow),
        "transfers_in": str(s.transfers_in),
        "transfers_out": str(s.transfers_out),
        "by_type": {k.value: str(v) for k, v in s.by_type.items()},
        "by_month": {
            month: {
                "income": str(m.income),
                "expenses": str(m.expenses),
                "inflow": str(m.inflow),
                "outflow": str(m.outflow),
                "net_cash_flow": str(m.net_cash_flow),
            }
            for month, m in s.by_month.items()
        },
        "expenses_by_category": {c: str(v) for c, v in s.expenses_by_category.items()},
        "largest_expenses": [transaction_dict(t) for t in s.largest_expenses],
        "warnings": s.quality.warnings(),
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
        "transactions": [transaction_dict(t) for t in result.transactions],
        "duplicates": [transaction_dict(t) for t in result.duplicates],
        "suspected_duplicates": [transaction_dict(t) for t in result.suspected_duplicates],
        "rejected": [
            {"source_file": r.source_file, "source_row": r.source_row, "reason": r.reason, "raw": r.raw}
            for r in result.rejected
        ],
        "summaries": {c: summary_dict(s) for c, s in result.summaries.items()},
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
            f"RECORDED SUMMARY ({currency})  {s.start_date} to {s.end_date}",
            "  Imported transactions only. This is not a bank balance.",
            f"  Money in            {_money(s.inflow):>14}",
            f"    income            {_money(s.income):>14}",
            f"    refunds           {_money(s.refunds):>14}",
            f"    unclassified      {_money(s.unclassified_inflow):>14}",
            f"  Money out           {_money(s.outflow):>14}",
            f"    expenses          {_money(s.expenses):>14}",
            f"    unclassified      {_money(s.unclassified_outflow):>14}",
            f"  Net cash flow       {_money(s.net_cash_flow):>14}",
            f"  Own-account transfers in {_money(s.transfers_in)}, out {_money(s.transfers_out)} (excluded)",
            "",
            "  Month           income       expenses  net cash flow",
        ]
        lines += [
            f"  {month}  {_money(m.income):>14} {_money(m.expenses):>14} {_money(m.net_cash_flow):>14}"
            for month, m in s.by_month.items()
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
        if warnings := s.quality.warnings():
            lines += ["", "  Data quality"]
            lines += [f"  ! {w}" for w in warnings]
    return "\n".join(lines)


def export_csv(result: PipelineResult, path: str | Path) -> None:
    """Write the unique, cleaned transactions to one CSV file."""
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_EXPORT_FIELDS)
        writer.writeheader()
        writer.writerows(transaction_dict(t) for t in result.transactions)
