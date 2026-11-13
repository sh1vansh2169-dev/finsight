"""Experiment E5 (research Model B): do recorded upcoming bills improve forecasts?

**Synthetic.** Reuses E2's simulated people (``spending_sim``) and protocol
(``forecasting``), but re-simulates the commitment payments so that the
user's *record* of their bills can differ from what is actually paid:

* ``ideal``: every bill recorded, paid on time, as recorded (upper bound).
* ``realistic``: some bills never recorded, payments late or missed (then paid
  together with the next one), rent rising without the record being updated,
  subscriptions cancelled while still listed.

Model A forecasts total spending from history alone (E2's baselines).
Model B adds the recorded bills due in the target window to a baseline
forecast of everything else. The plan and success criterion were fixed
before running; see ML_EXPERIMENTS.md, E5.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from moneyos.ml import forecasting as fc
from moneyos.ml.spending_sim import Profile

CONDITIONS = ("ideal", "realistic")


@dataclass(frozen=True, slots=True)
class Realism:
    record_probability: float = 0.8
    late_probability: float = 0.3
    late_days: tuple[int, int] = (1, 6)
    miss_probability: float = 0.04
    rent_rise: tuple[float, float] = (0.05, 0.10)
    cancel_probability: float = 0.3


IDEAL = Realism(record_probability=1.0, late_probability=0.0, miss_probability=0.0, rent_rise=(0.0, 0.0),
                cancel_probability=0.0)
REALISTIC = Realism()


def _bills(profile: Profile) -> list[tuple[str, int, float, bool]]:
    """(name, day of month, recorded amount, amount varies) for each commitment."""
    bills = [("utility", 10, profile.utility, True)]
    if profile.rent:
        bills.insert(0, ("rent", profile.rent_day, profile.rent, False))
    bills += [(f"subscription {i + 1}", day, amount, False) for i, (day, amount) in enumerate(profile.subscriptions)]
    return bills


def simulate_bills(profile: Profile, index: pd.DatetimeIndex, realism: Realism, seed: int) -> pd.DataFrame:
    """Daily columns: ``paid_recorded`` and ``paid_unrecorded`` (what left the account for
    bills the user did / did not record) and ``expected`` (what the record projects)."""
    rng = np.random.default_rng(seed)
    days = len(index)
    position = {d.date(): i for i, d in enumerate(index)}
    paid_recorded, paid_unrecorded, expected = np.zeros(days), np.zeros(days), np.zeros(days)
    second_year = [i for i, d in enumerate(index) if d.day == 1 and i >= 365]

    for name, day, amount, varies in _bills(profile):
        recorded = rng.random() < realism.record_probability
        rise_from = rng.choice(second_year) if name == "rent" and realism.rent_rise[1] > 0 else days
        rise = rng.uniform(*realism.rent_rise) if realism.rent_rise[1] > 0 else 0.0
        cancelled_from = (int(rng.integers(90, days)) if name.startswith("subscription")
                          and rng.random() < realism.cancel_probability else days)
        carried = 0.0
        for month_start in pd.date_range(index[0], index[-1], freq="MS"):
            y, m = month_start.year, month_start.month
            due = position.get(date(y, m, min(day, calendar.monthrange(y, m)[1])))
            if due is None:
                continue
            if recorded:
                expected[due] += amount  # the record keeps projecting the original bill
            if due >= cancelled_from:
                continue
            owed = amount * (1 + rise if due >= rise_from else 1.0)
            if varies:
                owed *= rng.uniform(0.8, 1.25)
            if rng.random() < realism.miss_probability:
                carried += owed  # paid together with the next one
                continue
            paid_day = due + (int(rng.integers(realism.late_days[0], realism.late_days[1] + 1))
                              if rng.random() < realism.late_probability else 0)
            if paid_day < days:
                (paid_recorded if recorded else paid_unrecorded)[paid_day] += owed + carried
            carried = 0.0
    return pd.DataFrame({"paid_recorded": paid_recorded, "paid_unrecorded": paid_unrecorded,
                         "expected": expected}, index=index).round(2)


def build(profile: Profile, frame: pd.DataFrame, condition: str) -> pd.DataFrame:
    """E2's everyday and one-off spending plus bills simulated for ``condition``."""
    realism = IDEAL if condition == "ideal" else REALISTIC
    bills = simulate_bills(profile, frame.index, realism, seed=profile.seed + 20_000)
    out = bills.assign(everyday=frame["everyday"], one_off=frame["one_off"])
    out["total"] = out["paid_recorded"] + out["paid_unrecorded"] + out["everyday"] + out["one_off"]
    out["rest"] = out["total"] - out["paid_recorded"]  # what Model B forecasts with a baseline
    return out


def model_b(rest_history: np.ndarray, expected: np.ndarray, origin: int, horizon: int, baseline) -> float:
    """Recorded bills due after the origin, plus a baseline forecast of everything else."""
    return float(expected[origin + 1: origin + 1 + horizon].sum() + baseline(rest_history, horizon))


A_METHODS = {f"A {name}": name for name in fc.BASELINES}
B_METHODS = {f"B {name}": name for name in fc.BASELINES}


def run(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """One row per (profile, horizon, origin) with every method's forecast."""
    rows = []
    for pid, frame in enumerate(frames):
        total, rest, expected = (frame[c].to_numpy() for c in ("total", "rest", "expected"))
        for horizon in fc.HORIZONS:
            for o in fc.origins(len(total), horizon):
                period = fc.period_of(o, horizon)
                if period in (None, "train"):  # nothing is trained; only calibration and test are needed
                    continue
                row = {"profile": pid, "horizon": horizon, "origin": o, "period": period,
                       "actual": fc.target(total, o, horizon)}
                for label, name in A_METHODS.items():
                    row[label] = fc.BASELINES[name](total[: o + 1], horizon)
                for label, name in B_METHODS.items():
                    row[label] = model_b(rest[: o + 1], expected, o, horizon, fc.BASELINES[name])
                rows.append(row)
    return pd.DataFrame(rows)


def _chosen(cal: pd.DataFrame, methods) -> str:
    return min(methods, key=lambda m: float((cal[m] - cal["actual"]).abs().mean()))


def evaluate(table: pd.DataFrame, *, resamples: int = 2000, seed: int = 0) -> dict:
    """Per horizon: each family's method chosen on calibration, its test scores, and the
    bootstrap (over people) interval of the test MAE difference B - A."""
    rng = np.random.default_rng(seed)
    results = {}
    for horizon in fc.HORIZONS:
        h = table[table["horizon"] == horizon]
        cal, test = h[h["period"] == "calibration"], h[h["period"] == "test"]
        a, b = _chosen(cal, A_METHODS), _chosen(cal, B_METHODS)
        scores = {}
        for method in (*A_METHODS, *B_METHODS):
            q_low, q_high = np.quantile((cal["actual"] - cal[method]).to_numpy(), fc.INTERVAL)
            p = test[method].to_numpy()
            scores[method] = fc.score(test["actual"].to_numpy(), p, p + q_low, p + q_high).__dict__
        # Paired by origin; people are resampled because origins of one person are not independent.
        errors = test.assign(err_a=(test[a] - test["actual"]).abs(), err_b=(test[b] - test["actual"]).abs())
        per_person = errors.groupby("profile")[["err_a", "err_b"]].agg(["sum", "count"])
        people = per_person.index.to_numpy()
        diffs = []
        for _ in range(resamples):
            pick = per_person.loc[rng.choice(people, size=len(people), replace=True)]
            n = pick[("err_a", "count")].sum()
            diffs.append((pick[("err_b", "sum")].sum() - pick[("err_a", "sum")].sum()) / n)
        mae_a, mae_b = scores[a]["mae"], scores[b]["mae"]
        low, high = np.quantile(diffs, [0.025, 0.975])
        results[horizon] = {
            "chosen_a": a, "chosen_b": b, "mae_a": mae_a, "mae_b": mae_b,
            "relative_change": (mae_b - mae_a) / mae_a,
            "difference_ci95": [float(low), float(high)],
            "meets_criterion": bool((mae_b - mae_a) / mae_a <= -0.05 and high < 0),
            "methods": scores,
        }
    return results
