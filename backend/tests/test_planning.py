"""Recurring payments, commitments, the what-if simulator and recommendations."""

from datetime import date
from decimal import Decimal

import pytest

from conftest import sign_up
from fastapi.testclient import TestClient

from moneyos.api.app import create_app
from moneyos.config import Settings
from moneyos.domain import synthetic
from moneyos.domain.recommend import recommend, CategoryTrend, OwedToYou, Subscription

BANNED = ("overspent", "overspending", "waste", "wasting", "bad", "irresponsible", "should have", "careless", "too much")


@pytest.fixture
def client(database_url, dataset):
    client = TestClient(create_app(Settings(database_url=database_url)))
    sign_up(client)
    for name, text in dataset.files.items():
        form = {"account": synthetic.CARD_ACCOUNT} if "card" in name else {}
        preview = client.post("/api/v1/imports/preview", files={"file": (name, text.encode(), "text/csv")}, data=form)
        client.post(f"/api/v1/imports/{preview.json()['batch']['id']}/commit")
    yield client
    client.app.state.session_factory.kw["bind"].dispose()


def _d(v):
    return Decimal(v) if v is not None else None


def _confirm(client, key):
    response = client.post("/api/v1/commitments/confirm", json={"key": key})
    assert response.status_code == 201, response.text
    return response.json()


def test_recurring_suggestions(client):
    found = {s["key"]: s for s in client.get("/api/v1/recurring").json()}
    rent = found["rent greenview apts"]
    assert (rent["cadence"], rent["typical_amount"], rent["is_commitment"]) == ("monthly", "22000.00", False)
    assert rent["next_expected"] == "2026-04-03" and rent["reasons"]
    assert found["city power electricity bill"]["amount_varies"] is True


def test_confirming_and_managing_commitments(client):
    rent = _confirm(client, "rent greenview apts")
    assert (rent["source"], rent["status"], rent["amount"]) == ("detected", "active", "22000.00")
    assert client.post("/api/v1/commitments/confirm", json={"key": "rent greenview apts"}).status_code == 409
    assert client.post("/api/v1/commitments/confirm", json={"key": "nothing like this"}).status_code == 404
    assert {s["key"]: s["is_commitment"] for s in client.get("/api/v1/recurring").json()}["rent greenview apts"]

    fee = client.post("/api/v1/commitments", json={"name": "School fee", "amount": "15000", "cadence": "once",
                                                   "next_due": "2026-04-20", "category": "Education"})
    assert fee.status_code == 201
    upcoming = client.get("/api/v1/commitments/upcoming").json()
    assert upcoming["start"] == "2026-03-27"  # the newest transaction, not today's date
    names = [(o["date"], o["name"]) for o in upcoming["occurrences"]]
    assert ("2026-04-03", rent["name"]) in names and ("2026-04-20", "School fee") in names
    assert _d(upcoming["reserve"]) == Decimal("37000.00")

    client.patch(f"/api/v1/commitments/{fee.json()['id']}", json={"status": "paused"})
    assert _d(client.get("/api/v1/commitments/upcoming").json()["reserve"]) == Decimal("22000.00")
    assert client.patch("/api/v1/commitments/999", json={"status": "ended"}).status_code == 404
    bad = client.post("/api/v1/commitments", json={"name": "X", "amount": "1", "next_due": "2026-04-20",
                                                   "end_date": "2026-04-01"})
    assert bad.status_code == 422


def test_confirmed_payments_leave_everyday_spending_exactly(client):
    """No double counting: confirming rent moves exactly the rent payments out of everyday spending."""
    from moneyos.services import planning

    from moneyos.db.tenancy import user_session

    factory = client.app.state.session_factory
    me = client.get("/api/v1/auth/me").json()["id"]
    with user_session(factory, me) as session:
        before = planning._everyday(session, "INR", date(2026, 3, 27), 30)
    _confirm(client, "rent greenview apts")
    with user_session(factory, me) as session:
        after = planning._everyday(session, "INR", date(2026, 3, 27), 30)
    removed = (before.per_day - after.per_day) * before.history_days
    assert abs(removed - Decimal("66000")) < before.history_days * Decimal("0.01")  # three rents, up to rounding
    assert before.history_days == after.history_days


def test_simulation_and_scenarios(client):
    _confirm(client, "rent greenview apts")
    _confirm(client, "acme corp salary")
    base = client.post("/api/v1/simulate", json={}).json()
    b = base["baseline"]
    assert "not promises" in base["note"]
    assert (_d(b["commitments"]["money_in"]), _d(b["commitments"]["money_out"])) == (Decimal("85000.00"), Decimal("22000.00"))
    estimate = _d(b["net_change"]["estimate"])
    assert estimate == Decimal("85000.00") - Decimal("22000.00") - _d(b["everyday_spending"]["estimate"])
    assert _d(b["net_change"]["cautious"]) <= estimate <= _d(b["net_change"]["hopeful"])
    assert b["balance"] is None and len(b["path"]) == 30

    what_if = client.post("/api/v1/simulate", json={
        "starting_balance": "20000",
        "scenarios": [{"kind": "purchase", "amount": "3000", "date": "2026-04-05", "description": "Phone"},
                      {"kind": "reduce_category", "category": "Dining", "percent": 15}],
    }).json()
    assert _d(what_if["scenario"]["balance"]["estimate"]) == Decimal("20000") + _d(what_if["scenario"]["net_change"]["estimate"])
    assert _d(what_if["difference"]["net_change"]) > Decimal("-3000")  # the Dining cut claws a little back
    assert len(what_if["scenario"]["changes"]) == 2

    again = client.post("/api/v1/simulate", json={"starting_balance": "20000", "scenarios": [
        {"kind": "purchase", "amount": "3000", "date": "2026-04-05", "description": "Phone"},
        {"kind": "reduce_category", "category": "Dining", "percent": 15}]}).json()
    assert again == what_if  # deterministic

    assert client.post("/api/v1/simulate", json={"scenarios": [{"kind": "lottery"}]}).status_code == 422
    assert client.post("/api/v1/simulate", json={"scenarios": [
        {"kind": "reduce_category", "category": "Yachts", "percent": 10}]}).status_code == 422
    assert client.post("/api/v1/simulate", json={"horizon_days": 400}).status_code == 422


def test_money_owed_to_you_is_never_in_the_estimate(client):
    sam = client.post("/api/v1/majra/people", json={"name": "Sam"}).json()["id"]
    client.post("/api/v1/majra/loans", json={"person_id": sam, "direction": "lent", "amount": "2000",
                                             "date": "2026-01-10", "description": "Laptop repair"})
    body = client.post("/api/v1/simulate", json={}).json()["baseline"]
    assert _d(body["not_included"]["if_others_repay_you"]) == Decimal("2000.00")
    delayed = client.post("/api/v1/simulate", json={"scenarios": [{"kind": "delay_repayment", "person": "Sam"}]}).json()
    assert delayed["difference"]["net_change"] == "0.00"  # it was never counted as money you have


def test_recommendations(client):
    _confirm(client, "rent greenview apts")
    sam = client.post("/api/v1/majra/people", json={"name": "Sam"}).json()["id"]
    client.post("/api/v1/majra/loans", json={"person_id": sam, "direction": "lent", "amount": "500",
                                             "date": "2026-01-10", "description": "Lunch"})
    recs = client.get("/api/v1/recommendations").json()
    kinds = {r["kind"] for r in recs}
    assert {"reserve", "classify", "owed_to_you"} <= kinds
    assert [r["priority"] for r in recs] == sorted(r["priority"] for r in recs)
    owed = next(r for r in recs if r["kind"] == "owed_to_you")
    assert "Sam" in owed["message"] and "never contacts anyone" in owed["message"]
    for r in recs:
        assert not any(word in r["message"].lower() for word in BANNED), r["message"]


def test_dashboard_outlook(client):
    _confirm(client, "rent greenview apts")
    outlook = client.get("/api/v1/dashboard").json()["outlook"]
    assert "not promises" in outlook["note"] and _d(outlook["commitments"]["money_out"]) == Decimal("22000.00")


# ----------------------------------------------------- recommendation rules


def test_rising_category_rule_and_quiet_cases():
    recs = recommend(currency="INR", today=date(2026, 3, 31), trends=[
        CategoryTrend("Dining", Decimal("2900"), Decimal("2000"), 3),  # +45%, +900: noticed
        CategoryTrend("Health", Decimal("390"), Decimal("200"), 3),  # +95% but only +190: too small to mention
        CategoryTrend("Travel", Decimal("9000"), Decimal("1000"), 1),  # one month of history is not a trend
    ])
    (rising,) = [r for r in recs if r.kind == "category_rising"]
    assert rising.title == "Dining is higher than usual" and "45%" in rising.message


def test_subscription_and_owed_rules():
    recs = recommend(currency="INR", today=date(2026, 3, 31),
                     subscriptions=[Subscription("Streamflix", Decimal("649")), Subscription("Music", Decimal("199"))],
                     owed=[OwedToYou("Ria", Decimal("300"), date(2026, 3, 20)),  # 11 days: too soon to mention
                           OwedToYou("Sam", Decimal("500"), date(2026, 1, 31))])
    kinds = [r.kind for r in recs]
    assert kinds.count("owed_to_you") == 1 and "subscriptions" in kinds
    subs = next(r for r in recs if r.kind == "subscriptions")
    assert "848.00" in subs.message
    for r in recs:
        assert not any(word in r.message.lower() for word in BANNED)


def test_summary_and_recommendations_agree_on_counts(client, dataset):
    """The same fact must show the same number everywhere (failed payments excluded in both)."""
    import re

    app = dataset.payapp  # contains failed payments with an unknown type
    preview = client.post("/api/v1/imports/preview", files={"file": (app.name, app.text.encode(), "text/csv")},
                          data={"account": synthetic.PAYAPP_ACCOUNT})
    client.post(f"/api/v1/imports/{preview.json()['batch']['id']}/commit")

    warnings = " ".join(client.get("/api/v1/summary").json()["currencies"]["INR"]["warnings"])
    in_summary = int(re.search(r"(\d+) transaction\(s\) have an unknown type", warnings).group(1))
    classify = next(r for r in client.get("/api/v1/recommendations").json() if r["kind"] == "classify")
    assert classify["evidence"]["count"] == in_summary
