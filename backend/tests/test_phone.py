"""Phone app: pairing and SMS alerts (synthetic messages only)."""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from conftest import TEST_PASSWORD, sign_up
from moneyos.api.app import create_app
from moneyos.config import Settings
from moneyos.db.tables import ImportBatch, PhoneDevice
from moneyos.db.tenancy import system_session

ALERTS = "/api/v1/phone/alerts"


def ms(day, hour=12):
    return int(datetime(2026, 3, day, hour).timestamp() * 1000)


BANK = [
    {"sender": "AX-HDFCBK", "timestamp_ms": ms(12), "body": "Sent Rs.500.00 From HDFC Bank A/C *1234 To SWIGGY On 12/03/26 Ref 412345678901"},
    {"sender": "JD-SBIUPI", "timestamp_ms": ms(13), "body": "Dear UPI user A/C X1234 debited by 250.0 on date 13Mar26 trf to RAVI KUMAR Refno 412398765432"},
]
NOISE = [
    {"sender": "AX-HDFCBK", "timestamp_ms": ms(12, 9), "body": "Your OTP for transaction of Rs.5000 at AMAZON is 482913. Do not share."},
    {"sender": "+919800000000", "timestamp_ms": ms(12, 10), "body": "Dinner was great, see you Sunday"},
]


@pytest.fixture
def make_client(database_url):
    clients = []

    def _make():
        client = TestClient(create_app(Settings(database_url=database_url, allow_signup=True)))
        clients.append(client)
        return client

    yield _make
    for c in clients:
        c.app.state.session_factory.kw["bind"].dispose()


def pair(client, name="Asha's phone"):
    reply = client.post("/api/v1/phone/devices", json={"name": name})
    assert reply.status_code == 201, reply.text
    return reply.json()


def send(client, key, alerts):
    return client.post(ALERTS, json={"alerts": alerts}, headers={"X-FinSight-Device": key})


def waiting(client):
    return [b for b in client.get("/api/v1/imports").json() if b["status"] == "previewed"]


def test_pairing_shows_the_key_once_and_stores_only_a_hash(make_client):
    client = make_client()
    sign_up(client)
    paired = pair(client)
    assert paired["key"].startswith("fsp_") and paired["name"] == "Asha's phone"
    listed = client.get("/api/v1/phone/devices").json()
    assert [d["name"] for d in listed] == ["Asha's phone"] and "key" not in listed[0]
    with system_session(client.app.state.session_factory) as s:
        stored = s.scalars(select(PhoneDevice)).one()
        assert stored.token_hash != paired["key"] and paired["key"] not in stored.token_hash


def test_only_transaction_alerts_are_kept_for_review(make_client):
    client = make_client()
    sign_up(client)
    key = pair(client)["key"]
    reply = send(client, key, NOISE + BANK)
    assert reply.status_code == 200, reply.text
    assert reply.json()["received"] == 4 and reply.json()["kept"] == 2
    [batch] = waiting(client)
    assert batch["filename"] == "Phone SMS.csv" and batch["new_rows"] == 2
    detail = client.get(f"/api/v1/imports/{batch['id']}").json()
    text = str(detail)
    assert "SWIGGY" in text and "RAVI KUMAR" in text
    assert "482913" not in text and "Dinner" not in text  # the OTP and the personal message are stored nowhere
    assert client.get("/api/v1/transactions").json()["total"] == 0  # nothing added before review


def test_alerts_collect_in_one_review_and_a_resend_is_staged_once(make_client):
    client = make_client()
    sign_up(client)
    key = pair(client)["key"]
    send(client, key, BANK[:1])
    second = send(client, key, BANK)  # the first alert again (a retry) plus a new one
    assert second.json()["kept"] == 1
    [batch] = waiting(client)
    assert batch["new_rows"] == 2  # one list, no double
    assert send(client, key, BANK).json()["kept"] == 0  # everything already staged

    assert client.post(f"/api/v1/imports/{batch['id']}/commit").json()["inserted_rows"] == 2
    later = send(client, key, [{"sender": "VM-ICICIT", "timestamp_ms": ms(14),
                                "body": "ICICI Bank Acct XX123 debited for Rs 1,875.56 on 14-Mar-26; FRESHMART credited. UPI:412311112222."}])
    assert later.json()["kept"] == 1 and len(waiting(client)) == 1  # a fresh list after adding


def test_the_phone_key_only_sends_alerts(make_client):
    client = make_client()
    sign_up(client)
    key = pair(client)["key"]
    other = make_client()  # no sign-in: just the key
    assert other.get("/api/v1/transactions", headers={"Authorization": f"Bearer {key}"}).status_code == 401
    assert other.get("/api/v1/phone/devices", headers={"X-FinSight-Device": key}).status_code == 401
    assert send(other, "fsp_not-a-real-key-at-all", BANK).status_code == 401
    assert other.post(ALERTS, json={"alerts": BANK}).status_code == 422  # no key at all


def test_a_disconnected_phone_is_refused(make_client):
    client = make_client()
    sign_up(client)
    paired = pair(client)
    assert client.delete(f"/api/v1/phone/devices/{paired['id']}").status_code == 204
    assert send(client, paired["key"], BANK).status_code == 401
    assert client.get("/api/v1/phone/devices").json() == []


def test_alerts_reach_only_the_phones_owner(make_client):
    asha = make_client()
    sign_up(asha, "asha@example.com")
    key = pair(asha)["key"]
    ravi = make_client()
    sign_up(ravi, "ravi@example.com")
    send(ravi, key, BANK)  # whoever sends it, the key decides the ledger
    assert len(waiting(asha)) == 1 and waiting(ravi) == []
    device_id = asha.get("/api/v1/phone/devices").json()[0]["id"]
    assert ravi.delete(f"/api/v1/phone/devices/{device_id}").status_code == 404  # not "forbidden"


def test_deleting_the_account_removes_its_phones(make_client):
    client = make_client()
    sign_up(client)
    key = pair(client)["key"]
    reply = client.post("/api/v1/auth/delete-account", json={"password": TEST_PASSWORD, "confirm": True})
    assert reply.status_code == 200, reply.text
    with system_session(client.app.state.session_factory) as s:
        assert s.scalars(select(PhoneDevice)).all() == []
    assert send(make_client(), key, BANK).status_code == 401


def test_limits(make_client):
    client = make_client()
    sign_up(client)
    key = pair(client)["key"]
    assert send(client, key, BANK * 251).status_code == 422  # at most 500 per call
    assert send(client, key, [{"sender": "X", "timestamp_ms": ms(1), "body": "x" * 2001}]).status_code == 422
    assert send(client, key, []).status_code == 422
