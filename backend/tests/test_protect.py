"""Phase 11 security review fixes: size limits, headers, and who may create the first account."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_PASSWORD, sign_up
from moneyos.api.app import create_app
from moneyos.api.protect import BODY_LIMIT, Protect
from moneyos.config import Settings

LAN_PHONE = ("192.168.1.20", 50000)  # another device on the home Wi-Fi
THIS_COMPUTER = ("127.0.0.1", 50000)


@pytest.fixture
def make(database_url):
    clients = []

    def _make(client=THIS_COMPUTER, **settings):
        c = TestClient(create_app(Settings(database_url=database_url, **settings)), client=client)
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.app.state.session_factory.kw["bind"].dispose()


def register(client, email="you@example.com"):
    return client.post("/api/v1/auth/register", json={"email": email, "password": TEST_PASSWORD})


def test_the_first_account_cannot_be_created_from_the_network(make):
    phone = make(LAN_PHONE)
    refused = register(phone, "stranger@example.com")
    assert refused.status_code == 409 and "on this computer" in refused.json()["detail"]
    assert register(make(THIS_COMPUTER)).status_code == 201  # the owner, at the computer


def test_later_accounts_follow_the_sign_up_setting_wherever_they_come_from(make):
    assert register(make(THIS_COMPUTER)).status_code == 201
    assert register(make(LAN_PHONE), "guest@example.com").status_code == 409  # closed by default
    assert register(make(LAN_PHONE, allow_signup=True), "guest@example.com").status_code == 201


def test_signing_in_from_the_phone_still_works(make):
    assert register(make(THIS_COMPUTER)).status_code == 201
    reply = make(LAN_PHONE).post("/api/v1/auth/login", json={"email": "you@example.com", "password": TEST_PASSWORD})
    assert reply.status_code == 200


def test_oversized_requests_are_refused_before_being_read(make):
    client = make()
    big = json.dumps({"email": "x@example.com", "password": "p" * (BODY_LIMIT + 10)})
    reply = client.post("/api/v1/auth/login", content=big, headers={"Content-Type": "application/json"})
    assert reply.status_code == 413 and "larger than 4 MB" in reply.json()["detail"]
    phone = client.post("/api/v1/phone/alerts", content=big,
                        headers={"Content-Type": "application/json", "X-FinSight-Device": "fsp_x" * 3})
    assert phone.status_code == 413


def test_statement_uploads_have_their_own_larger_limit(make):
    client = make()
    sign_up(client)
    six_mb_csv = b"Date,Description,Amount\n" + b"01/01/2026,X,-1.00\n" * 330_000
    assert len(six_mb_csv) > BODY_LIMIT
    reply = client.post("/api/v1/imports/preview", files={"file": ("big.csv", six_mb_csv, "text/csv")})
    # Past the 4 MB general limit, so the request reached the import code, which applies the 5 MB CSV limit.
    assert reply.status_code == 413 and "file is larger than 5 MB" in reply.json()["detail"]


def test_a_body_without_a_declared_length_is_still_capped():
    """Chunked bodies (no Content-Length) are counted as they arrive."""
    sent = []

    async def app(scope, receive, send):
        while True:
            message = await receive()
            if not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"read it all"})

    chunks = [{"type": "http.request", "body": b"x" * (1024 * 1024), "more_body": True}] * 5 + [
        {"type": "http.request", "body": b"", "more_body": False}]

    async def receive():
        return chunks.pop(0)

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "path": "/api/v1/auth/login", "method": "POST", "headers": []}
    asyncio.run(Protect(app)(scope, receive, send))
    assert sent[0]["status"] == 413 and b"read it all" not in b"".join(m.get("body", b"") for m in sent[1:])


def test_protective_headers_on_every_response(make):
    client = make()
    sign_up(client)
    api = client.get("/api/v1/transactions")
    assert api.headers["x-content-type-options"] == "nosniff"
    assert api.headers["referrer-policy"] == "no-referrer" and api.headers["x-frame-options"] == "DENY"
    assert api.headers["cache-control"] == "no-store"  # financial data is never cached
    health = client.get("/health")
    assert health.headers["x-content-type-options"] == "nosniff" and "cache-control" not in health.headers
