"""
Tests for HDBSCAN clustering algorithm
Based on the DBSCAN test code
"""
import numpy as np
import pytest
from scipy import sparse, stats
from scipy.spatial import distance

from sklearn.cluster import HDBSCAN
from sklearn.datasets import make_blobs
from sklearn.metrics import fowlkes_mallows_score
from sklearn.metrics.pairwise import _VALID_METRICS, euclidean_distances
from sklearn.neighbors import BallTree, KDTree
from sklearn.preprocessing import StandardScaler
from sklearn.utils import shuffle
from sklearn.utils._testing import assert_allclose, assert_array_equal
from sklearn.cluster._hdbscan.hdbscan import _OUTLIER_ENCODING

n_clusters_true = 3
X, y = make_blobs(n_samples=200, random_state=10)
X, y = shuffle(X, y, random_state=7)
X = StandardScaler().fit_transform(X)

ALGORITHMS = [
    "kdtree",
    "balltree",
    "brute",
    "auto",
]

OUTLIER_SET = {-1} | {out["label"] for _, out in _OUTLIER_ENCODING.items()}


@pytest.mark.parametrize("outlier_type", _OUTLIER_ENCODING)
def test_outlier_data(outlier_type):
    """
    Tests if np.inf and np.nan data are each treated as special outliers.
    """
    outlier = {
        "infinite": np.inf,
        "missing": np.nan,
    }[outlier_type]
    prob_check = {
        "infinite": lambda x, y: x == y,
        "missing": lambda x, y: np.isnan(x),
    }[outlier_type]
    label = _OUTLIER_ENCODING[outlier_type]["label"]
    prob = _OUTLIER_ENCODING[outlier_type]["prob"]

    X_outlier = X.copy()
    X_outlier[0] = [outlier, 1]
    X_outlier[5] = [outlier, outlier]
    model = HDBSCAN().fit(X_outlier)

    (missing_labels_idx,) = (model.labels_ == label).nonzero()
    assert_array_equal(missing_labels_idx, [0, 5])

    (missing_probs_idx,) = (prob_check(model.probabilities_, prob)).nonzero()
    assert_array_equal(missing_probs_idx, [0, 5])

    clean_indices = list(range(1, 5)) + list(range(6, 200))
    clean_model = HDBSCAN().fit(X_outlier[clean_indices])
    assert_array_equal(clean_model.labels_, model.labels_[clean_indices])


def test_hdbscan_distance_matrix():
    D = euclidean_distances(X)
    D_original = D.copy()
    labels = HDBSCAN(metric="precomputed", copy=True).fit_predict(D)

    assert_allclose(D, D_original)
    n_clusters = len(set(labels) - OUTLIER_SET)
    assert n_clusters == n_clusters_true

    # Check that clustering is arbitrarily good
    # This is a heuristic to guard against regression
    score = fowlkes_mallows_score(y, labels)
    assert score >= 0.98


def test_hdbscan_sparse_distance_matrix():
    D = distance.squareform(distance.pdist(X))
    D /= np.max(D)

    threshold = stats.scoreatpercentile(D.flatten(), 50)

    D[D >= threshold] = 0.0
    D = sparse.csr_matrix(D)
    D.eliminate_zeros()

    labels = HDBSCAN(metric="precomputed").fit_predict(D)
    n_clusters = len(set(labels) - OUTLIER_SET)
    assert n_clusters == n_clusters_true


def test_hdbscan_feature_vector():
    labels = HDBSCAN().fit_predict(X)
    n_clusters = len(set(labels) - OUTLIER_SET)
    assert n_clusters == n_clusters_true

    # Check that clustering is arbitrarily good
    # This is a heuristic to guard against regression
    score = fowlkes_mallows_score(y, labels)
    assert score >= 0.98


@pytest.mark.parametrize("algo", ALGORITHMS)
@pytest.mark.parametrize("metric", _VALID_METRICS)
def test_hdbscan_algorithms(algo, metric):
    labels = HDBSCAN(algorithm=algo).fit_predict(X)
    n_clusters = len(set(labels) - OUTLIER_SET)
    assert n_clusters == n_clusters_true

    # Validation for brute is handled by `pairwise_distances`
    if algo in ("brute", "auto"):
        return

    ALGOS_TREES = {
        "kdtree": KDTree,
        "balltree": BallTree,
    }
    metric_params = {
        "mahalanobis": {"V": np.eye(X.shape[1])},
        "seuclidean": {"V": np.ones(X.shape[1])},
        "minkowski": {"p": 2},
        "wminkowski": {"p": 2, "w": np.ones(X.shape[1])},
    }.get(metric, None)

    hdb = HDBSCAN(
        algorithm=algo,
        metric=metric,
        metric_params=metric_params,
    )

    if metric not in ALGOS_TREES[algo].valid_metrics:
        with pytest.raises(ValueError):
            hdb.fit(X)
    elif metric == "wminkowski":
        with pytest.warns(FutureWarning):
            hdb.fit(X)
    else:
        hdb.fit(X)


def test_hdbscan_dbscan_clustering():
    clusterer = HDBSCAN().fit(X)
    labels = clusterer.dbscan_clustering(0.3)
    n_clusters = len(set(labels) - OUTLIER_SET)
    assert n_clusters == n_clusters_true


def test_hdbscan_high_dimensional():
    H, y = make_blobs(n_samples=50, random_state=0, n_features=64)
    H = StandardScaler().fit_transform(H)
    labels = HDBSCAN(
        algorithm="auto",
        metric="seuclidean",
        metric_params={"V": np.ones(H.shape[1])},
    ).fit_predict(H)
    n_clusters = len(set(labels) - OUTLIER_SET)
    assert n_clusters == n_clusters_true


def test_hdbscan_best_balltree_metric():
    labels = HDBSCAN(
        metric="seuclidean", metric_params={"V": np.ones(X.shape[1])}
    ).fit_predict(X)
    n_clusters = len(set(labels) - OUTLIER_SET)
    assert n_clusters == n_clusters_true


def test_hdbscan_no_clusters():
    labels = HDBSCAN(min_cluster_size=len(X) - 1).fit_predict(X)
    n_clusters = len(set(labels) - OUTLIER_SET)
    assert n_clusters == 0


def test_hdbscan_min_cluster_size():
    """
    Test that the smallest non-noise cluster has at least `min_cluster_size`
    many points
    """
    for min_cluster_size in range(2, len(X), 1):
        labels = HDBSCAN(min_cluster_size=min_cluster_size).fit_predict(X)
        true_labels = [label for label in labels if label != -1]
        if len(true_labels) != 0:
            assert np.min(np.bincount(true_labels)) >= min_cluster_size


def test_hdbscan_callable_metric():
    metric = distance.euclidean
    labels = HDBSCAN(metric=metric).fit_predict(X)
    n_clusters = len(set(labels) - OUTLIER_SET)
    assert n_clusters == n_clusters_true


@pytest.mark.parametrize("tree", ["kd", "ball"])
def test_hdbscan_precomputed_non_brute(tree):
    hdb = HDBSCAN(metric="precomputed", algorithm=f"prims_{tree}tree")
    with pytest.raises(ValueError):
        hdb.fit(X)


def test_hdbscan_sparse():
    sparse_X = sparse.csr_matrix(X)

    labels = HDBSCAN().fit(sparse_X).labels_
    n_clusters = len(set(labels) - OUTLIER_SET)
    assert n_clusters == 3

    sparse_X_nan = sparse_X.copy()
    sparse_X_nan[0, 0] = np.nan
    labels = HDBSCAN().fit(sparse_X_nan).labels_
    n_clusters = len(set(labels) - OUTLIER_SET)
    assert n_clusters == 3

    msg = "Sparse data matrices only support algorithm `brute`."
    with pytest.raises(ValueError, match=msg):
        HDBSCAN(metric="euclidean", algorithm="balltree").fit(sparse_X)


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_hdbscan_centers(algorithm):
    centers = [(0.0, 0.0), (3.0, 3.0)]
    H, _ = make_blobs(n_samples=1000, random_state=0, centers=centers, cluster_std=0.5)
    hdb = HDBSCAN(store_centers="both").fit(H)

    for center, centroid, medoid in zip(centers, hdb.centroids_, hdb.medoids_):
        assert_allclose(center, centroid, rtol=1, atol=0.05)
        assert_allclose(center, medoid, rtol=1, atol=0.05)

    # Ensure that nothing is done for noise
    hdb = HDBSCAN(
        algorithm=algorithm, store_centers="both", min_cluster_size=X.shape[0]
    ).fit(X)
    assert hdb.centroids_.shape[0] == 0
    assert hdb.medoids_.shape[0] == 0


def test_hdbscan_allow_single_cluster_with_epsilon():
    rng = np.random.RandomState(0)
    no_structure = rng.rand(150, 2)
    # without epsilon we should see many noise points as children of root.
    labels = HDBSCAN(
        min_cluster_size=5,
        cluster_selection_epsilon=0.0,
        cluster_selection_method="eom",
        allow_single_cluster=True,
    ).fit_predict(no_structure)
    unique_labels, counts = np.unique(labels, return_counts=True)
    assert len(unique_labels) == 2

    # Arbitrary heuristic. Would prefer something more precise.
    assert counts[unique_labels == -1] > 30

    # for this random seed an epsilon of 0.18 will produce exactly 2 noise
    # points at that cut in single linkage.
    labels = HDBSCAN(
        min_cluster_size=5,
        cluster_selection_epsilon=0.18,
        cluster_selection_method="eom",
        allow_single_cluster=True,
        algorithm="kdtree",
    ).fit_predict(no_structure)
    unique_labels, counts = np.unique(labels, return_counts=True)
    assert len(unique_labels) == 2
    assert counts[unique_labels == -1] == 2


def test_hdbscan_better_than_dbscan():
    """
    Validate that HDBSCAN can properly cluster this difficult synthetic
    dataset. Note that DBSCAN fails on this (see HDBSCAN plotting
    example)
    """
    centers = [[-0.85, -0.85], [-0.85, 0.85], [3, 3], [3, -3]]
    X, _ = make_blobs(
        n_samples=750,
        centers=centers,
        cluster_std=[0.2, 0.35, 1.35, 1.35],
        random_state=0,
    )
    hdb = HDBSCAN().fit(X)
    n_clusters = len(set(hdb.labels_)) - int(-1 in hdb.labels_)
    assert n_clusters == 4


@pytest.mark.parametrize(
    "kwargs, X",
    [
        ({"metric": "precomputed"}, np.array([[1, np.inf], [np.inf, 1]])),
        ({"metric": "precomputed"}, [[1, 2], [2, 1]]),
        ({}, [[1, 2], [3, 4]]),
    ],
)
def test_hdbscan_usable_inputs(X, kwargs):
    HDBSCAN(min_samples=1, **kwargs).fit(X)


def test_hdbscan_sparse_distances_too_few_nonzero():
    X = sparse.csr_matrix(np.zeros((10, 10)))

    msg = "There exists points with fewer than"
    with pytest.raises(ValueError, match=msg):
        HDBSCAN(metric="precomputed").fit(X)


def test_hdbscan_tree_invalid_metric():
    metric_callable = lambda x: x
    msg = (
        ".* is not a valid metric for a .*-based algorithm\\. Please select a different"
        " metric\\."
    )

    # Callables are not supported for either
    with pytest.raises(ValueError, match=msg):
        HDBSCAN(algorithm="kdtree", metric=metric_callable).fit(X)
    with pytest.raises(ValueError, match=msg):
        HDBSCAN(algorithm="balltree", metric=metric_callable).fit(X)

    # The set of valid metrics for KDTree at the time of writing this test is a
    # strict subset of those supported in BallTree
    metrics_not_kd = list(set(BallTree.valid_metrics) - set(KDTree.valid_metrics))
    if len(metrics_not_kd) > 0:
        with pytest.raises(ValueError, match=msg):
            HDBSCAN(algorithm="kdtree", metric=metrics_not_kd[0]).fit(X)


def test_hdbscan_too_many_min_samples():
    hdb = HDBSCAN(min_samples=len(X) + 1)
    msg = r"min_samples (.*) must be at most"
    with pytest.raises(ValueError, match=msg):
        hdb.fit(X)


def test_hdbscan_precomputed_dense_nan():
    X_nan = X.copy()
    X_nan[0, 0] = np.nan
    msg = "np.nan values found in precomputed-dense"
    hdb = HDBSCAN(metric="precomputed")
    with pytest.raises(ValueError, match=msg):
        hdb.fit(X_nan)
