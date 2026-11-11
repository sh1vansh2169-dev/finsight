"""Dashboard, analytics and budget endpoints over a real SQLite file."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from moneyos.api.app import create_app
from moneyos.config import Settings
from moneyos.domain import synthetic


@pytest.fixture
def client(database_url):
    client = TestClient(create_app(Settings(database_url=database_url)))
    yield client
    client.app.state.session_factory.kw["bind"].dispose()


def _import(client, name, text, account=None):
    form = {"account": account} if account else {}
    preview = client.post("/api/v1/imports/preview", files={"file": (name, text.encode(), "text/csv")}, data=form)
    assert preview.status_code == 201, preview.text
    assert client.post(f"/api/v1/imports/{preview.json()['batch']['id']}/commit").status_code == 200


@pytest.fixture
def loaded(client, dataset):
    for name, text in dataset.files.items():
        _import(client, name, text, synthetic.CARD_ACCOUNT if "card" in name else None)
    _import(client, dataset.payapp.name, dataset.payapp.text, synthetic.PAYAPP_ACCOUNT)
    return client


def _d(value):
    return Decimal(value) if value is not None else None


def test_empty_ledger_dashboard(client):
    body = client.get("/api/v1/dashboard").json()
    assert body["currency"] is None and body["summary"] is None
    assert body["daily"] == [] and body["recent_transactions"] == []
    assert set(body["not_yet_available"]) == {"forecast", "upcoming_commitments"}
    assert body["money_majra"] is None


def test_dashboard_defaults_to_the_newest_month(loaded):
    body = loaded.get("/api/v1/dashboard").json()
    assert (body["month"], body["currency"], body["sample_data"]) == ("2026-03", "INR", False)
    assert "not a bank balance" in body["note"]
    assert len(body["daily"]) == 31 and len(body["monthly"]) == 6
    assert len(body["recent_transactions"]) == 10
    assert all(t["date"] <= "2026-03-31" for t in body["recent_transactions"])
    assert body["open_duplicate_reviews"] > 0
    assert any("await review" in w for w in body["warnings"])

    # The month's summary and its daily series are two views of the same data.
    daily_expenses = sum(_d(p["expenses"]) or 0 for p in body["daily"])
    assert daily_expenses == _d(body["summary"]["expenses"])
    # The trailing months before 2026-01 have no statement at all: unknown, not zero.
    before = [p for p in body["monthly"] if p["period"] < "2026-01"]
    assert len(before) == 3
    assert all(p["coverage"] == 0 and p["expenses"] is None for p in before)


def test_unknown_days_are_null_never_zero(loaded):
    body = loaded.get("/api/v1/dashboard", params={"month": "2026-03"}).json()
    for point in body["daily"]:
        assert (point["coverage"] == 0) == (point["expenses"] is None)
    assert any(p["coverage"] == 0 for p in body["daily"])  # the end of March is after every statement
    assert any("No statement covers" in w for w in body["warnings"])


def test_cash_flow_series_reconciles_with_the_summary(loaded):
    summary = loaded.get("/api/v1/summary").json()["currencies"]["INR"]
    for granularity in ("day", "week", "month"):
        body = loaded.get("/api/v1/analytics/cash-flow", params={"granularity": granularity}).json()
        assert body["currency"] == "INR" and "coverage" in body["note"]
        net = sum(_d(p["net_cash_flow"]) or 0 for p in body["points"])
        expenses = sum(_d(p["expenses"]) or 0 for p in body["points"])
        assert net == _d(summary["net_cash_flow"]), granularity
        assert expenses == _d(summary["expenses"]), granularity

    weekly = loaded.get("/api/v1/analytics/cash-flow", params={"granularity": "week"}).json()["points"]
    assert weekly[0]["start"] == "2025-12-29"  # weeks run Monday to Sunday
    assert loaded.get("/api/v1/analytics/cash-flow", params={"granularity": "year"}).status_code == 422
    bad_range = {"start": "2026-03-01", "end": "2026-01-01"}
    assert loaded.get("/api/v1/analytics/cash-flow", params=bad_range).status_code == 422


def test_spending_statistics(loaded):
    body = loaded.get("/api/v1/analytics/spending").json()
    summary = loaded.get("/api/v1/summary").json()["currencies"]["INR"]
    assert _d(body["total"]) == _d(summary["expenses"])
    assert sum(_d(c["purchases"]) for c in body["by_category"]) == _d(body["total"])
    # Refunds reduce spending in their own category (Shopkart refund -> Shopping).
    assert sum(_d(c["spending"]) for c in body["by_category"]) == _d(summary["spending"])
    shopping = next(c for c in body["by_category"] if c["category"] == "Shopping")
    assert _d(shopping["refunds"]) == Decimal("499.00")
    assert _d(shopping["spending"]) == _d(shopping["purchases"]) - Decimal("499.00")
    assert sum(c["share"] for c in body["by_category"]) == pytest.approx(1, abs=1e-3)
    assert sum(_d(w["total"]) for w in body["by_weekday"]) == _d(body["total"])
    assert body["by_category"][0]["category"] == "Housing"  # rent is the largest
    assert body["month_over_month"]["months"] == ["2026-02", "2026-03"]
    assert len(body["top_merchants"]) == 5


def test_quality_report(loaded, dataset):
    body = loaded.get("/api/v1/analytics/quality").json()
    assert body["rejected_rows"] == dataset.expected.rejected
    assert body["open_duplicate_reviews"] == len(dataset.payapp.mirrored) + 1
    accounts = {c["account"] for c in body["coverage"]}
    assert accounts == {"Sample Savings 0001", synthetic.CARD_ACCOUNT, synthetic.PAYAPP_ACCOUNT}
    assert body["accounts_without_statements"] == []
    fields = {f["field"]: f for f in body["fields"]}
    assert fields["txn_type"]["missing"] > 0
    assert sum(body["type_decided_by"].values()) == body["transactions"]


def test_manual_only_account_is_reported_as_uncovered(loaded):
    loaded.post("/api/v1/transactions", json={"date": "2026-03-02", "description": "Auto fare", "amount": "80",
                                              "direction": "debit", "account": "Cash"})
    body = loaded.get("/api/v1/analytics/quality").json()
    assert body["accounts_without_statements"] == ["Cash"]
    assert any("Cash has only manually entered records" in w for w in body["warnings"])


def test_budgets(loaded):
    created = loaded.put("/api/v1/budgets", json={"category": "Groceries", "monthly_limit": "3000"})
    assert created.status_code == 200
    budget_id = created.json()["id"]
    updated = loaded.put("/api/v1/budgets", json={"category": "Groceries", "monthly_limit": "4500.50"}).json()
    assert (updated["id"], updated["monthly_limit"]) == (budget_id, "4500.50")
    loaded.put("/api/v1/budgets", json={"category": "Housing", "monthly_limit": "100"})  # rent alone is 22,000
    assert [b["category"] for b in loaded.get("/api/v1/budgets").json()] == ["Groceries", "Housing"]

    usage = {u["category"]: u for u in loaded.get("/api/v1/budgets/usage", params={"month": "2026-03"}).json()}
    groceries = loaded.get(
        "/api/v1/transactions",
        params={"category": "Groceries", "txn_type": "expense", "start": "2026-03-01", "end": "2026-03-31", "limit": 500},
    ).json()["items"]
    spent = -sum(Decimal(t["amount"]) for t in groceries if t["status"] != "failed")
    assert _d(usage["Groceries"]["spent"]) == spent
    assert _d(usage["Groceries"]["remaining"]) == Decimal("4500.50") - spent
    assert usage["Groceries"]["projected_month_total"] is None  # March 2026 is over
    housing = usage["Housing"]
    assert housing["state"] == "over" and "over the limit" in housing["message"]

    dashboard = loaded.get("/api/v1/dashboard", params={"month": "2026-03"}).json()
    assert {b["category"] for b in dashboard["budgets"]} == {"Groceries", "Housing"}

    assert loaded.delete(f"/api/v1/budgets/{budget_id}").status_code == 204
    assert loaded.delete(f"/api/v1/budgets/{budget_id}").status_code == 404
    for bad in ({"category": "X", "monthly_limit": "0"}, {"category": "X", "monthly_limit": "1.001"},
                {"category": "", "monthly_limit": "5"}, {"category": "X", "monthly_limit": "5", "currency": "RUPEE"}):
        assert loaded.put("/api/v1/budgets", json=bad).status_code == 422, bad


def test_month_validation_and_currency_choice(loaded):
    assert loaded.get("/api/v1/dashboard", params={"month": "2026-13"}).status_code == 422
    assert loaded.get("/api/v1/dashboard", params={"month": "March"}).status_code == 422
    loaded.post("/api/v1/transactions", json={"date": "2026-03-02", "description": "Book", "amount": "12",
                                              "direction": "debit", "currency": "USD", "account": "US Card"})
    ambiguous = loaded.get("/api/v1/dashboard")
    assert ambiguous.status_code == 422 and "several currencies" in ambiguous.json()["detail"]
    usd = loaded.get("/api/v1/dashboard", params={"currency": "USD"}).json()
    assert usd["currency"] == "USD" and _d(usd["summary"]["expenses"]) in (None, Decimal("0.00"), Decimal("12.00"))


def test_reimporting_does_not_double_count_rejected_rows(loaded, dataset):
    for name, text in dataset.files.items():
        _import(loaded, name, text, synthetic.CARD_ACCOUNT if "card" in name else None)
    assert loaded.get("/api/v1/analytics/quality").json()["rejected_rows"] == dataset.expected.rejected


def test_cli_report(tmp_path, capsys, monkeypatch):
    from moneyos.cli import main

    url = f"sqlite:///{(tmp_path / 'sample.db').as_posix()}"
    assert main(["seed-sample", "--database", url]) == 0
    out = tmp_path / "report"
    monkeypatch.setenv("MONEYOS_DATABASE_URL", url)
    assert main(["report", "--sample", "--out", str(out)]) == 0
    text = (out / "report.md").read_text(encoding="utf-8")
    assert synthetic.SAMPLE_MARKER in text
    assert "not a bank balance" in text and "What this report cannot tell you" in text
    for chart in ("monthly_in_out.png", "daily_spending.png", "spending_by_category.png"):
        assert f"]({chart})" in text and (out / chart).stat().st_size > 1000


def test_budgets_ignore_confirmed_duplicates(loaded):
    """A FreshMart payment seen by both the app and the bank is spent once."""
    loaded.put("/api/v1/budgets", json={"category": "Groceries", "monthly_limit": "50000"})

    def spent(month):
        usage = loaded.get("/api/v1/budgets/usage", params={"month": month}).json()
        return Decimal(next(u for u in usage if u["category"] == "Groceries")["spent"])

    items = loaded.get("/api/v1/review/duplicates").json()
    groceries = [
        i for i in items
        if {t["account"] for t in i["transactions"]} == {"Sample Savings 0001", synthetic.PAYAPP_ACCOUNT}
        and all(t["category"] == "Groceries" for t in i["transactions"])
    ]
    assert groceries, "the sample should mirror at least one grocery payment"
    item = groceries[0]
    bank, app = sorted(item["transactions"], key=lambda t: t["account"] == synthetic.PAYAPP_ACCOUNT)
    month = bank["date"][:7]

    before = spent(month)
    loaded.post(f"/api/v1/review/duplicates/{item['id']}/resolve",
                json={"decision": "duplicate", "keep_transaction_id": bank["id"]})
    assert spent(month) == before + Decimal(app["amount"])  # app amount is negative: one copy removed


def test_refund_reduces_budget_spending(loaded):
    loaded.put("/api/v1/budgets", json={"category": "Shopping", "monthly_limit": "100000"})

    def spent():
        usage = loaded.get("/api/v1/budgets/usage", params={"month": "2026-03"}).json()
        return Decimal(next(u for u in usage if u["category"] == "Shopping")["spent"])

    before = spent()
    refund = loaded.post("/api/v1/transactions", json={
        "date": "2026-03-10", "description": "ShopKart refund", "amount": "250.00", "direction": "credit",
        "account": "Sample Card 4321", "txn_type": "refund", "category": "Shopping",
    })
    assert refund.status_code == 201, refund.text
    assert spent() == before - Decimal("250.00")
    summary = loaded.get("/api/v1/summary", params={"start": "2026-03-01", "end": "2026-03-31"}).json()
    inr = summary["currencies"]["INR"]
    assert _d(inr["spending"]) == _d(inr["expenses"]) - _d(inr["refunds"])
