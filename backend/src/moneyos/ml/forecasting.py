"""Spending forecasts: baselines vs time-series and feature-based models.

Protocol (fixed before running):

* Target: total spending in the H days after a forecast origin (the last
  observed day), H in {7, 30}. Origins every 7 days.
* Chronological sets with purging: *train* origins have their whole target
  window before day ``CAL_START``; *calibration* origins start at or after
  ``CAL_START`` and end before ``TEST_START``; *test* origins start at or
  after ``TEST_START``. No target window crosses a boundary.
* Every forecast uses only data up to and including its origin.
* Methods are compared and **chosen on calibration**, then reported on test.
* 80% intervals: forecast + the 10th/90th percentiles of that method's
  calibration errors (split-conformal style); test coverage shows whether
  the intervals are honest.
"""

from __future__ import annotations

import time
import warnings
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

HORIZONS = (7, 30)
FIRST_ORIGIN, ORIGIN_STEP = 120, 7
CAL_START, TEST_START = 450, 570
INTERVAL = (0.10, 0.90)


def origins(days: int, horizon: int) -> list[int]:
    return list(range(FIRST_ORIGIN, days - horizon, ORIGIN_STEP))


def period_of(origin: int, horizon: int) -> str | None:
    if origin + horizon < CAL_START:
        return "train"
    if origin >= CAL_START and origin + horizon < TEST_START:
        return "calibration"
    if origin >= TEST_START:
        return "test"
    return None  # purged: the target window would straddle a boundary


def target(series: np.ndarray, origin: int, horizon: int) -> float:
    return float(series[origin + 1: origin + 1 + horizon].sum())


# ---------------------------------------------------------------- baselines


def historical_mean(history: np.ndarray, horizon: int, _dates=None) -> float:
    return float(history.mean() * horizon)


def last_period(history: np.ndarray, horizon: int, _dates=None) -> float:
    return float(history[-horizon:].sum())


def moving_average_90(history: np.ndarray, horizon: int, _dates=None) -> float:
    return float(history[-90:].mean() * horizon)


def same_window_last_month(history: np.ndarray, horizon: int, _dates=None) -> float:
    # The H days that started 30 days before the target window.
    start = len(history) - 30
    return float(history[start: start + horizon].sum()) if horizon <= 30 else last_period(history, horizon)


BASELINES: dict[str, Callable] = {
    "historical_mean": historical_mean,
    "last_period": last_period,
    "moving_average_90": moving_average_90,
    "same_window_last_month": same_window_last_month,
}


# ------------------------------------------------------- time-series models


class TimeSeriesModels:
    """Exponential smoothing (refit at each origin) and SARIMA (parameters
    estimated once on training data, then rolled forward without refitting)."""

    def __init__(self, series: np.ndarray, dates: pd.DatetimeIndex):
        self.series, self.dates = series, dates
        self.convergence_warnings = 0
        self._sarima = None

    def exponential_smoothing(self, origin: int, horizon: int) -> float:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing

        history = pd.Series(self.series[: origin + 1], index=self.dates[: origin + 1])
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            fit = ExponentialSmoothing(history, trend="add", damped_trend=True, seasonal="add",
                                       seasonal_periods=7, initialization_method="estimated").fit()
        self.convergence_warnings += sum("converge" in str(w.message).lower() for w in caught)
        return float(max(fit.forecast(horizon).sum(), 0.0))

    def sarima(self, origin: int, horizon: int) -> float:
        from statsmodels.tsa.statespace.sarimax import SARIMAX

        if self._sarima is None:  # estimate on the training period only
            train_end = CAL_START - 30
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                self._sarima = SARIMAX(self.series[:train_end], order=(1, 0, 1), seasonal_order=(1, 0, 1, 7),
                                       trend="c").fit(disp=False)
            self.convergence_warnings += sum("converge" in str(w.message).lower() for w in caught)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            rolled = self._sarima.apply(self.series[: origin + 1])  # same parameters, new data
            return float(max(rolled.forecast(horizon).sum(), 0.0))


# ---------------------------------------------------- feature-based models

FEATURES = (
    "mean_7", "mean_30", "mean_90", "mean_all", "last_h", "std_30", "same_window_last_month",
    "weekend_share", "festive_share", "month_end_share",
)


def features(history: np.ndarray, target_dates: pd.DatetimeIndex, horizon: int) -> dict[str, float]:
    """Transactions-only features from history, plus calendar facts about the
    target window (known in advance). Spending features are relative to the
    90-day mean so one model can serve people who spend at different levels."""
    level = max(history[-90:].mean(), 1.0)
    return {
        "mean_7": history[-7:].mean() / level,
        "mean_30": history[-30:].mean() / level,
        "mean_90": 1.0,
        "mean_all": history.mean() / level,
        "last_h": history[-horizon:].mean() / level,
        "std_30": history[-30:].std() / level,
        "same_window_last_month": same_window_last_month(history, horizon) / horizon / level,
        "weekend_share": float((target_dates.day_of_week >= 5).mean()),
        "festive_share": float(target_dates.month.isin([10, 11, 12]).mean()),
        "month_end_share": float((target_dates.day >= 25).mean()),
        "_level": level,
    }


def make_regressor(name: str, seed: int = 0):
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.linear_model import LinearRegression

    if name == "linear_regression":
        return LinearRegression()
    if name == "random_forest":
        return RandomForestRegressor(n_estimators=300, min_samples_leaf=5, n_jobs=-1, random_state=seed)
    if name == "xgboost":
        from xgboost import XGBRegressor

        return XGBRegressor(n_estimators=300, max_depth=4, learning_rate=0.05, subsample=0.8, random_state=seed,
                            n_jobs=-1, verbosity=0)
    raise ValueError(name)


REGRESSORS = ("linear_regression", "random_forest", "xgboost")


# ---------------------------------------------------------------- metrics


@dataclass
class Scores:
    mae: float
    rmse: float
    mape: float
    coverage: float  # share of actuals inside the 80% interval
    mean_width: float
    n: int


def score(actual: np.ndarray, predicted: np.ndarray, low: np.ndarray, high: np.ndarray) -> Scores:
    errors = predicted - actual
    nonzero = actual > 0
    return Scores(
        mae=float(np.abs(errors).mean()),
        rmse=float(np.sqrt((errors**2).mean())),
        mape=float(np.abs(errors[nonzero] / actual[nonzero]).mean()) if nonzero.any() else float("nan"),
        coverage=float(((actual >= low) & (actual <= high)).mean()),
        mean_width=float((high - low).mean()),
        n=int(len(actual)),
    )


# ------------------------------------------------------------- experiment


def run(profiles: list[pd.DataFrame], *, seed: int = 0) -> dict:
    """Forecast every origin of every profile with every method; return per-row predictions."""
    rows = []
    started = time.perf_counter()
    convergence = 0
    for pid, frame in enumerate(profiles):
        series, dates = frame["total"].to_numpy(), frame.index
        ts = TimeSeriesModels(series, dates)
        for horizon in HORIZONS:
            for o in origins(len(series), horizon):
                period = period_of(o, horizon)
                if period is None:
                    continue
                history = series[: o + 1]
                target_dates = dates[o + 1: o + 1 + horizon]
                row = {"profile": pid, "horizon": horizon, "origin": o, "period": period,
                       "actual": target(series, o, horizon), **features(history, target_dates, horizon)}
                for name, fn in BASELINES.items():
                    row[name] = fn(history, horizon)
                if period != "train":  # time-series models are only needed out of sample
                    row["exponential_smoothing"] = ts.exponential_smoothing(o, horizon)
                    row["sarima"] = ts.sarima(o, horizon)
                rows.append(row)
        convergence += ts.convergence_warnings
    table = pd.DataFrame(rows)

    # Feature-based models: one global model per horizon, trained on train origins only.
    for horizon in HORIZONS:
        h = table["horizon"] == horizon
        train = h & (table["period"] == "train")
        X_train = table.loc[train, list(FEATURES)].to_numpy()
        y_train = (table.loc[train, "actual"] / (table.loc[train, "_level"] * horizon)).to_numpy()
        for name in REGRESSORS:
            model = make_regressor(name, seed).fit(X_train, y_train)
            table.loc[h, name] = model.predict(table.loc[h, list(FEATURES)].to_numpy()) * table.loc[h, "_level"] * horizon
    table[list(REGRESSORS)] = table[list(REGRESSORS)].clip(lower=0)
    return {"table": table, "seconds": time.perf_counter() - started, "convergence_warnings": convergence}


METHODS = (*BASELINES, "exponential_smoothing", "sarima", *REGRESSORS)


def evaluate(table: pd.DataFrame) -> dict:
    """Scores per horizon and method on calibration and test, with intervals from calibration errors."""
    results = {}
    for horizon in HORIZONS:
        h = table[table["horizon"] == horizon]
        cal, test = h[h["period"] == "calibration"], h[h["period"] == "test"]
        per_method = {}
        for method in METHODS:
            errors = (cal["actual"] - cal[method]).to_numpy()
            q_low, q_high = np.quantile(errors, INTERVAL)
            per_method[method] = {
                "calibration": score(cal["actual"].to_numpy(), cal[method].to_numpy(),
                                     cal[method].to_numpy() + q_low, cal[method].to_numpy() + q_high).__dict__,
                "test": score(test["actual"].to_numpy(), test[method].to_numpy(),
                              test[method].to_numpy() + q_low, test[method].to_numpy() + q_high).__dict__,
            }
        best_baseline = min(BASELINES, key=lambda m: per_method[m]["calibration"]["mae"])
        chosen = min(METHODS, key=lambda m: per_method[m]["calibration"]["mae"])
        results[horizon] = {"methods": per_method, "best_baseline_on_calibration": best_baseline,
                            "chosen_on_calibration": chosen}
    return results
