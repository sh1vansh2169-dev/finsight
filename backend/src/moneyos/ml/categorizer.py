"""Transaction categorisation: baselines, candidate models, evaluation, persistence.

Hyperparameters are fixed in advance (``PREREGISTERED``) rather than tuned
on test folds, so the comparison between models is not biased by tuning.
"""

from __future__ import annotations

import hashlib
import json
import platform
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support
from sklearn.model_selection import StratifiedGroupKFold, StratifiedKFold
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.preprocessing import FunctionTransformer, LabelEncoder

from moneyos.domain.classify import Rules, load_rules
from moneyos.domain.cleaning import normalize_key
from moneyos.ml.text import prepare

UNCATEGORIZED = "Uncategorized"
# Fixed before any results were seen. Changing them means a new experiment.
PREREGISTERED = {
    "word_ngrams": (1, 2),
    "char_ngrams": (3, 5),
    "char_max_features": 20000,
    "logreg_C": 5.0,
    "forest_trees": 300,
    "xgb_trees": 200,
    "xgb_depth": 6,
    "confidence_threshold": 0.6,
    "folds": 5,
}


def prepare_all(texts) -> list[str]:
    # Module-level (not a lambda) so fitted pipelines can be saved with joblib.
    return [prepare(t) for t in texts]


def _features() -> Pipeline:
    return Pipeline([
        ("prepare", FunctionTransformer(prepare_all)),
        ("tfidf", FeatureUnion([
            ("words", TfidfVectorizer(ngram_range=PREREGISTERED["word_ngrams"], sublinear_tf=True)),
            ("chars", TfidfVectorizer(analyzer="char_wb", ngram_range=PREREGISTERED["char_ngrams"],
                                      min_df=2, sublinear_tf=True, max_features=PREREGISTERED["char_max_features"])),
        ])),
    ])


class RulesClassifier(ClassifierMixin, BaseEstimator):
    """The app's keyword rules as a classifier. Abstains (Uncategorized) when no rule matches."""

    def __init__(self, rules: Rules | None = None):
        self.rules = rules

    def fit(self, X, y):
        self.rules_ = self.rules or load_rules()
        self.classes_ = np.unique(np.asarray(y))
        return self

    def predict(self, X):
        out = []
        for text in X:
            padded = f" {normalize_key(text)} "
            match = next((r.label for r in self.rules_.category_rules if r.matches(padded, r.direction or _ANY)), None)
            out.append(match or UNCATEGORIZED)
        return np.asarray(out, dtype=object)


class VocabularyRulesClassifier(ClassifierMixin, BaseEstimator):
    """Keyword rules built from the synthetic generator's own descriptor lists.

    A reference, not a fair competitor: on synthetic data these rules know
    exactly the words the generator uses, so they show roughly the best that
    keyword matching can do here. Shared descriptors go to the first
    category that lists them; merchants without a descriptor are missed.
    """

    def fit(self, X, y):
        from moneyos.ml.corpus import _DESCRIPTORS

        self.keywords_ = [
            (category, normalize_key(word)) for category, words in _DESCRIPTORS.items() for word in words
        ]
        self.classes_ = np.unique(np.asarray(y))
        return self

    def predict(self, X):
        out = []
        for text in X:
            padded = f" {normalize_key(text)} "
            out.append(next((c for c, k in self.keywords_ if f" {k} " in padded), UNCATEGORIZED))
        return np.asarray(out, dtype=object)


class _AnyDirection:
    def __eq__(self, other):  # a rule's direction check always passes
        return True


_ANY = _AnyDirection()


class EncodedXGB(ClassifierMixin, BaseEstimator):
    """XGBoost needs integer labels; this keeps the string-label interface."""

    def __init__(self, n_estimators=200, max_depth=6, random_state=0):
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.random_state = random_state

    def fit(self, X, y):
        from xgboost import XGBClassifier

        self.encoder_ = LabelEncoder().fit(y)
        self.classes_ = self.encoder_.classes_
        self.model_ = XGBClassifier(
            n_estimators=self.n_estimators, max_depth=self.max_depth, learning_rate=0.1, tree_method="hist",
            random_state=self.random_state, n_jobs=-1, verbosity=0,
        )
        self.model_.fit(X, self.encoder_.transform(y))
        return self

    def predict_proba(self, X):
        return self.model_.predict_proba(X)

    def predict(self, X):
        return self.encoder_.inverse_transform(self.model_.predict(X))


def make_model(name: str, seed: int = 0):
    """A fresh, unfitted model by name."""
    if name == "majority":
        return DummyClassifier(strategy="most_frequent")
    if name == "rules":
        return RulesClassifier()
    if name == "vocabulary_rules":
        return VocabularyRulesClassifier()
    if name == "tfidf_logreg":
        clf = LogisticRegression(C=PREREGISTERED["logreg_C"], max_iter=3000, class_weight="balanced")
    elif name == "tfidf_random_forest":
        clf = RandomForestClassifier(n_estimators=PREREGISTERED["forest_trees"], n_jobs=-1, random_state=seed,
                                     class_weight="balanced_subsample")
    elif name == "tfidf_xgboost":
        clf = EncodedXGB(PREREGISTERED["xgb_trees"], PREREGISTERED["xgb_depth"], seed)
    else:
        raise ValueError(f"unknown model {name!r}")
    return Pipeline([("features", _features()), ("classifier", clf)])


MODEL_NAMES = ("majority", "rules", "vocabulary_rules", "tfidf_logreg", "tfidf_random_forest", "tfidf_xgboost")


@dataclass
class FoldScore:
    accuracy: float
    macro_precision: float
    macro_recall: float
    macro_f1: float
    coverage: float  # share of predictions confident enough to show (or rules that matched)
    covered_accuracy: float  # accuracy on those
    fit_seconds: float


@dataclass
class ModelResult:
    name: str
    split: str
    folds: list[FoldScore] = field(default_factory=list)
    y_true: list[str] = field(default_factory=list)
    y_pred: list[str] = field(default_factory=list)

    def mean(self, metric: str) -> float:
        return float(np.mean([getattr(f, metric) for f in self.folds]))

    def std(self, metric: str) -> float:
        return float(np.std([getattr(f, metric) for f in self.folds], ddof=1)) if len(self.folds) > 1 else 0.0


def _score(model, X_test, y_test, labels, fit_seconds) -> tuple[FoldScore, np.ndarray]:
    predicted = np.asarray(model.predict(X_test), dtype=object)
    if hasattr(model, "predict_proba") and not isinstance(model, DummyClassifier):
        confident = model.predict_proba(X_test).max(axis=1) >= PREREGISTERED["confidence_threshold"]
    else:
        confident = predicted != UNCATEGORIZED
    p, r, f1, _ = precision_recall_fscore_support(y_test, predicted, labels=labels, average="macro", zero_division=0)
    covered = confident.mean()
    covered_acc = accuracy_score(np.asarray(y_test)[confident], predicted[confident]) if confident.any() else 0.0
    return FoldScore(accuracy_score(y_test, predicted), p, r, f1, float(covered), float(covered_acc), fit_seconds), predicted


def evaluate(
    names: Sequence[str],
    texts: Sequence[str],
    labels: Sequence[str],
    groups: Sequence[str],
    *,
    split: str,
    seed: int,
) -> dict[str, ModelResult]:
    """Cross-validate every model on the same folds.

    ``split="seen"``: stratified K-fold by transaction (a merchant can be in
    train and test). ``split="unseen"``: stratified group K-fold by merchant,
    so test merchants never appear in training.
    """
    X, y, g = np.asarray(texts, dtype=object), np.asarray(labels, dtype=object), np.asarray(groups, dtype=object)
    category_labels = sorted(set(labels))
    if split == "seen":
        folds = StratifiedKFold(PREREGISTERED["folds"], shuffle=True, random_state=seed).split(X, y)
    elif split == "unseen":
        folds = StratifiedGroupKFold(PREREGISTERED["folds"], shuffle=True, random_state=seed).split(X, y, g)
    else:
        raise ValueError(split)
    results = {name: ModelResult(name, split) for name in names}
    for train, test in folds:
        if split == "unseen":
            assert not set(g[train]) & set(g[test]), "merchant leaked across the split"
        for name in names:
            model = make_model(name, seed)
            started = time.perf_counter()
            model.fit(X[train], y[train])
            score, predicted = _score(model, X[test], y[test], category_labels, time.perf_counter() - started)
            results[name].folds.append(score)
            results[name].y_true.extend(y[test])
            results[name].y_pred.extend(predicted)
    return results


def confusion(result: ModelResult, labels: Sequence[str]) -> np.ndarray:
    return confusion_matrix(result.y_true, result.y_pred, labels=list(labels))


# -------------------------------------------------------------- persistence


def data_fingerprint(texts: Sequence[str], labels: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for text, label in zip(texts, labels):
        digest.update(f"{label}\t{text}\n".encode())
    return digest.hexdigest()


def save_model(model, directory: Path, *, name: str, texts: Sequence[str], labels: Sequence[str],
               metrics: dict, training_data: str) -> Path:
    """Write ``<version>.joblib`` plus a JSON model card next to it."""
    import joblib
    import sklearn

    directory.mkdir(parents=True, exist_ok=True)
    fingerprint = data_fingerprint(texts, labels)
    version = f"categorizer-{datetime.now(UTC):%Y%m%d}-{fingerprint[:8]}"
    joblib.dump(model, directory / f"{version}.joblib")
    card = {
        "version": version,
        "model": name,
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "training_data": training_data,
        "training_rows": len(texts),
        "training_data_sha256": fingerprint,
        "labels": sorted(set(labels)),
        "preregistered": {k: list(v) if isinstance(v, tuple) else v for k, v in PREREGISTERED.items()},
        "evaluation": metrics,
        "libraries": {"python": platform.python_version(), "scikit-learn": sklearn.__version__},
    }
    path = directory / f"{version}.json"
    path.write_text(json.dumps(card, indent=2), encoding="utf-8")
    return path


def load_latest(directory: Path):
    """(model, card) for the newest saved categoriser, or (None, None)."""
    import joblib

    cards = sorted(directory.glob("categorizer-*.json")) if directory.exists() else []
    if not cards:
        return None, None
    card = json.loads(cards[-1].read_text(encoding="utf-8"))
    return joblib.load(directory / f"{card['version']}.joblib"), card
