from sklearn.base import BaseEstimator
from sklearn.utils.testing import assert_true


class ArraySlicingWrapper(object):
    def __init__(self, array):
        self.array = array

    def __getitem__(self, aslice):
        return MockDataFrame(self.array[aslice])


class MockDataFrame(object):

    # have shape an length but don't support indexing.
    def __init__(self, array):
        self.array = array
        self.shape = array.shape
        self.ndim = array.ndim
        # ugly hack to make iloc work.
        self.iloc = ArraySlicingWrapper(array)

    def __len__(self):
        return len(self.array)

    def __array__(self):
        # Pandas data frames also are array-like: we want to make sure that
        # input validation in cross-validation does not try to call that
        # method.
        return self.array


class CheckingClassifier(BaseEstimator):
    """Dummy classifier to test pipelining and meta-estimators.

    Checks some property of X and y in fit / predict.
    This allows testing whether pipelines / cross-validation or metaestimators
    changed the input.
    """
    def __init__(self, check_y=None, check_X=None, check_sample_props=None,
                 foo_param=0, check_all=None):
        self.check_y = check_y
        self.check_X = check_X
        self.check_sample_props = check_sample_props
        self.check_all = check_all
        self.foo_param = foo_param

    def fit(self, X, y, sample_props=None):
        assert_true(len(X) == len(y))
        if self.check_X is not None:
            assert_true(self.check_X(X))
        if self.check_y is not None:
            assert_true(self.check_y(y))
        if self.check_sample_props is not None:
            assert_true(self.check_sample_props(sample_props))
        if self.check_all is not None:
            assert_true(self.check_all(X, y, sample_props))

        return self

    def predict(self, T):
        if self.check_X is not None:
            assert_true(self.check_X(T))
        return T.shape[0]

    def score(self, X=None, Y=None):
        if self.foo_param > 1:
            score = 1.
        else:
            score = 0.
        return score
