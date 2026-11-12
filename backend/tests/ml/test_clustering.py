import numpy as np

from moneyos.ml import clustering


def test_real_types_are_recovered_and_smooth_variation_scores_low():
    X, truth = clustering.archetype_population(1)
    from sklearn.metrics import adjusted_rand_score

    for method in ("kmeans", "hierarchical"):
        labels = clustering.cluster(X, method, 4)
        assert adjusted_rand_score(truth, labels) > 0.9
        assert clustering.silhouette(X, labels) > 0.4
    smooth = clustering.continuous_population(1)
    labels = clustering.cluster(smooth, "kmeans", 4)
    assert len(set(labels)) == 4  # clustering still "finds" groups...
    assert clustering.silhouette(smooth, labels) < 0.25  # ...but the silhouette says they are not real


def test_populations_are_deterministic():
    a, _ = clustering.archetype_population(2)
    b, _ = clustering.archetype_population(2)
    assert np.array_equal(a, b)
    assert clustering.continuous_population(2).shape == (200, len(clustering.FEATURES))
