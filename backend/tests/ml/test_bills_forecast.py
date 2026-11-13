"""E5 (research Model B) checks: the bill simulation, no leakage, and the decision rule."""

import numpy as np
import pandas as pd
import pytest

from moneyos.ml import bills_forecast as bf
from moneyos.ml import forecasting as fc
from moneyos.ml.spending_sim import make_profile, simulate


@pytest.fixture(scope="module")
def people():
    return [(make_profile(s), simulate(make_profile(s))) for s in range(1, 9)]


def test_ideal_bills_are_paid_as_recorded(people):
    for profile, frame in people:
        built = bf.build(profile, frame, "ideal")
        assert built["paid_unrecorded"].sum() == 0
        fixed = built["expected"] - (profile.utility * (frame.index.day == 10))  # all but the varying utility bill
        paid_fixed = built["paid_recorded"] - built["paid_recorded"].where(frame.index.day == 10, 0)
        assert np.allclose(fixed, paid_fixed, atol=0.02)  # on time, to the rupee
        assert np.allclose(built["total"], built["paid_recorded"] + built["everyday"] + built["one_off"], atol=0.02)


def test_realistic_bills_differ_from_the_record(people):
    late = unrecorded = stale = 0
    for profile, frame in people:
        built = bf.build(profile, frame, "realistic")
        unrecorded += built["paid_unrecorded"].sum() > 0
        paid_days, due_days = set(np.flatnonzero(built["paid_recorded"])), set(np.flatnonzero(built["expected"]))
        late += len(paid_days - due_days) > 0
        stale += abs(built["expected"].sum() - built["paid_recorded"].sum()) > 1
        assert np.allclose(built["total"], built[["paid_recorded", "paid_unrecorded", "everyday", "one_off"]].sum(axis=1),
                           atol=0.02)
        assert np.allclose(built["rest"], built["total"] - built["paid_recorded"], atol=0.02)
    # Across 8 people each kind of mismatch happens at least once.
    assert late and unrecorded and stale


def test_bill_simulation_is_deterministic(people):
    profile, frame = people[0]
    assert bf.build(profile, frame, "realistic").equals(bf.build(profile, frame, "realistic"))


def test_forecasts_never_see_the_future(people):
    """Changing anything actually paid after the origin must not change a forecast.
    (The bill record is known in advance, so it may be used.)"""
    profile, frame = people[0]
    built = bf.build(profile, frame, "realistic")
    changed = built.copy()
    origin = 603  # an actual forecast origin (120 + 7k)
    changed.iloc[origin + 1:, changed.columns.get_indexer(["total", "rest", "paid_recorded", "everyday"])] *= 3
    first, second = bf.run([built]), bf.run([changed])
    at = first["origin"] == origin
    assert at.sum() == 2  # one row per horizon: the check below must not be vacuous
    methods = [*bf.A_METHODS, *bf.B_METHODS]
    assert np.allclose(first.loc[at, methods].to_numpy(), second.loc[at, methods].to_numpy())
    assert not np.allclose(first.loc[at, "actual"], second.loc[at, "actual"])  # the target did change


def test_model_b_adds_recorded_bills_to_a_baseline():
    rest = np.full(100, 10.0)
    expected = np.zeros(130)
    expected[[101, 105, 120]] = [500, 50, 7]
    assert bf.model_b(rest, expected, 99, 7, fc.historical_mean) == pytest.approx(70 + 550)
    assert bf.model_b(rest, expected, 99, 30, fc.historical_mean) == pytest.approx(300 + 557)


def _table(b_error: float, noise: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(1)
    rows = []
    for period in ("calibration", "test"):
        for horizon in fc.HORIZONS:
            for profile in range(10):
                for origin in range(20):
                    actual = 1000 + rng.normal(0, 50)
                    row = {"profile": profile, "horizon": horizon, "origin": origin, "period": period, "actual": actual}
                    for m in bf.A_METHODS:
                        row[m] = actual + rng.choice([-100, 100])
                    for m in bf.B_METHODS:
                        row[m] = actual + rng.choice([-b_error, b_error]) + rng.normal(0, noise)
                    rows.append(row)
    return pd.DataFrame(rows)


def test_the_decision_rule():
    clearly_better = bf.evaluate(_table(b_error=50), resamples=300)
    assert all(r["meets_criterion"] for r in clearly_better.values())
    assert all(r["relative_change"] == pytest.approx(-0.5, abs=0.02) for r in clearly_better.values())

    slightly_better = bf.evaluate(_table(b_error=97), resamples=300)  # 3% better: below the 5% bar
    assert not any(r["meets_criterion"] for r in slightly_better.values())

    worse = bf.evaluate(_table(b_error=150), resamples=300)
    assert not any(r["meets_criterion"] for r in worse.values())
    assert all(r["difference_ci95"][0] > 0 for r in worse.values())
