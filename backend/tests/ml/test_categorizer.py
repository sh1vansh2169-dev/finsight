"""Fast checks of the categorisation pipeline (the full experiment runs via `moneyos ml`)."""

import random

import numpy as np
import pytest
from sklearn.model_selection import StratifiedGroupKFold

from moneyos.ml import categorizer as cat
from moneyos.ml.corpus import CATEGORIES, make_corpus, make_merchants, render
from moneyos.ml.experiments import select
from moneyos.ml.text import prepare


@pytest.fixture(scope="module")
def small():
    corpus = make_corpus(5, per_category=12, mean_per_merchant=6)
    return (np.asarray([c.text for c in corpus], dtype=object), np.asarray([c.category for c in corpus], dtype=object),
            np.asarray([c.merchant for c in corpus], dtype=object))


@pytest.mark.parametrize(
    ("raw", "prepared"),
    [
        ("UPI/DR/412345678901/ROYAL KITCHEN/HDFC/royalkitchen@okaxis/Payment", "royal kitchen royalkitchen"),
        ("POS 412345XXXXXX9876 ELITE HOSPITAL PUNE", "elite hospital pune"),
        ("NEFT DR-SBIN0000123-SKY ACADEMY-998877665544", "sky academy"),
        ("Paid to Lotus Cinemas", "lotus cinemas"),
    ],
)
def test_prepare_strips_rails_codes_and_numbers(raw, prepared):
    assert prepare(raw) == prepared


def test_corpus_is_deterministic_and_covers_every_category():
    a, b = make_corpus(3, per_category=5), make_corpus(3, per_category=5)
    assert a == b and make_corpus(4, per_category=5) != a
    assert {c.category for c in a} == set(CATEGORIES)
    merchants = make_merchants(random.Random(0), per_category=20)
    assert len({m.name for m in merchants}) == len(merchants)  # names are unique
    assert all(render(random.Random(i), merchants[0]) for i in range(20))


def test_unseen_split_never_leaks_merchants(small):
    texts, labels, groups = small
    for train, test in StratifiedGroupKFold(5, shuffle=True, random_state=0).split(texts, labels, groups):
        assert not set(groups[train]) & set(groups[test])


def test_vocabulary_is_learned_from_training_data_only(small):
    """Leakage check: TF-IDF fitted inside the pipeline sees no test-only words."""
    texts, labels, groups = small
    train, test = next(StratifiedGroupKFold(5, shuffle=True, random_state=0).split(texts, labels, groups))
    model = cat.make_model("tfidf_logreg").fit(texts[train], labels[train])
    vocabulary = model.named_steps["features"].named_steps["tfidf"].transformer_list[0][1].vocabulary_
    train_words = {w for t in texts[train] for w in prepare(t).split()}
    test_only = {w for t in texts[test] for w in prepare(t).split()} - train_words
    assert test_only, "the fixture should contain words unique to test merchants"
    assert not test_only & set(vocabulary)


def test_rules_abstain_when_nothing_matches():
    model = cat.make_model("rules").fit(["x"], ["Dining"])
    assert list(model.predict(["CITY POWER ELECTRICITY BILL", "ZEBRA QWERTY"])) == ["Utilities", cat.UNCATEGORIZED]
    vocab = cat.make_model("vocabulary_rules").fit(["x"], ["Dining"])
    assert list(vocab.predict(["Paid to Lotus Cinemas", "ZEBRA"])) == ["Entertainment", cat.UNCATEGORIZED]


def test_evaluation_runs_and_learning_beats_the_majority(small):
    texts, labels, groups = small
    results = cat.evaluate(["majority", "rules", "tfidf_logreg"], texts, labels, groups, split="unseen", seed=0)
    assert all(len(r.folds) == 5 for r in results.values())
    assert results["tfidf_logreg"].mean("macro_f1") > results["majority"].mean("macro_f1") + 0.3
    logreg = results["tfidf_logreg"]
    assert 0 < logreg.mean("coverage") <= 1 and len(logreg.y_true) == len(texts)
    assert results["majority"].mean("coverage") == 1.0
    matrix = cat.confusion(logreg, sorted(set(labels)))
    assert matrix.sum() == len(texts)


def _fake(values):
    result = cat.ModelResult("x", "unseen")
    result.folds = [cat.FoldScore(0, 0, 0, v, 0, 0, 0) for v in values]
    return result


def test_selection_prefers_the_simpler_model_within_one_standard_deviation():
    close = {"tfidf_logreg": _fake([0.74, 0.76]), "tfidf_random_forest": _fake([0.75, 0.79]),
             "tfidf_xgboost": _fake([0.70, 0.72])}
    assert select(close) == "tfidf_logreg"  # forest 0.77 ± 0.028; logreg 0.75 is within it
    clear = {"tfidf_logreg": _fake([0.60, 0.61]), "tfidf_random_forest": _fake([0.80, 0.81]),
             "tfidf_xgboost": _fake([0.70, 0.71])}
    assert select(clear) == "tfidf_random_forest"


def test_saved_model_round_trip_with_card(small, tmp_path):
    texts, labels, _ = small
    model = cat.make_model("tfidf_logreg").fit(texts, labels)
    card_path = cat.save_model(model, tmp_path, name="tfidf_logreg", texts=list(texts), labels=list(labels),
                               metrics={"note": "test"}, training_data="synthetic test corpus")
    loaded, card = cat.load_latest(tmp_path)
    assert card_path.exists() and card["model"] == "tfidf_logreg"
    assert card["training_rows"] == len(texts) and card["labels"] == sorted(set(labels))
    assert card["training_data_sha256"] == cat.data_fingerprint(list(texts), list(labels))
    assert list(loaded.predict(texts[:20])) == list(model.predict(texts[:20]))
    assert cat.load_latest(tmp_path / "empty") == (None, None)
