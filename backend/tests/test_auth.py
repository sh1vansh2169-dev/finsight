"""Accounts, sign-in, per-user isolation and account deletion."""

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_PASSWORD, sign_up
from moneyos.api.app import create_app
from moneyos.config import Settings
from moneyos.services import auth

COFFEE = b"Date,Description,Amount,Account\n07/02/2026,CHAI POINT CAFE,-120.00,Wallet\n"


@pytest.fixture
def make_client(database_url):
    clients = []

    def _make(allow_signup: bool = True):
        client = TestClient(create_app(Settings(database_url=database_url, allow_signup=allow_signup)))
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.app.state.session_factory.kw["bind"].dispose()


@pytest.fixture(autouse=True)
def _fresh_failures(monkeypatch):
    monkeypatch.setattr(auth, "failures", auth._Failures())  # failed attempts must not leak between tests


def _import(client, content=COFFEE):
    preview = client.post("/api/v1/imports/preview", files={"file": ("f.csv", content, "text/csv")})
    assert preview.status_code == 201, preview.text
    return client.post(f"/api/v1/imports/{preview.json()['batch']['id']}/commit").json()


def test_everything_needs_sign_in_except_health_and_auth(make_client):
    client = make_client()
    assert client.get("/health").status_code == 200
    for path in ("/api/v1/transactions", "/api/v1/summary", "/api/v1/dashboard", "/api/v1/majra/people",
                 "/api/v1/ml/categorizer", "/api/v1/recurring", "/api/v1/auth/me"):
        response = client.get(path)
        assert response.status_code == 401, path
        assert response.headers["www-authenticate"] == "Bearer"
    assert client.get("/api/v1/transactions", headers={"Authorization": "Bearer made-up"}).status_code == 401


def test_register_login_me_logout(make_client):
    client = make_client()
    body = sign_up(client, "Asha@Example.com")
    assert body["user"]["email"] == "asha@example.com"  # emails are compared case-insensitively
    assert client.get("/api/v1/auth/me").json()["email"] == "asha@example.com"
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401  # that token no longer works

    login = client.post("/api/v1/auth/login", json={"email": "asha@example.com", "password": TEST_PASSWORD})
    assert login.status_code == 200 and login.json()["token"]


def test_expired_sessions_are_refused(make_client):
    from datetime import timedelta

    from sqlalchemy import update

    from moneyos.db.tables import AuthSession, utc_now
    from moneyos.db.tenancy import system_session

    client = make_client()
    sign_up(client, "asha@example.com")
    assert client.get("/api/v1/auth/me").status_code == 200
    with system_session(client.app.state.session_factory) as s:
        s.execute(update(AuthSession).values(expires_at=utc_now() - timedelta(seconds=1)))
        s.commit()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_wrong_email_and_wrong_password_look_the_same(make_client):
    client = make_client()
    sign_up(client, "asha@example.com")
    wrong_password = client.post("/api/v1/auth/login", json={"email": "asha@example.com", "password": "nope-nope-nope"})
    no_such_user = client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "nope-nope-nope"})
    assert wrong_password.status_code == no_such_user.status_code == 401
    assert wrong_password.json() == no_such_user.json()


def test_repeated_failures_lock_the_email(make_client):
    client = make_client()
    sign_up(client, "asha@example.com")
    for _ in range(auth.MAX_FAILURES):
        bad = client.post("/api/v1/auth/login", json={"email": "asha@example.com", "password": "x" * 12})
        assert bad.status_code == 401
    locked = client.post("/api/v1/auth/login", json={"email": "asha@example.com", "password": TEST_PASSWORD})
    assert locked.status_code == 429  # even the right password waits out the lockout


def test_password_and_email_rules(make_client):
    client = make_client()
    assert client.post("/api/v1/auth/register", json={"email": "a@b.co", "password": "short"}).status_code == 422
    assert client.post("/api/v1/auth/register",
                       json={"email": "not-an-email", "password": TEST_PASSWORD}).status_code == 422
    sign_up(client, "asha@example.com")
    again = client.post("/api/v1/auth/register", json={"email": "ASHA@example.com", "password": TEST_PASSWORD})
    assert again.status_code == 409


def test_sign_up_closes_after_the_first_account_unless_allowed(make_client):
    closed = make_client(allow_signup=False)
    sign_up(closed, "owner@example.com")
    second = closed.post("/api/v1/auth/register", json={"email": "other@example.com", "password": TEST_PASSWORD})
    assert second.status_code == 409 and "MONEYOS_ALLOW_SIGNUP" in second.json()["detail"]


def test_each_user_sees_only_their_own_data(make_client):
    asha, ravi = make_client(), make_client()
    sign_up(asha, "asha@example.com")
    sign_up(ravi, "ravi@example.com")
    _import(asha)
    _import(asha, b"Date,Description,Amount,Account\n08/02/2026,FRESHMART GROCERIES,-450.00,Wallet\n")

    assert asha.get("/api/v1/transactions").json()["total"] == 2
    assert ravi.get("/api/v1/transactions").json()["total"] == 0
    assert ravi.get("/api/v1/summary").json()["currencies"] == {}
    assert ravi.get("/api/v1/imports").json() == []
    asha_txn = asha.get("/api/v1/transactions").json()["items"][0]["id"]
    assert ravi.get(f"/api/v1/transactions/{asha_txn}").status_code == 404  # it does not exist for him
    assert ravi.patch(f"/api/v1/transactions/{asha_txn}", json={"category": "Hacked"}).status_code == 404
    assert asha.get(f"/api/v1/transactions/{asha_txn}").json()["category"] != "Hacked"

    # The same file imported by Ravi is new for him: duplicate detection is per person.
    assert _import(ravi)["inserted_rows"] == 1
    # The same account, person and budget names on both sides do not clash.
    for client in (asha, ravi):
        assert client.post("/api/v1/majra/people", json={"name": "Sam"}).status_code == 201
        assert client.put("/api/v1/budgets", json={"category": "Dining", "monthly_limit": "1000"}).status_code == 200
    assert len(asha.get("/api/v1/majra/people").json()) == len(ravi.get("/api/v1/majra/people").json()) == 2


def test_delete_account_removes_everything_and_only_yours(make_client):
    asha, ravi = make_client(), make_client()
    sign_up(asha, "asha@example.com")
    sign_up(ravi, "ravi@example.com")
    for client in (asha, ravi):
        _import(client)
        sam = client.post("/api/v1/majra/people", json={"name": "Sam"}).json()["id"]
        client.post("/api/v1/majra/loans", json={"person_id": sam, "direction": "lent", "amount": "100",
                                                 "date": "2026-02-01", "description": "x"})
        client.put("/api/v1/budgets", json={"category": "Dining", "monthly_limit": "1000"})

    refused = asha.post("/api/v1/auth/delete-account", json={"password": "wrong-password", "confirm": True})
    assert refused.status_code == 401
    not_confirmed = asha.post("/api/v1/auth/delete-account", json={"password": TEST_PASSWORD, "confirm": False})
    assert not_confirmed.status_code == 401

    done = asha.post("/api/v1/auth/delete-account", json={"password": TEST_PASSWORD, "confirm": True}).json()
    assert done["deleted"] and done["rows_deleted"]["transactions"] == 1
    assert asha.get("/api/v1/auth/me").status_code == 401  # signed out for good
    login = asha.post("/api/v1/auth/login", json={"email": "asha@example.com", "password": TEST_PASSWORD})
    assert login.status_code == 401

    assert ravi.get("/api/v1/transactions").json()["total"] == 1  # the other account is untouched
    assert len(ravi.get("/api/v1/majra/groups").json()) == 1


def test_sessions_cannot_cross_users_even_by_mistake(database_url):
    """The isolation layer itself: a session bound to one user cannot read or write another's rows."""
    from sqlalchemy import select

    from moneyos.config import DataMode
    from moneyos.db.session import init_db
    from moneyos.db.tables import Account, User
    from moneyos.db.tenancy import TenancyError, system_session, user_session

    factory = init_db(database_url, DataMode.REAL)
    try:
        with system_session(factory) as admin:
            a, b = User(email="a@x.io"), User(email="b@x.io")
            admin.add_all([a, b])
            admin.commit()
            admin.add(Account(name="First bank", currency="INR", user_id=a.id))
            admin.commit()
            a_id, b_id = a.id, b.id
        with user_session(factory, b_id) as s:
            assert s.scalars(select(Account)).all() == []  # no filter written, none needed
            s.add(Account(name="sneaky", currency="INR", user_id=a_id))
            with pytest.raises(TenancyError):
                s.commit()
        with factory() as anonymous, pytest.raises(TenancyError):
            anonymous.scalars(select(Account)).all()
    finally:
        factory.kw["bind"].dispose()


def test_isolation_holds_when_users_alternate(database_url):
    """Regression: a cached query must never carry one user's filter to another.

    A lambda-based filter passed every single-user check but leaked data as
    soon as a second user queried in the same process.
    """
    from sqlalchemy import select

    from moneyos.config import DataMode
    from moneyos.db.session import init_db
    from moneyos.db.tables import Account, User
    from moneyos.db.tenancy import system_session, user_session

    factory = init_db(database_url, DataMode.REAL)
    try:
        with system_session(factory) as admin:
            users = [User(email=f"u{i}@x.io") for i in range(3)]
            admin.add_all(users)
            admin.commit()
            admin.add_all([Account(name=f"bank of {u.email}", currency="INR", user_id=u.id) for u in users])
            admin.commit()
            ids = [u.id for u in users]
        for uid in ids + list(reversed(ids)) + ids:
            with user_session(factory, uid) as s:
                names = [a.name for a in s.scalars(select(Account))]
                assert names == [f"bank of u{ids.index(uid)}@x.io"], (uid, names)
    finally:
        factory.kw["bind"].dispose()


def test_passwords_are_stored_hashed():
    stored = auth.hash_password("correct horse battery")
    assert "correct horse" not in stored and stored.startswith("scrypt$")
    assert auth.verify_password("correct horse battery", stored)
    assert not auth.verify_password("correct horse batterY", stored)
    assert auth.hash_password("same") != auth.hash_password("same")  # salted
    assert not auth.verify_password("anything", None)  # an account with no password cannot sign in


@pytest.mark.parametrize("bad", ["﻿correct horse battery", "correct horse battery\r", "correct\thorse battery"])
def test_invisible_characters_are_rejected(bad):
    from moneyos.services.errors import InvalidRequestError

    with pytest.raises(InvalidRequestError):
        auth.check_password_rules(bad)


def test_cli_password_from_a_windows_pipe(tmp_path, monkeypatch, capsys):
    """PowerShell pipes text with a byte-order mark and CRLF; the password must not include them."""
    import io

    from moneyos.cli import main

    url = f"sqlite:///{(tmp_path / 'cli.db').as_posix()}"
    monkeypatch.setenv("MONEYOS_DATABASE_URL", url)
    monkeypatch.setattr("sys.stdin", io.StringIO("﻿correct horse battery\r\n"))
    assert main(["user", "create", "me@example.com", "--password-stdin"]) == 0
    client = TestClient(create_app(Settings(database_url=url)))
    try:
        ok = client.post("/api/v1/auth/login", json={"email": "me@example.com", "password": "correct horse battery"})
        assert ok.status_code == 200
    finally:
        client.app.state.session_factory.kw["bind"].dispose()
