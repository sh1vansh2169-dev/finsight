import numpy as np
import pandas as pd
import pytest

from moneyos.ml import anomaly


def _stream(rows):
    return pd.DataFrame(rows, columns=["day", "category", "amount", "label", "kind"])


def test_spike_is_flagged_with_a_plain_explanation():
    rows = [(d, "Dining", 400 + (d % 5) * 20, 0, "normal") for d in range(30)]
    rows.append((31, "Dining", 8000.0, 1, "amount_spike"))
    flags = anomaly.personal_scores(_stream(rows), robust=True)
    assert not any(f.flagged for f in flags[:-1])
    last = flags[-1]
    assert last.flagged and "x your typical Dining payment" in last.reason
    assert "fraud" not in last.reason.lower()


def test_no_judgement_without_enough_history():
    rows = [(d, "Health", 300.0, 0, "normal") for d in range(anomaly.MIN_HISTORY - 1)]
    rows.append((20, "Health", 30000.0, 1, "amount_spike"))
    assert not any(f.flagged for f in anomaly.personal_scores(_stream(rows), robust=True))


def test_scores_use_only_earlier_payments():
    rows = [(d, "Groceries", 500.0 + d, 0, "normal") for d in range(40)]
    base = anomaly.personal_scores(_stream(rows), robust=False)
    tampered = rows[:21] + [(d, c, a * 50, l, k) for d, c, a, l, k in rows[21:]]  # change only the future
    changed = anomaly.personal_scores(_stream(tampered), robust=False)
    assert [f.score for f in base[:21]] == [f.score for f in changed[:21]]
    assert base[30].score != changed[30].score  # and the tampering did reach later payments


def test_low_amounts_are_not_flagged():
    rows = [(d, "Dining", 500.0, 0, "normal") for d in range(30)] + [(31, "Dining", 5.0, 0, "normal")]
    assert not anomaly.personal_scores(_stream(rows), robust=True)[-1].flagged


def test_simulated_stream_is_deterministic_and_labelled():
    a, b = anomaly.simulate_stream(7), anomaly.simulate_stream(7)
    pd.testing.assert_frame_equal(a, b)
    assert set(a["kind"]) <= {"normal", "amount_spike", "large_but_normal", "unusual_category"}
    assert (a.loc[a["kind"] == "large_but_normal", "label"] == 0).all()  # decoys are not anomalies
    assert (a.loc[a["kind"].isin(["amount_spike", "unusual_category"]), "label"] == 1).all()


def test_models_never_flag_their_own_training_period():
    stream = anomaly.simulate_stream(3)
    for method in ("isolation_forest", "lof"):
        flags = anomaly.model_scores(stream, method, train_days=180)
        assert flags[(stream["day"] < 180).to_numpy()].sum() == 0


def test_evaluation_and_bootstrap():
    results = anomaly.evaluate([1, 2])
    for m in anomaly.METHODS:
        r = results[m]
        assert 0 <= r["precision"] <= 1 and 0 <= r["recall"] <= 1
        assert r["tp"] + r["fn"] > 0
    low, high = anomaly.bootstrap_f1([{"tp": 8, "fp": 2, "fn": 2}, {"tp": 1, "fp": 5, "fn": 3}])
    assert 0 <= low <= high <= 1
    assert anomaly.bootstrap_f1([{"tp": 5, "fp": 0, "fn": 0}] * 3) == (1.0, 1.0)
