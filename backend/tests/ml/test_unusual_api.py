"""Unusual-payment flags over HTTP."""

import pytest
from fastapi.testclient import TestClient

from moneyos.api.app import create_app
from moneyos.config import Settings


@pytest.fixture
def client(database_url):
    client = TestClient(create_app(Settings(database_url=database_url)))
    yield client
    client.app.state.session_factory.kw["bind"].dispose()


def _pay(client, day, amount, description="Spice Route Restaurant"):
    r = client.post("/api/v1/transactions", json={"date": f"2026-03-{day:02d}", "description": description,
                                                  "amount": amount, "direction": "debit"})
    assert r.status_code == 201
    return r.json()["transaction"]


def test_unusual_payment_is_flagged_explained_and_dismissable(client):
    for day in range(1, 21):
        _pay(client, day, str(400 + day * 5))
    spike = _pay(client, 25, "8000")

    body = client.get("/api/v1/ml/unusual").json()
    assert body["method"] == "robust_z_score" and "not a fraud check" in body["note"]
    (flag,) = body["payments"]
    assert flag["transaction"]["id"] == spike["id"]
    assert "x your typical Dining payment" in flag["reason"] and flag["score"] >= 3

    assert client.post(f"/api/v1/ml/unusual/{spike['id']}/dismiss", json={"note": "birthday dinner"}).status_code == 204
    assert client.get("/api/v1/ml/unusual").json()["payments"] == []
    audit = client.get(f"/api/v1/transactions/{spike['id']}/audit").json()
    assert audit[-1]["action"] == "unusual_dismissed" and audit[-1]["details"]["note"] == "birthday dinner"


def test_nothing_is_judged_without_history(client):
    for day in range(1, 4):
        _pay(client, day, "400")
    _pay(client, 5, "9000")
    assert client.get("/api/v1/ml/unusual").json()["payments"] == []
    assert client.post("/api/v1/ml/unusual/999/dismiss", json={}).status_code == 404
