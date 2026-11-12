"""Forecasting protocol checks: no leakage, purged splits, correct metrics."""

import numpy as np
import pandas as pd
import pytest

from moneyos.ml import forecasting as fc
from moneyos.ml.spending_sim import make_profile, simulate


@pytest.fixture(scope="module")
def profile():
    return simulate(make_profile(3))


def test_simulator_is_deterministic_and_adds_up(profile):
    assert simulate(make_profile(3)).equals(profile)
    parts = profile["commitments"] + profile["everyday"] + profile["one_off"]
    assert np.allclose(parts, profile["total"], atol=0.02)
    assert (profile[["scheduled", "commitments", "everyday", "one_off", "total"]] >= 0).all().all()
    weekend = profile.index.day_of_week >= 5
    assert profile["everyday"][weekend].mean() > profile["everyday"][~weekend].mean() * 0.95  # weekend effect present


def test_periods_are_purged():
    for horizon in fc.HORIZONS:
        for o in fc.origins(730, horizon):
            period = fc.period_of(o, horizon)
            end = o + horizon
            if period == "train":
                assert end < fc.CAL_START
            elif period == "calibration":
                assert o >= fc.CAL_START and end < fc.TEST_START
            elif period == "test":
                assert o >= fc.TEST_START and end < 730
            else:  # straddles a boundary, so it is dropped
                assert o + horizon >= fc.CAL_START or o + horizon >= fc.TEST_START


def test_forecasts_use_only_the_past(profile):
    """Changing anything after the origin must not change features or baseline forecasts."""
    series, dates = profile["total"].to_numpy(), profile.index
    o, h = 500, 30
    tampered = series.copy()
    tampered[o + 1:] *= 10
    target_dates = dates[o + 1: o + 1 + h]
    assert fc.features(series[: o + 1], target_dates, h) == fc.features(tampered[: o + 1], target_dates, h)
    for fn in fc.BASELINES.values():
        assert fn(series[: o + 1], h) == fn(tampered[: o + 1], h)
    assert fc.target(series, o, h) != fc.target(tampered, o, h)


def test_baselines_on_a_tiny_series():
    history = np.arange(1, 101, dtype=float)  # 1..100
    assert fc.historical_mean(history, 7) == pytest.approx(50.5 * 7)
    assert fc.last_period(history, 7) == sum(range(94, 101))
    assert fc.moving_average_90(history, 7) == pytest.approx(np.arange(11, 101).mean() * 7)
    assert fc.same_window_last_month(history, 7) == sum(range(71, 78))  # days 71-77
    assert fc.target(np.arange(10, dtype=float), 3, 4) == 4 + 5 + 6 + 7


def test_scores():
    actual = np.array([100.0, 200.0, 0.0])
    predicted = np.array([110.0, 180.0, 5.0])
    s = fc.score(actual, predicted, predicted - 15, predicted + 15)
    assert s.mae == pytest.approx((10 + 20 + 5) / 3)
    assert s.rmse == pytest.approx(np.sqrt((100 + 400 + 25) / 3))
    assert s.mape == pytest.approx((0.1 + 0.1) / 2)  # zero actuals are left out of MAPE
    assert s.coverage == pytest.approx(2 / 3) and s.mean_width == 30


def test_one_profile_end_to_end(profile):
    out = fc.run([profile])
    table = out["table"]
    assert set(table["period"]) == {"train", "calibration", "test"}
    out_of_sample = table[table["period"] != "train"]
    assert out_of_sample[list(fc.METHODS)].notna().all().all()
    assert (out_of_sample[list(fc.METHODS)] >= 0).all().all()
    results = fc.evaluate(table)
    for horizon in fc.HORIZONS:
        r = results[horizon]
        assert r["chosen_on_calibration"] in fc.METHODS
        assert all(0 <= m["test"]["coverage"] <= 1 for m in r["methods"].values())
