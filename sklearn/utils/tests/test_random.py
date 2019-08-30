import math

import numpy as np
import scipy.sparse as sp
import scipy.stats
from numpy.testing import assert_array_almost_equal
import pytest

from sklearn.utils.fixes import comb
from sklearn.utils.random import random_choice_csc, sample_without_replacement
from sklearn.utils.random import loguniform
from sklearn.utils._random import _our_rand_r_py
from sklearn.utils.testing import assert_raises


###############################################################################
# test custom sampling without replacement algorithm
###############################################################################
def test_invalid_sample_without_replacement_algorithm():
    assert_raises(ValueError, sample_without_replacement, 5, 4, "unknown")


def test_sample_without_replacement_algorithms():
    methods = ("auto", "tracking_selection", "reservoir_sampling", "pool")

    for m in methods:
        def sample_without_replacement_method(n_population, n_samples,
                                              random_state=None):
            return sample_without_replacement(n_population, n_samples,
                                              method=m,
                                              random_state=random_state)

        check_edge_case_of_sample_int(sample_without_replacement_method)
        check_sample_int(sample_without_replacement_method)
        check_sample_int_distribution(sample_without_replacement_method)


def check_edge_case_of_sample_int(sample_without_replacement):

    # n_population < n_sample
    assert_raises(ValueError, sample_without_replacement, 0, 1)
    assert_raises(ValueError, sample_without_replacement, 1, 2)

    # n_population == n_samples
    assert sample_without_replacement(0, 0).shape == (0, )

    assert sample_without_replacement(1, 1).shape == (1, )

    # n_population >= n_samples
    assert sample_without_replacement(5, 0).shape == (0, )
    assert sample_without_replacement(5, 1).shape == (1, )

    # n_population < 0 or n_samples < 0
    assert_raises(ValueError, sample_without_replacement, -1, 5)
    assert_raises(ValueError, sample_without_replacement, 5, -1)


def check_sample_int(sample_without_replacement):
    # This test is heavily inspired from test_random.py of python-core.
    #
    # For the entire allowable range of 0 <= k <= N, validate that
    # the sample is of the correct length and contains only unique items
    n_population = 100

    for n_samples in range(n_population + 1):
        s = sample_without_replacement(n_population, n_samples)
        assert len(s) == n_samples
        unique = np.unique(s)
        assert np.size(unique) == n_samples
        assert np.all(unique < n_population)

    # test edge case n_population == n_samples == 0
    assert np.size(sample_without_replacement(0, 0)) == 0


def check_sample_int_distribution(sample_without_replacement):
    # This test is heavily inspired from test_random.py of python-core.
    #
    # For the entire allowable range of 0 <= k <= N, validate that
    # sample generates all possible permutations
    n_population = 10

    # a large number of trials prevents false negatives without slowing normal
    # case
    n_trials = 10000

    for n_samples in range(n_population):
        # Counting the number of combinations is not as good as counting the
        # the number of permutations. However, it works with sampling algorithm
        # that does not provide a random permutation of the subset of integer.
        n_expected = comb(n_population, n_samples, exact=True)

        output = {}
        for i in range(n_trials):
            output[frozenset(sample_without_replacement(n_population,
                                                        n_samples))] = None

            if len(output) == n_expected:
                break
        else:
            raise AssertionError(
                "number of combinations != number of expected (%s != %s)" %
                (len(output), n_expected))


def test_random_choice_csc(n_samples=10000, random_state=24):
    # Explicit class probabilities
    classes = [np.array([0, 1]),  np.array([0, 1, 2])]
    class_probabilities = [np.array([0.5, 0.5]), np.array([0.6, 0.1, 0.3])]

    got = random_choice_csc(n_samples, classes, class_probabilities,
                            random_state)
    assert sp.issparse(got)

    for k in range(len(classes)):
        p = np.bincount(got.getcol(k).toarray().ravel()) / float(n_samples)
        assert_array_almost_equal(class_probabilities[k], p, decimal=1)

    # Implicit class probabilities
    classes = [[0, 1],  [1, 2]]  # test for array-like support
    class_probabilities = [np.array([0.5, 0.5]), np.array([0, 1/2, 1/2])]

    got = random_choice_csc(n_samples=n_samples,
                            classes=classes,
                            random_state=random_state)
    assert sp.issparse(got)

    for k in range(len(classes)):
        p = np.bincount(got.getcol(k).toarray().ravel()) / float(n_samples)
        assert_array_almost_equal(class_probabilities[k], p, decimal=1)

    # Edge case probabilities 1.0 and 0.0
    classes = [np.array([0, 1]),  np.array([0, 1, 2])]
    class_probabilities = [np.array([1.0, 0.0]), np.array([0.0, 1.0, 0.0])]

    got = random_choice_csc(n_samples, classes, class_probabilities,
                            random_state)
    assert sp.issparse(got)

    for k in range(len(classes)):
        p = np.bincount(got.getcol(k).toarray().ravel(),
                        minlength=len(class_probabilities[k])) / n_samples
        assert_array_almost_equal(class_probabilities[k], p, decimal=1)

    # One class target data
    classes = [[1],  [0]]  # test for array-like support
    class_probabilities = [np.array([0.0, 1.0]), np.array([1.0])]

    got = random_choice_csc(n_samples=n_samples,
                            classes=classes,
                            random_state=random_state)
    assert sp.issparse(got)

    for k in range(len(classes)):
        p = np.bincount(got.getcol(k).toarray().ravel()) / n_samples
        assert_array_almost_equal(class_probabilities[k], p, decimal=1)


def test_random_choice_csc_errors():
    # the length of an array in classes and class_probabilities is mismatched
    classes = [np.array([0, 1]),  np.array([0, 1, 2, 3])]
    class_probabilities = [np.array([0.5, 0.5]), np.array([0.6, 0.1, 0.3])]
    assert_raises(ValueError, random_choice_csc, 4, classes,
                  class_probabilities, 1)

    # the class dtype is not supported
    classes = [np.array(["a", "1"]),  np.array(["z", "1", "2"])]
    class_probabilities = [np.array([0.5, 0.5]), np.array([0.6, 0.1, 0.3])]
    assert_raises(ValueError, random_choice_csc, 4, classes,
                  class_probabilities, 1)

    # the class dtype is not supported
    classes = [np.array([4.2, 0.1]),  np.array([0.1, 0.2, 9.4])]
    class_probabilities = [np.array([0.5, 0.5]), np.array([0.6, 0.1, 0.3])]
    assert_raises(ValueError, random_choice_csc, 4, classes,
                  class_probabilities, 1)

    # Given probabilities don't sum to 1
    classes = [np.array([0, 1]),  np.array([0, 1, 2])]
    class_probabilities = [np.array([0.5, 0.6]), np.array([0.6, 0.1, 0.3])]
    assert_raises(ValueError, random_choice_csc, 4, classes,
                  class_probabilities, 1)


@pytest.mark.parametrize("low,high,base",
                         [(-1, 0, 10), (0, 2, np.exp(1)), (-1, 1, 2)])
def test_loguniform(low, high, base):
    rv = loguniform(low, high, base=base)
    assert isinstance(rv, scipy.stats.rv_continuous)
    rvs = rv.rvs(size=2000, random_state=0)

    # Test the basics; right bounds, right size
    assert (base ** low <= rvs).all() and (rvs <= base ** high).all()
    assert len(rvs) == 2000

    # Test that it's actually (fairly) uniform
    log_rvs = np.array([math.log(x, base) for x in rvs])
    counts, _ = np.histogram(log_rvs)
    assert counts.mean() == 200
    assert np.abs(counts - counts.mean()).max() <= 40

    # Test that random_state works
    assert loguniform(low, high, base=base).rvs(random_state=0) == loguniform(
        low, high, base=base
    ).rvs(random_state=0)


def test_log_uniform_default_base(low=-1, high=0):
    rv = loguniform(low, high)
    rvs = rv.rvs(size=100)
    assert isinstance(rvs, np.ndarray)
    assert (10 ** low <= rvs).all() and (rvs <= 10 ** high).all()


def test_log_api_w_scipy(low=1, high=2):
    def _check_rvs(rvs, low, high):
        return low <= rvs.min() <= rvs.max() <= high

    # API difference: loguniform has [low, high] not uniform's [low, pdf_width]
    log = loguniform(low, high)
    uni = scipy.stats.uniform(low, high - low)
    assert isinstance(log.rvs(), float)
    assert isinstance(uni.rvs(), float)

    assert len(log.rvs(size=3)) == 3
    assert len(uni.rvs(size=3)) == 3
    assert _check_rvs(log.rvs(size=10), 10 ** low, 10 ** high)
    assert _check_rvs(uni.rvs(size=10), low, high)

    urvs = scipy.stats.uniform.rvs(size=4)
    assert 0 <= urvs.min() <= urvs.max() <= 1


@pytest.mark.xfail(raises=TypeError, reason="not developed")
def test_uniform_api(self):
    scipy.stats.uniform.rvs(size=4)
    with pytest.raises(TypeError):
        loguniform.rvs(size=4)
    raise TypeError


def test_our_rand_r():
    assert 131541053 == _our_rand_r_py(1273642419)
    assert 270369 == _our_rand_r_py(0)
