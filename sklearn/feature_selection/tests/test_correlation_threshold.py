import pytest
import numpy as np
from scipy.sparse import csr_matrix, csc_matrix

from sklearn.feature_selection import CorrelationThreshold
from sklearn.datasets import load_boston
from sklearn.datasets import load_iris
from sklearn.datasets import load_diabetes
from sklearn.datasets import load_digits
from sklearn.datasets import load_wine
from sklearn.datasets import load_breast_cancer
from sklearn.utils.testing import assert_allclose_dense_sparse


@pytest.mark.parametrize("toarray", [np.asarray, csr_matrix, csc_matrix])
def test_correlated_features_are_removed(toarray):
    rng = np.random.RandomState(0)
    X_shape = (1000, 3)

    X_uncorr = rng.normal(size=X_shape)
    X = np.c_[X_uncorr,
              X_uncorr + 2 * rng.normal(scale=0.05, size=X_shape),
              X_uncorr + 3 * rng.normal(scale=0.05, size=X_shape)]
    X = toarray(X)

    cor_thres = CorrelationThreshold()
    X_trans = cor_thres.fit_transform(X)

    assert X_trans.shape[1] == X_shape[1]


@pytest.mark.parametrize("toarray", [np.asarray, csr_matrix, csc_matrix])
def test_uncorrelated_features_are_kept(toarray):
    rng = np.random.RandomState(0)
    X_shape = (1000, 3)

    X_uncorr = toarray(rng.normal(size=X_shape))

    cor_thres = CorrelationThreshold()
    X_trans = cor_thres.fit_transform(X_uncorr)

    assert X_trans.shape[1] == X_shape[1]


@pytest.mark.parametrize("toarray", [np.asarray, csr_matrix, csc_matrix])
def test_all_correlated_features_are_removed(toarray):
    X = np.linspace(0, 10, 100)
    X = toarray(np.c_[X, 2 * X, 0.5 * X])

    cor_thres = CorrelationThreshold()
    X_trans = cor_thres.fit_transform(X)

    assert X_trans.shape[1] == 1


@pytest.mark.parametrize("load_dataset", [
    load_boston, load_iris, load_diabetes, load_digits, load_wine,
    load_breast_cancer
])
@pytest.mark.parametrize("toarray", [np.asarray, csr_matrix, csc_matrix])
def test_increasing_threshold_removes_features_consistently(load_dataset,
                                                            toarray):
    X, _ = load_dataset(return_X_y=True)
    X = toarray(X)

    cor_thresholds = []
    for threshold in np.linspace(0, 1, 20):
        cor_thres = CorrelationThreshold(threshold=threshold)
        X_trans = cor_thres.fit_transform(X)
        assert_allclose_dense_sparse(X_trans, X[:, cor_thres.support_mask_])

        cor_thresholds.append(cor_thres)

    # lower threshold produces a mask that is a subset of a higher threshold
    for lower_cor_thres, higher_cor_thres in zip(cor_thresholds,
                                                 cor_thresholds[1:]):
        assert np.all(lower_cor_thres.support_mask_ <=
                      higher_cor_thres.support_mask_)


@pytest.mark.parametrize("toarray", [np.asarray, csr_matrix, csc_matrix])
def test_threshold_one_keeps_all_features(toarray):
    X = np.linspace(0, 10, 100)
    X = toarray(np.c_[X, 2 * X, 0.5 * X])

    cor_thres = CorrelationThreshold(threshold=1.0)
    X_trans = cor_thres.fit_transform(X)

    assert X_trans.shape[1] == 3


@pytest.mark.parametrize("toarray", [np.asarray, csr_matrix, csc_matrix])
def test_threshold_zero_keeps_one_feature(toarray):
    X = np.linspace(0, 10, 100)
    X = toarray(np.c_[X, 2 * X, 0.5 * X])

    cor_thres = CorrelationThreshold(threshold=0.0)
    X_trans = cor_thres.fit_transform(X)

    assert X_trans.shape[1] == 1


@pytest.mark.parametrize("toarray", [np.asarray, csr_matrix, csc_matrix])
def test_constant_features(toarray):
    X = np.array([[0, 0, 0], [1, 1, 1], [1, 2, 3], [2, 3, 4]]).T
    X = toarray(X)

    cor_thres = CorrelationThreshold()
    X_trans = cor_thres.fit_transform(X)
    print(X_trans)
    assert X_trans.shape == (3, 1)


@pytest.mark.parametrize("threshold", [-1, 2])
def test_threshold_out_of_bounds(threshold):
    msg = r"threshold must be in \[0.0, 1.0\], got {}".format(threshold)
    with pytest.raises(ValueError, match=msg):
        CorrelationThreshold(threshold=threshold).fit([[0, 1]])
