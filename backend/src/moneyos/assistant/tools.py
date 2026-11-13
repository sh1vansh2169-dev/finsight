"""The assistant's tools: read-only questions to MoneyOS itself.

Every figure the assistant may quote comes from one of these functions, which
call the same API code the web app uses (so the numbers match the screens,
as exact decimal strings) inside the signed-in user's session, so tenancy
rules apply. **No tool changes anything**: there is no tool that writes,
moves money or contacts anyone. Outputs are kept small, because local
models have short context windows.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from moneyos.config import Settings

MAX_TRANSACTIONS = 20


class ToolError(ValueError):
    """Bad arguments from the model; reported back to it so it can correct itself."""


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    run: Callable[[Session, Settings, dict[str, Any]], Any]

    def schema(self) -> dict[str, Any]:
        """The tool as a function definition for the model."""
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": self.parameters}}


def _json(model: Any) -> Any:
    return json.loads(model.model_dump_json()) if hasattr(model, "model_dump_json") else model


def _date(args: dict[str, Any], key: str) -> date | None:
    value = args.get(key)
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ToolError(f"{key} must be a date like 2026-03-31") from None


def _month(args: dict[str, Any]) -> str | None:
    value = args.get("month")
    if value in (None, ""):
        return None
    text = str(value)
    if len(text) != 7 or text[4] != "-" or not (text[:4] + text[5:]).isdigit():
        raise ToolError("month must look like 2026-03")
    return text


def month_overview(session: Session, settings: Settings, args: dict[str, Any]) -> dict[str, Any]:
    from moneyos.api.analytics import get_dashboard

    d = _json(get_dashboard(session, settings, month=_month(args), currency=None))
    summary = d["summary"] or {}
    return {
        "month": d["month"], "currency": d["currency"], "note": d["note"],
        "income": summary.get("income"), "spending_after_refunds": summary.get("spending"),
        "net_cash_flow": summary.get("net_cash_flow"),
        "spending_by_category": summary.get("spending_by_category"),
        "budgets": [{k: b[k] for k in ("category", "spent", "limit", "remaining", "state")} for b in d["budgets"]],
        "warnings": d["warnings"],
    }


def find_transactions(session: Session, settings: Settings, args: dict[str, Any]) -> dict[str, Any]:
    from moneyos.api.routes import _filter, list_transactions

    limit = args.get("limit") or 10
    if not isinstance(limit, int) or not 1 <= limit <= MAX_TRANSACTIONS:
        raise ToolError(f"limit must be a whole number from 1 to {MAX_TRANSACTIONS}")
    search = args.get("search")
    if search is not None and (not isinstance(search, str) or len(search) > 100):
        raise ToolError("search must be text of at most 100 characters")
    f = _filter(start=_date(args, "start"), end=_date(args, "end"), account=None, currency=None, txn_type=None,
                category=args.get("category") or None, include_duplicates=False,
                q=(search or "").strip() or None)
    page = _json(list_transactions(session, f, limit=limit, offset=0))
    return {
        "total_matching": page["total"], "shown": len(page["items"]),
        "transactions": [{k: t[k] for k in ("date", "description", "amount", "currency", "category", "account")}
                         for t in page["items"]],
    }


def spending_between(session: Session, settings: Settings, args: dict[str, Any]) -> dict[str, Any]:
    from moneyos.api.routes import _filter, summary

    start, end = _date(args, "start"), _date(args, "end")
    if start is None or end is None or start > end:
        raise ToolError("start and end are both needed, with start on or before end")
    f = _filter(start=start, end=end, account=None, currency=None, txn_type=None, category=None,
                include_duplicates=False, q=None)
    out = _json(summary(session, f, settings))
    return {
        "start": start.isoformat(), "end": end.isoformat(), "warnings": out["warnings"],
        "by_currency": {c: {k: s[k] for k in ("income", "spending", "refunds", "net_cash_flow", "spending_by_category")}
                        for c, s in out["currencies"].items()},
        "note": "Recorded totals for transactions in MoneyOS only; not a bank balance.",
    }


def upcoming_bills(session: Session, settings: Settings, args: dict[str, Any]) -> dict[str, Any]:
    from moneyos.api.planning import upcoming

    days = args.get("days") or 30
    if not isinstance(days, int) or not 1 <= days <= 90:
        raise ToolError("days must be a whole number from 1 to 90")
    return _json(upcoming(session, days=days, currency=None, as_of=None))


def money_owed(session: Session, settings: Settings, args: dict[str, Any]) -> list[Any]:
    from moneyos.api.majra import summary

    return [_json(s) for s in summary(session)]


def unusual_payments(session: Session, settings: Settings, args: dict[str, Any]) -> dict[str, Any]:
    from moneyos.api.ml import unusual_payments as unusual

    out = _json(unusual(session, start=None, end=None, currency=None))
    return {"note": out["note"], "payments": [
        {"date": p["transaction"]["date"], "description": p["transaction"]["description"],
         "amount": p["transaction"]["amount"], "reason": p["reason"]} for p in out["payments"][:10]]}


def what_if(session: Session, settings: Settings, args: dict[str, Any]) -> dict[str, Any]:
    from moneyos.api.planning import SimulateIn, simulate

    days = args.get("days") or 30
    if not isinstance(days, int) or not 7 <= days <= 90:
        raise ToolError("days must be a whole number from 7 to 90")
    scenarios = []
    if args.get("purchase_amount") not in (None, "", 0):
        scenarios.append({"kind": "purchase", "amount": str(args["purchase_amount"]),
                          "date": args.get("purchase_date") or None, "description": "a purchase"})
    try:
        if scenarios and scenarios[0]["date"] is None:
            base = simulate(SimulateIn(horizon_days=days), session)["baseline"]
            scenarios[0]["date"] = (base["start"] + timedelta(days=1)).isoformat()  # first day inside the window
        out = simulate(SimulateIn(horizon_days=days, scenarios=scenarios), session)
    except ValueError as error:  # includes the service's InvalidRequestError
        raise ToolError(str(error)) from None

    def brief(p: dict[str, Any]) -> dict[str, Any]:
        return {"start": str(p["start"]), "end": str(p["end"]), "currency": p["currency"],
                "net_change": {k: (None if v is None else str(v)) for k, v in p["net_change"].items()},
                "not_counted_money_others_owe_you": str(p["not_included"]["if_others_repay_you"])}

    result = {"note": out["note"], "as_things_are": brief(out["baseline"])}
    if "scenario" in out:
        result["with_the_purchase"] = brief(out["scenario"])
        result["difference"] = str(out["difference"]["net_change"])
    return result


_DATE = {"type": "string", "description": "A date, YYYY-MM-DD"}

TOOLS: dict[str, Tool] = {t.name: t for t in (
    Tool("month_overview",
         "Income, spending after refunds, net cash flow, spending by category, budgets and data warnings for one "
         "calendar month. Without a month, the newest month that has data.",
         {"type": "object", "properties": {"month": {"type": "string", "description": "YYYY-MM"}}},
         month_overview),
    Tool("find_transactions",
         "Search recorded transactions by words in the description, category or date range. Newest first.",
         {"type": "object", "properties": {
             "search": {"type": "string"}, "category": {"type": "string"}, "start": _DATE, "end": _DATE,
             "limit": {"type": "integer", "description": f"1 to {MAX_TRANSACTIONS}"}}},
         find_transactions),
    Tool("spending_between",
         "Totals (income, spending after refunds, net, spending by category) between two dates, inclusive.",
         {"type": "object", "properties": {"start": _DATE, "end": _DATE}, "required": ["start", "end"]},
         spending_between),
    Tool("upcoming_bills",
         "Confirmed bills and income due in the coming days, and how much to keep aside for the bills.",
         {"type": "object", "properties": {"days": {"type": "integer", "description": "1 to 90, default 30"}}},
         upcoming_bills),
    Tool("money_owed",
         "Money Majra: how much others owe the user and how much the user owes, per person. Money owed to the "
         "user is expected, not guaranteed.",
         {"type": "object", "properties": {}}, money_owed),
    Tool("unusual_payments",
         "Payments unusually large for this user, with the reason. Not a fraud check.",
         {"type": "object", "properties": {}}, unusual_payments),
    Tool("what_if",
         "Estimate the change in money over the next days from commitments and usual spending, optionally with "
         "one purchase. An estimate with a range, not a promise.",
         {"type": "object", "properties": {
             "days": {"type": "integer", "description": "7 to 90, default 30"},
             "purchase_amount": {"type": "number", "description": "Optional purchase amount"},
             "purchase_date": _DATE}},
         what_if),
)}


def call(session: Session, settings: Settings, name: str, args: Any) -> Any:
    """Run a tool by name. Errors come back as data, for the model to read."""
    tool = TOOLS.get(name)
    if tool is None:
        return {"error": f"there is no tool called {name!r}"}
    if not isinstance(args, dict):
        return {"error": "arguments must be an object"}
    try:
        return tool.run(session, settings, args)
    except ToolError as error:
        return {"error": str(error)}
