"""Money Majra over HTTP."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from moneyos.api.app import create_app
from moneyos.config import Settings


@pytest.fixture
def client(database_url):
    client = TestClient(create_app(Settings(database_url=database_url)))
    yield client
    client.app.state.session_factory.kw["bind"].dispose()


def _person(client, name):
    response = client.post("/api/v1/majra/people", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.fixture
def trip(client):
    sam, ria = _person(client, "Sam"), _person(client, "Ria")
    me = next(p["id"] for p in client.get("/api/v1/majra/people").json() if p["is_me"])
    group = client.post("/api/v1/majra/groups", json={"name": "Goa trip", "member_ids": [sam, ria]})
    assert group.status_code == 201, group.text
    return group.json()["group"]["id"], me, sam, ria


def _expense(client, group_id, payer, amount, participants, method="equal"):
    body = {"description": "Shared", "date": "2026-03-10", "amount": amount, "paid_by_id": payer,
            "split": {"method": method, "participants": participants}}
    return client.post(f"/api/v1/majra/groups/{group_id}/expenses", json=body)


def test_people_always_include_you(client):
    people = client.get("/api/v1/majra/people").json()
    assert [(p["name"], p["is_me"]) for p in people] == [("You", True)]
    assert client.post("/api/v1/majra/people", json={"name": "You"}).status_code == 409


def test_shared_expenses_balances_and_settlement(client, trip):
    group_id, me, sam, ria = trip
    response = _expense(client, group_id, me, "100.00", [{"person_id": p} for p in (me, sam, ria)])
    assert response.status_code == 201
    detail = response.json()
    balances = {b["person"]["id"]: (b["balance"], b["status"]) for b in detail["balances"]}
    # 100.00 / 3 = 33.34 + 33.33 + 33.33: the shares add up exactly.
    assert balances == {me: ("66.66", "is_owed"), sam: ("-33.33", "owes"), ria: ("-33.33", "owes")}
    assert detail["balances_sum_to_zero"] is True and detail["settlement_is_minimal"] is True
    plan = {(t["payer"]["id"], t["receiver"]["id"]): t["amount"] for t in detail["settlement"]}
    assert plan == {(sam, me): "33.33", (ria, me): "33.33"}
    (entry,) = detail["entries"]
    assert sorted(s["amount"] for s in entry["shares"]) == ["33.33", "33.33", "33.34"]

    paid = client.post(f"/api/v1/majra/groups/{group_id}/payments",
                       json={"payer_id": sam, "receiver_id": me, "amount": "33.33", "date": "2026-03-11"})
    assert paid.status_code == 201
    assert {b["person"]["id"]: b["status"] for b in paid.json()["balances"]}[sam] == "settled"


def test_payment_rules_over_http(client, trip):
    group_id, me, sam, ria = trip
    _expense(client, group_id, me, "90.00", [{"person_id": p} for p in (me, sam, ria)])
    over = client.post(f"/api/v1/majra/groups/{group_id}/payments",
                       json={"payer_id": sam, "receiver_id": me, "amount": "30.01", "date": "2026-03-11"})
    assert over.status_code == 422 and "more than is outstanding" in over.json()["detail"]
    body = {"payer_id": sam, "receiver_id": me, "amount": "10.00", "date": "2026-03-11"}
    assert client.post(f"/api/v1/majra/groups/{group_id}/payments", json=body).status_code == 201
    repeat = client.post(f"/api/v1/majra/groups/{group_id}/payments", json=body)
    assert repeat.status_code == 409 and "confirm_duplicate" in repeat.json()["detail"]
    confirmed = client.post(f"/api/v1/majra/groups/{group_id}/payments", json={**body, "confirm_duplicate": True})
    assert confirmed.status_code == 201


@pytest.mark.parametrize(
    ("method", "participants", "fragment"),
    [
        ("exact", [{"value": "40"}, {"value": "50"}], "add up to"),
        ("percent", [{"value": "60"}, {"value": "30"}], "100"),
        ("shares", [{"value": "0"}, {"value": "0"}], "more than zero"),
    ],
)
def test_split_validation(client, trip, method, participants, fragment):
    group_id, me, sam, _ = trip
    for p, person in zip(participants, (me, sam)):
        p["person_id"] = person
    response = _expense(client, group_id, me, "100.00", participants, method)
    assert response.status_code == 422 and fragment in response.json()["detail"]


def test_loans_summary_void_and_dashboard(client, trip):
    group_id, me, sam, ria = trip
    loan = client.post("/api/v1/majra/loans", json={"person_id": sam, "direction": "lent", "amount": "500",
                                                    "date": "2026-03-01", "description": "Concert"})
    assert loan.status_code == 201
    assert loan.json()["group"]["kind"] == "direct"
    client.post("/api/v1/majra/loans", json={"person_id": ria, "direction": "borrowed", "amount": "120",
                                             "date": "2026-03-02", "description": "Lunch"})

    (inr,) = client.get("/api/v1/majra/summary").json()
    assert (inr["owed_to_you"], inr["you_owe"]) == ("500.00", "120.00")
    assert "not guaranteed" in inr["note"]

    # The dashboard shows the same position, separately from recorded totals.
    client.post("/api/v1/transactions", json={"date": "2026-03-03", "description": "Groceries", "amount": "10",
                                              "direction": "debit"})
    dashboard = client.get("/api/v1/dashboard").json()
    assert dashboard["money_majra"]["owed_to_you"] == "500.00"
    assert dashboard["summary"]["inflow"] == "0.00"  # money you are owed is not money you have

    entry_id = loan.json()["entries"][0]["id"]
    voided = client.post(f"/api/v1/majra/entries/{entry_id}/void", json={"reason": "mistake"})
    assert voided.status_code == 200
    assert voided.json()["entries"][0]["voided"] is True
    (inr,) = client.get("/api/v1/majra/summary").json()
    assert inr["owed_to_you"] == "0.00"
    assert client.post(f"/api/v1/majra/entries/{entry_id}/void", json={"reason": "again"}).status_code == 409


def test_not_found_and_bad_input(client, trip):
    group_id, me, sam, _ = trip
    assert client.get("/api/v1/majra/groups/999").status_code == 404
    assert client.post("/api/v1/majra/groups", json={"name": "X", "member_ids": [999]}).status_code == 404
    assert client.post("/api/v1/majra/loans", json={"person_id": sam, "direction": "gifted", "amount": "1",
                                                    "date": "2026-03-01", "description": "X"}).status_code == 422
    assert _expense(client, group_id, me, "-5", [{"person_id": me}]).status_code == 422
