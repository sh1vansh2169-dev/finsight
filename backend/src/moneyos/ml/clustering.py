"""Spending-behaviour clustering: a research check, not a product feature.

FinSight has one user, so there is no population to cluster. This asks two
questions on simulated people:

1. When people really do come in a few spending types (archetypes), can
   K-Means / hierarchical clustering recover them (adjusted Rand index)?
2. When people vary smoothly with no types at all, does clustering still
   produce groups, and does the silhouette score warn us they are not real?

Features follow the FinSight spec: category shares, payments per month,
average payment, savings rate, recurring-cost share.
"""

from __future__ import annotations

import numpy as np

FEATURES = ("share_food", "share_shopping", "share_travel", "share_bills", "payments_per_month",
            "log_average_payment", "savings_rate", "recurring_share")

# Archetypes: mean feature vectors for distinct spending types.
_ARCHETYPES = {
    "frugal_saver": [0.30, 0.10, 0.05, 0.55, 35, 5.2, 0.40, 0.55],
    "foodie": [0.55, 0.15, 0.05, 0.25, 90, 5.6, 0.15, 0.25],
    "shopper": [0.20, 0.50, 0.05, 0.25, 70, 6.6, 0.05, 0.25],
    "traveller": [0.20, 0.10, 0.45, 0.25, 40, 7.4, 0.20, 0.25],
}
_SPREAD = np.array([0.05, 0.05, 0.04, 0.05, 10, 0.25, 0.06, 0.06])


def archetype_population(seed: int, per_type: int = 50) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    X, y = [], []
    for label, (name, centre) in enumerate(_ARCHETYPES.items()):
        X.append(rng.normal(centre, _SPREAD, size=(per_type, len(FEATURES))))
        y += [label] * per_type
    return np.vstack(X), np.asarray(y)


def continuous_population(seed: int, size: int = 200) -> np.ndarray:
    """No types: every feature varies smoothly and independently."""
    rng = np.random.default_rng(seed)
    lows = np.array([0.15, 0.05, 0.0, 0.2, 25, 5.0, 0.0, 0.2])
    highs = np.array([0.55, 0.5, 0.45, 0.6, 100, 7.5, 0.45, 0.6])
    return rng.uniform(lows, highs, size=(size, len(FEATURES)))


def cluster(X: np.ndarray, method: str, k: int, seed: int = 0) -> np.ndarray:
    from sklearn.cluster import AgglomerativeClustering, KMeans
    from sklearn.preprocessing import StandardScaler

    Z = StandardScaler().fit_transform(X)
    if method == "kmeans":
        return KMeans(n_clusters=k, n_init=10, random_state=seed).fit_predict(Z)
    if method == "hierarchical":
        return AgglomerativeClustering(n_clusters=k, linkage="ward").fit_predict(Z)
    raise ValueError(method)


def silhouette(X: np.ndarray, labels: np.ndarray) -> float:
    from sklearn.metrics import silhouette_score
    from sklearn.preprocessing import StandardScaler

    return float(silhouette_score(StandardScaler().fit_transform(X), labels))


def evaluate(seeds=(1, 2, 3, 4, 5), ks=(2, 3, 4, 5, 6)) -> dict:
    from sklearn.metrics import adjusted_rand_score

    out = {"archetypes": {}, "continuous": {}}
    for method in ("kmeans", "hierarchical"):
        recovery, best_k, sil_types, sil_smooth = [], [], [], []
        for seed in seeds:
            X, truth = archetype_population(seed)
            recovery.append(adjusted_rand_score(truth, cluster(X, method, len(_ARCHETYPES), seed)))
            sils = {k: silhouette(X, cluster(X, method, k, seed)) for k in ks}
            best_k.append(max(sils, key=sils.get))
            sil_types.append(max(sils.values()))
            smooth = continuous_population(seed)
            sil_smooth.append(max(silhouette(smooth, cluster(smooth, method, k, seed)) for k in ks))
        out["archetypes"][method] = {
            "adjusted_rand_index_mean": round(float(np.mean(recovery)), 3),
            "adjusted_rand_index_min": round(float(np.min(recovery)), 3),
            "k_chosen_by_silhouette": best_k,
            "best_silhouette_mean": round(float(np.mean(sil_types)), 3),
        }
        out["continuous"][method] = {"best_silhouette_mean": round(float(np.mean(sil_smooth)), 3)}
    return out
