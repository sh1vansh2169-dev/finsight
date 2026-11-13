"""Search, categories, and serving the built web app."""

import pytest
from fastapi.testclient import TestClient

from conftest import sign_up
from moneyos.api.app import create_app
from moneyos.config import Settings


@pytest.fixture
def dist(tmp_path):
    folder = tmp_path / "dist"
    (folder / "assets").mkdir(parents=True)
    (folder / "index.html").write_text("<!doctype html><title>MoneyOS</title>", encoding="utf-8")
    (folder / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside the app", encoding="utf-8")
    return folder


@pytest.fixture
def client(database_url, dist):
    client = TestClient(create_app(Settings(database_url=database_url, frontend_dist=dist)))
    yield client
    client.app.state.session_factory.kw["bind"].dispose()


def test_serves_the_app_with_security_headers(client):
    for path in ("/", "/transactions", "/money-majra/groups/3"):  # client-side routes load the app
        page = client.get(path)
        assert page.status_code == 200 and "<title>MoneyOS</title>" in page.text, path
        assert "script-src 'self'" in page.headers["content-security-policy"]
        assert page.headers["x-frame-options"] == "DENY"
    asset = client.get("/assets/app.js")
    assert asset.status_code == 200 and asset.text == "console.log(1)"


def test_api_and_docs_are_not_swallowed_by_the_app(client):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/api/v1/transactions").status_code == 401  # still the API, still protected
    assert client.get("/api/v1/no-such-route").status_code in (401, 404)
    assert "swagger" in client.get("/docs").text.lower()


def test_no_files_outside_the_app_folder(client):
    for path in ("/../secret.txt", "/assets/../../secret.txt", "/%2e%2e/secret.txt"):
        response = client.get(path)
        assert "outside the app" not in response.text, path


def test_without_a_build_the_root_is_simply_not_found(database_url, tmp_path):
    client = TestClient(create_app(Settings(database_url=database_url, frontend_dist=tmp_path / "missing")))
    try:
        assert client.get("/").status_code == 404
    finally:
        client.app.state.session_factory.kw["bind"].dispose()


def test_search_and_categories(client):
    sign_up(client)
    for description in ("Chai Point Cafe", "FreshMart 100% organic", "Metro_card recharge"):
        client.post("/api/v1/transactions", json={"date": "2026-03-01", "description": description,
                                                  "amount": "10", "direction": "debit"})

    def found(q):
        return [t["description"] for t in client.get("/api/v1/transactions", params={"q": q}).json()["items"]]

    assert found("CHAI") == ["Chai Point Cafe"]  # case-insensitive
    assert found("100%") == ["FreshMart 100% organic"]  # % is a character, not a wildcard
    assert found("chai_point") == []  # _ is a character too (as a wildcard it would match "Chai Point")
    assert found("metro_") == ["Metro_card recharge"]
    assert len(found("   ")) == 3  # blank search means no filter
    categories = client.get("/api/v1/categories").json()
    assert {"Dining", "Groceries", "Transport"} <= set(categories) and categories[-1] == "Uncategorized"
