"""Unusual-spending detection: personal statistical baselines vs Isolation Forest and LOF.

A flag means "unusual compared with your own history", never "fraud".

Evaluation data is synthetic: per-person transaction streams with injected,
labelled anomalies (amount spikes and never-used categories) plus large but
legitimate purchases that a good method should *not* flag. Results show
which method finds the injected patterns; real anomalies will differ.

Every method scores a transaction using only earlier transactions.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

MIN_HISTORY = 8  # payments in a category before anything in it can be called unusual
Z_THRESHOLD = 3.0  # flag at |z| >= 3 on log amounts
_CATEGORIES = ("Dining", "Groceries", "Transport", "Shopping", "Utilities", "Entertainment", "Health")


# ------------------------------------------------------------ synthetic data


def simulate_stream(seed: int, days: int = 365, anomaly_rate: float = 0.01) -> pd.DataFrame:
    """One person's purchases: date, category, amount, label (1 = injected anomaly), kind."""
    rng = np.random.default_rng(seed)
    used = list(rng.choice(_CATEGORIES, size=int(rng.integers(4, 7)), replace=False))
    unused = [c for c in _CATEGORIES if c not in used]
    params = {c: (rng.uniform(4.5, 7.5), rng.uniform(0.25, 0.6), rng.uniform(0.1, 0.8)) for c in _CATEGORIES}
    rows = []
    for day in range(days):
        for category in used:
            log_mean, log_sd, per_day = params[category]
            for _ in range(rng.poisson(per_day)):
                amount, label, kind = rng.lognormal(log_mean, log_sd), 0, "normal"
                roll = rng.random()
                if roll < anomaly_rate:
                    amount, label, kind = amount * rng.uniform(5, 20), 1, "amount_spike"
                elif roll < anomaly_rate * 1.5:
                    amount, kind = amount * rng.uniform(2.0, 3.0), "large_but_normal"  # decoy: not labelled
                rows.append((day, category, amount, label, kind))
        if unused and rng.random() < anomaly_rate / 4:
            category = unused[int(rng.integers(len(unused)))]
            rows.append((day, category, rng.lognormal(params[category][0] + 1, 0.3), 1, "unusual_category"))
    frame = pd.DataFrame(rows, columns=["day", "category", "amount", "label", "kind"])
    frame["amount"] = frame["amount"].round(2)
    return frame


# ------------------------------------------------------- personal baselines


@dataclass(frozen=True, slots=True)
class Flag:
    score: float
    flagged: bool
    reason: str | None


def _history_stats(log_amounts: list[float], robust: bool) -> tuple[float, float]:
    values = np.asarray(log_amounts)
    if robust:
        centre = float(np.median(values))
        spread = 1.4826 * float(np.median(np.abs(values - centre)))  # MAD scaled to match a normal SD
    else:
        centre, spread = float(values.mean()), float(values.std(ddof=1))
    return centre, max(spread, 0.05)  # floor: a perfectly regular payment should not flag every cent of change


def personal_scores(stream: pd.DataFrame, *, robust: bool, threshold: float = Z_THRESHOLD) -> list[Flag]:
    """Score each payment against the same person's earlier payments in its category."""
    history: dict[str, list[float]] = {}
    total_payments = 0
    flags = []
    for row in stream.itertuples():
        past = history.setdefault(row.category, [])
        log_amount = float(np.log(row.amount))
        if not past and total_payments >= MIN_HISTORY * 3:
            flags.append(Flag(10.0, True, f"first payment ever in {row.category}"))
        elif len(past) < MIN_HISTORY:
            flags.append(Flag(0.0, False, None))  # not enough history to judge
        else:
            centre, spread = _history_stats(past, robust)
            z = (log_amount - centre) / spread
            typical = float(np.exp(centre))
            flagged = z >= threshold  # unusually *high*; unusually low spending is not a concern here
            reason = (
                f"{row.amount:,.0f} is {row.amount / typical:.1f}x your typical {row.category} payment "
                f"({typical:,.0f})" if flagged else None
            )
            flags.append(Flag(float(z), bool(flagged), reason))
        past.append(log_amount)
        total_payments += 1
    return flags


# ---------------------------------------------------------- learned models


def _features(stream: pd.DataFrame) -> np.ndarray:
    """Per payment, from earlier payments only: log amount, its gap from the
    category's running median, category frequency so far, and weekday."""
    out, history, seen = [], {}, 0
    for row in stream.itertuples():
        past = history.setdefault(row.category, [])
        log_amount = float(np.log(row.amount))
        median = float(np.median(past)) if past else log_amount
        out.append([log_amount, log_amount - median, len(past) / max(seen, 1), row.day % 7])
        past.append(log_amount)
        seen += 1
    return np.asarray(out)


def model_scores(stream: pd.DataFrame, method: str, *, train_days: int, contamination: float = 0.01) -> np.ndarray:
    """Fit on payments before ``train_days``; return a flag (1/0) for every payment.

    Payments in the training period get 0 (they are what the model learned from).
    """
    from sklearn.ensemble import IsolationForest
    from sklearn.neighbors import LocalOutlierFactor

    X = _features(stream)
    train = (stream["day"] < train_days).to_numpy()
    if method == "isolation_forest":
        model = IsolationForest(n_estimators=300, contamination=contamination, random_state=0).fit(X[train])
    elif method == "lof":
        model = LocalOutlierFactor(n_neighbors=35, contamination=contamination, novelty=True).fit(X[train])
    else:
        raise ValueError(method)
    flags = (model.predict(X) == -1).astype(int)
    flags[train] = 0
    return flags


# --------------------------------------------------------------- evaluation


METHODS = ("z_score", "robust_z_score", "isolation_forest", "lof")


def evaluate(stream_seeds, *, days: int = 365, train_days: int = 180) -> dict:
    """Precision, recall and false alarms per month on payments after ``train_days``."""
    totals = {m: {"tp": 0, "fp": 0, "fn": 0, "decoy_flags": 0, "decoys": 0} for m in METHODS}
    by_kind = {m: {} for m in METHODS}
    months = 0.0
    for seed in stream_seeds:
        stream = simulate_stream(seed, days)
        test = (stream["day"] >= train_days).to_numpy()
        months += (days - train_days) / 30.4
        labels = stream["label"].to_numpy()
        predictions = {
            "z_score": np.array([f.flagged for f in personal_scores(stream, robust=False)], dtype=int),
            "robust_z_score": np.array([f.flagged for f in personal_scores(stream, robust=True)], dtype=int),
            "isolation_forest": model_scores(stream, "isolation_forest", train_days=train_days),
            "lof": model_scores(stream, "lof", train_days=train_days),
        }
        for m, p in predictions.items():
            t = totals[m]
            t["tp"] += int(((p == 1) & (labels == 1) & test).sum())
            t["fp"] += int(((p == 1) & (labels == 0) & test).sum())
            t["fn"] += int(((p == 0) & (labels == 1) & test).sum())
            decoy = (stream["kind"] == "large_but_normal").to_numpy() & test
            t["decoys"] += int(decoy.sum())
            t["decoy_flags"] += int((p[decoy] == 1).sum())
            for kind in ("amount_spike", "unusual_category"):
                mask = (stream["kind"] == kind).to_numpy() & test
                found, count = by_kind[m].get(kind, (0, 0))
                by_kind[m][kind] = (found + int((p[mask] == 1).sum()), count + int(mask.sum()))
    results = {}
    for m, t in totals.items():
        precision = t["tp"] / (t["tp"] + t["fp"]) if t["tp"] + t["fp"] else 0.0
        recall = t["tp"] / (t["tp"] + t["fn"]) if t["tp"] + t["fn"] else 0.0
        results[m] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
            "false_alarms_per_month": round(t["fp"] / months, 3),
            "decoys_flagged": f"{t['decoy_flags']}/{t['decoys']}",
            "recall_by_kind": {k: f"{f}/{n}" for k, (f, n) in by_kind[m].items()},
            **t,
        }
    return results


def bootstrap_f1(per_stream: list[dict[str, int]], *, rounds: int = 2000, seed: int = 0) -> tuple[float, float]:
    """95% interval for F1, resampling whole streams (people) with replacement."""
    rng = np.random.default_rng(seed)
    counts = np.array([[s["tp"], s["fp"], s["fn"]] for s in per_stream])
    values = []
    for _ in range(rounds):
        tp, fp, fn = counts[rng.integers(0, len(counts), len(counts))].sum(axis=0)
        values.append(2 * tp / (2 * tp + fp + fn) if tp else 0.0)
    low, high = np.quantile(values, [0.025, 0.975])
    return round(float(low), 3), round(float(high), 3)


def evaluate_with_intervals(stream_seeds, *, days: int = 365, train_days: int = 180) -> dict:
    """``evaluate`` plus a bootstrap 95% interval for each method's F1."""
    results = evaluate(stream_seeds, days=days, train_days=train_days)
    per_stream = {m: [] for m in METHODS}
    for seed in stream_seeds:
        single = evaluate([seed], days=days, train_days=train_days)
        for m in METHODS:
            per_stream[m].append({k: single[m][k] for k in ("tp", "fp", "fn")})
    for m in METHODS:
        results[m]["f1_95ci"] = bootstrap_f1(per_stream[m])
    return results
