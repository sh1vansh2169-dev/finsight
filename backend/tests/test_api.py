"""HTTP API tests using FastAPI's TestClient against a temporary SQLite file."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from moneyos.api.app import create_app
from moneyos.cli import main
from moneyos.config import DataMode, Settings
from moneyos.domain import synthetic

COFFEE = b"Date,Description,Amount,Account\n07/02/2026,CHAI POINT CAFE,-120.00,Wallet\n"


@pytest.fixture
def make_client(database_url):
    clients = []

    def _make(**settings) -> TestClient:
        settings.setdefault("database_url", database_url)
        client = TestClient(create_app(Settings(**settings)))
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.app.state.session_factory.kw["bind"].dispose()


@pytest.fixture
def client(make_client):
    return make_client()


def _upload(client, content, name="file.csv", **form):
    return client.post("/api/v1/imports/preview", files={"file": (name, content, "text/csv")}, data=form)


def _import(client, content, name="file.csv", **form):
    preview = _upload(client, content, name, **form)
    assert preview.status_code == 201, preview.text
    commit = client.post(f"/api/v1/imports/{preview.json()['batch']['id']}/commit")
    assert commit.status_code == 200, commit.text
    return commit.json()


def _load_sample(client, dataset):
    for name, text in dataset.files.items():
        form = {"account": synthetic.CARD_ACCOUNT} if "card" in name else {}
        _import(client, text.encode("utf-8"), name, **form)


def test_health(client, make_client, tmp_path):
    assert client.get("/health").json() == {
        "status": "ok", "version": "0.6.0", "data_mode": "real", "sample_data": False,
    }
    sample = make_client(
        data_mode=DataMode.SAMPLE, database_url=f"sqlite:///{(tmp_path / 's.db').as_posix()}"
    )
    assert sample.get("/health").json()["sample_data"] is True


def test_preview_then_commit(client):
    preview = _upload(client, COFFEE + b"08/02/2026,BAD,abc,Wallet\n", "wallet.csv")
    assert preview.status_code == 201
    body = preview.json()
    assert body["batch"]["status"] == "previewed"
    assert [(r["source_row"], r["outcome"]) for r in body["rows"]] == [(2, "new"), (3, "rejected")]
    assert body["rows"][0]["transaction"]["amount"] == "-120.00"
    assert body["rows"][1]["reason"] == "unparseable amount: 'abc'"
    assert client.get("/api/v1/transactions").json()["total"] == 0  # nothing committed yet

    batch_id = body["batch"]["id"]
    committed = client.post(f"/api/v1/imports/{batch_id}/commit").json()
    assert (committed["status"], committed["inserted_rows"]) == ("committed", 1)

    page = client.get("/api/v1/transactions").json()
    assert page["total"] == 1
    item = page["items"][0]
    assert item["amount"] == "-120.00"  # money is a string, never a float
    assert (item["direction"], item["txn_type"], item["type_basis"]) == ("debit", "expense", "rule")
    assert (item["account"], item["source"], item["import_batch_id"]) == ("Wallet", "csv_import", batch_id)

    history = client.get("/api/v1/imports").json()
    assert [b["id"] for b in history] == [batch_id]
    assert client.get(f"/api/v1/imports/{batch_id}").json()["rows"][1]["outcome"] == "rejected"


def test_repeat_import_is_flagged_and_adds_nothing(client):
    first = _import(client, COFFEE)
    preview = _upload(client, COFFEE).json()
    assert preview["batch"]["duplicate_rows"] == 1
    assert preview["batch"]["warnings"] == [f"This exact file was already imported (import {first['id']})."]
    assert client.post(f"/api/v1/imports/{preview['batch']['id']}/commit").json()["inserted_rows"] == 0


def test_import_errors(client):
    bad = _upload(client, b"When,What\n1,2\n")
    assert bad.status_code == 422
    assert "missing required column" in bad.json()["detail"]

    assert _upload(client, b"x" * (5 * 1024 * 1024 + 1)).status_code == 413
    assert _upload(client, COFFEE, currency="rupees").status_code == 422
    assert client.post("/api/v1/imports/999/commit").status_code == 404

    batch_id = _import(client, COFFEE)["id"]
    again = client.post(f"/api/v1/imports/{batch_id}/commit")
    assert again.status_code == 409 and "already committed" in again.json()["detail"]


def test_discard(client):
    batch_id = _upload(client, COFFEE).json()["batch"]["id"]
    assert client.post(f"/api/v1/imports/{batch_id}/discard").json()["status"] == "discarded"
    assert client.get(f"/api/v1/imports/{batch_id}").json()["rows"] == []
    assert client.post(f"/api/v1/imports/{batch_id}/commit").status_code == 409


def test_summary_matches_ground_truth(client, dataset):
    _load_sample(client, dataset)
    body = client.get("/api/v1/summary").json()
    expected = dataset.expected

    assert "not a bank balance" in body["note"]
    assert body["sample_data"] is False
    inr = body["currencies"]["INR"]
    assert Decimal(inr["income"]) == expected.income
    assert Decimal(inr["expenses"]) == expected.expenses
    assert Decimal(inr["net_cash_flow"]) == expected.net_cash_flow
    assert Decimal(inr["unclassified_outflow"]) == expected.unclassified_outflow
    assert any("unknown type" in w for w in inr["warnings"])

    march = client.get("/api/v1/summary", params={"start": "2026-03-01", "end": "2026-03-31"}).json()
    assert list(march["currencies"]["INR"]["by_month"]) == ["2026-03"]


def test_transaction_filters_and_paging(client, dataset):
    _load_sample(client, dataset)
    unknown = client.get("/api/v1/transactions", params={"txn_type": "unknown"}).json()
    assert unknown["total"] == 2

    page = client.get("/api/v1/transactions", params={"limit": 3, "offset": 3}).json()
    assert (page["limit"], page["offset"], len(page["items"])) == (3, 3, 3)
    assert client.get("/api/v1/transactions", params={"limit": 501}).status_code == 422
    assert client.get("/api/v1/transactions", params={"txn_type": "salary"}).status_code == 422

    accounts = {a["name"] for a in client.get("/api/v1/accounts").json()}
    assert accounts == {"Sample Savings 0001", synthetic.CARD_ACCOUNT}


def test_manual_entry(client):
    response = client.post(
        "/api/v1/transactions",
        json={"date": "2026-03-01", "description": "  Lunch at cafe ", "amount": "250.50", "direction": "debit"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    t = body["transaction"]
    assert (t["description"], t["amount"], t["account"], t["source"]) == ("Lunch at cafe", "-250.50", "Cash", "manual")
    assert (t["category"], t["txn_type"]) == ("Dining", "expense")
    assert body["warnings"] == []


@pytest.mark.parametrize(
    "change",
    [
        {"amount": "-5"},
        {"amount": "0"},
        {"amount": "1.005"},
        {"amount": 1.5},  # JSON float: accepted by pydantic as a number; see next case
        {"direction": "sideways"},
        {"txn_type": "income"},  # a debit cannot be income
        {"currency": "RUPEE"},
        {"description": ""},
        {"unexpected": "field"},
    ],
)
def test_manual_entry_validation(client, change):
    body = {"date": "2026-03-01", "description": "X", "amount": "10", "direction": "debit", **change}
    response = client.post("/api/v1/transactions", json=body)
    if change == {"amount": 1.5}:
        # Floats with an exact two-place value are accepted and stored exactly.
        assert response.status_code == 201
        assert response.json()["transaction"]["amount"] == "-1.50"
    else:
        assert response.status_code == 422, (change, response.text)


def test_correction_and_audit(client, dataset):
    _load_sample(client, dataset)
    unknown = client.get("/api/v1/transactions", params={"txn_type": "unknown"}).json()["items"]
    debit = next(t for t in unknown if t["direction"] == "debit")

    patched = client.patch(f"/api/v1/transactions/{debit['id']}", json={"txn_type": "lent", "category": "Friends"})
    assert patched.status_code == 200
    assert (patched.json()["txn_type"], patched.json()["type_basis"]) == ("lent", "user")
    assert patched.json()["category_basis"] == "user"

    audit = client.get(f"/api/v1/transactions/{debit['id']}/audit").json()
    assert [e["action"] for e in audit] == ["transaction_corrected"]
    assert audit[0]["details"]["before"]["txn_type"] == "unknown"

    assert client.patch(f"/api/v1/transactions/{debit['id']}", json={"txn_type": "income"}).status_code == 422
    assert client.patch(f"/api/v1/transactions/{debit['id']}", json={}).status_code == 422
    assert client.patch("/api/v1/transactions/999", json={"category": "X"}).status_code == 404


def test_api_token(make_client):
    client = make_client(api_token="s3cret-token")
    assert client.get("/health").status_code == 200  # no personal data
    assert client.get("/api/v1/transactions").status_code == 401
    assert client.get("/api/v1/transactions", headers={"Authorization": "Bearer wrong"}).status_code == 401
    ok = client.get("/api/v1/transactions", headers={"Authorization": "Bearer s3cret-token"})
    assert ok.status_code == 200


def test_cli_serve_refuses_public_host_without_token(monkeypatch, capsys):
    monkeypatch.delenv("MONEYOS_API_TOKEN", raising=False)
    assert main(["serve", "--host", "0.0.0.0"]) == 2
    assert "non-loopback" in capsys.readouterr().err


def test_cli_seed_sample_creates_a_separate_sample_database(tmp_path, capsys):
    url = f"sqlite:///{(tmp_path / 'sample.db').as_posix()}"
    assert main(["seed-sample", "--database", url]) == 0
    assert synthetic.SAMPLE_MARKER in capsys.readouterr().out

    sample_client = TestClient(create_app(Settings(data_mode=DataMode.SAMPLE, database_url=url)))
    try:
        assert sample_client.get("/api/v1/summary").json()["sample_data"] is True
    finally:
        sample_client.app.state.session_factory.kw["bind"].dispose()

    from moneyos.db.session import DataModeError

    with pytest.raises(DataModeError):
        create_app(Settings(data_mode=DataMode.REAL, database_url=url))


def test_duplicate_review_over_http(client, dataset):
    _load_sample(client, dataset)
    app = dataset.payapp
    _import(client, app.text.encode("utf-8"), app.name, account=synthetic.PAYAPP_ACCOUNT)

    summary = client.get("/api/v1/summary").json()
    pending = summary["open_duplicate_reviews"]
    assert pending == len(app.mirrored) + 1
    assert "may count them twice" in summary["warnings"][0]

    items = client.get("/api/v1/review/duplicates").json()
    assert len(items) == pending
    item = items[0]
    assert item["confidence"] == "high" and item["reasons"] and len(item["transactions"]) == 2
    a, b = item["transactions"]

    bad = client.post(f"/api/v1/review/duplicates/{item['id']}/resolve", json={"decision": "duplicate"})
    assert bad.status_code == 422  # must say which record to keep
    not_in_pair = client.post(
        f"/api/v1/review/duplicates/{item['id']}/resolve",
        json={"decision": "duplicate", "keep_transaction_id": 999_999},
    )
    assert not_in_pair.status_code == 422

    resolved = client.post(
        f"/api/v1/review/duplicates/{item['id']}/resolve",
        json={"decision": "duplicate", "keep_transaction_id": a["id"]},
    )
    assert resolved.status_code == 200
    assert (resolved.json()["status"], resolved.json()["kept_transaction_id"]) == ("duplicate", a["id"])
    assert client.get("/api/v1/summary").json()["open_duplicate_reviews"] == pending - 1

    hidden = client.get(f"/api/v1/transactions/{b['id']}").json()
    assert hidden["duplicate_of_id"] == a["id"]
    listed = {t["id"] for t in client.get("/api/v1/transactions", params={"limit": 500}).json()["items"]}
    assert b["id"] not in listed
    with_dupes = client.get("/api/v1/transactions", params={"limit": 500, "include_duplicates": True}).json()
    assert b["id"] in {t["id"] for t in with_dupes["items"]}

    again = client.post(f"/api/v1/review/duplicates/{item['id']}/resolve", json={"decision": "distinct"})
    assert again.status_code == 409
    reopened = client.post(f"/api/v1/review/duplicates/{item['id']}/reopen")
    assert reopened.json()["status"] == "open"
    assert client.get(f"/api/v1/transactions/{b['id']}").json()["duplicate_of_id"] is None

    assert client.post("/api/v1/review/duplicates/scan").json() == {"new_candidates": 0}
    assert client.post("/api/v1/review/duplicates/999/reopen").status_code == 404
