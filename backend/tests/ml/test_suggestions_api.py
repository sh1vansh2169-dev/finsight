"""Model suggestions over HTTP, with a small model trained for the test."""

import numpy as np
import pytest
from fastapi.testclient import TestClient

from moneyos.api.app import create_app
from moneyos.config import Settings
from moneyos.ml import categorizer as cat
from moneyos.ml.corpus import make_corpus


@pytest.fixture(scope="module")
def models_dir(tmp_path_factory):
    directory = tmp_path_factory.mktemp("models")
    corpus = make_corpus(11, per_category=15, mean_per_merchant=8)
    texts = np.asarray([c.text for c in corpus], dtype=object)
    labels = np.asarray([c.category for c in corpus], dtype=object)
    model = cat.make_model("tfidf_logreg").fit(texts, labels)
    cat.save_model(model, directory, name="tfidf_logreg", texts=list(texts), labels=list(labels),
                   metrics={}, training_data="synthetic test corpus")
    return directory


def _client(database_url, models_dir):
    return TestClient(create_app(Settings(database_url=database_url, models_dir=models_dir)))


@pytest.fixture
def client(database_url, models_dir):
    client = _client(database_url, models_dir)
    yield client
    client.app.state.session_factory.kw["bind"].dispose()


def _manual(client, description, direction="debit"):
    response = client.post("/api/v1/transactions", json={
        "date": "2026-03-05", "description": description, "amount": "450", "direction": direction})
    assert response.status_code == 201
    return response.json()["transaction"]


def test_no_model_yet(database_url, tmp_path):
    client = _client(database_url, tmp_path / "nothing")
    try:
        response = client.get("/api/v1/ml/category-suggestions")
        assert response.status_code == 404 and "moneyos ml categorization" in response.json()["detail"]
    finally:
        client.app.state.session_factory.kw["bind"].dispose()


def test_suggestions_only_for_uncategorised(client):
    rules_know = _manual(client, "CITY POWER ELECTRICITY BILL")  # categorised by the keyword rules
    unknown = _manual(client, "Paid to Zenith Medicos")  # no rule mentions "medicos"
    assert (rules_know["category_basis"], unknown["category_basis"]) == ("rule", "none")

    body = client.get("/api/v1/ml/category-suggestions").json()
    assert body["model_version"].startswith("categorizer-") and "synthetic" in body["note"]
    (suggestion,) = body["suggestions"]  # the rule-categorised one is left alone
    assert suggestion["transaction"]["id"] == unknown["id"]
    assert suggestion["category"] == "Health"
    assert 0 < suggestion["confidence"] <= 1 and len(suggestion["alternatives"]) == 2

    card = client.get("/api/v1/ml/categorizer").json()
    assert card["training_data"] == "synthetic test corpus"


def test_apply_marks_results_as_model_inferred_and_user_can_override(client):
    unknown = _manual(client, "Paid to Zenith Medicos")
    assert client.post("/api/v1/ml/category-suggestions/apply", json={"min_confidence": 0.5}).status_code == 422
    applied = client.post("/api/v1/ml/category-suggestions/apply", json={"min_confidence": 0.6}).json()
    assert applied["applied"] == 1 and applied["basis"] == "model"

    t = client.get(f"/api/v1/transactions/{unknown['id']}").json()
    assert (t["category"], t["category_basis"], t["txn_type"], t["type_basis"]) == ("Health", "model", "expense", "model")
    assert client.get("/api/v1/ml/category-suggestions").json()["suggestions"] == []  # nothing left to suggest

    corrected = client.patch(f"/api/v1/transactions/{unknown['id']}", json={"category": "Shopping"}).json()
    assert (corrected["category"], corrected["category_basis"]) == ("Shopping", "user")


def test_low_confidence_is_not_applied(client):
    _manual(client, "XQZ")  # nothing to go on
    body = client.get("/api/v1/ml/category-suggestions").json()
    assert body["suggestions"][0]["confident"] is False
    applied = client.post("/api/v1/ml/category-suggestions/apply", json={"min_confidence": 0.95}).json()
    assert applied["applied"] == 0


def test_a_deliberate_uncategorized_is_left_alone(client):
    """If you set "Uncategorized" yourself, that is a decision the model must respect."""
    t = _manual(client, "Paid to Zenith Medicos")
    client.patch(f"/api/v1/transactions/{t['id']}", json={"category": "Uncategorized"})
    assert client.get("/api/v1/ml/category-suggestions").json()["suggestions"] == []
    assert client.post("/api/v1/ml/category-suggestions/apply", json={"min_confidence": 0.6}).json()["applied"] == 0
