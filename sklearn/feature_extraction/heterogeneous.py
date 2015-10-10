from scipy import sparse
import numpy as np

from ..base import BaseEstimator, TransformerMixin
from ..pipeline import _fit_one_transformer, _fit_transform_one, _transform_one
from ..externals.joblib import Parallel, delayed
from ..externals.six import iteritems


class ColumnTransformer(BaseEstimator, TransformerMixin):
    """Applies transformers to columns of a dataframe / dict.

    This estimator applies transformer objects to columns or fields of the
    input, then concatenates the results. This is useful for heterogeneous or
    columnar data, to combine several feature extraction mechanisms into a
    single transformer.

    Read more in the :ref:`User Guide <column_transformer>`.

    Parameters
    ----------
    transformers : dict from string to (string, transformer) tuples
        Keys are arbitrary names, values are tuples of column names and
        transformer objects.

    n_jobs : int, optional
        Number of jobs to run in parallel (default 1).

    transformer_weights : dict, optional
        Multiplicative weights for features per transformer.
        Keys are transformer names, values the weights.

    Examples
    --------
    >>> from sklearn.preprocessing import Normalizer
    >>> union = ColumnTransformer({"norm1": (Normalizer(norm='l1'), 'subset1'),  \
                                   "norm2": (Normalizer(norm='l1'), 'subset2')})
    >>> X = {'subset1': [[0., 1.], [2., 2.]], 'subset2': [[1., 1.], [0., 1.]]}
    >>> union.fit_transform(X)    # doctest: +NORMALIZE_WHITESPACE
    array([[ 0. ,  1. ,  0.5,  0.5],
           [ 0.5,  0.5,  0. ,  1. ]])

    """
    def __init__(self, transformers, n_jobs=1, transformer_weights=None):
        self.transformers = transformers
        self.n_jobs = n_jobs
        self.transformer_weights = transformer_weights

    def get_feature_names(self):
        """Get feature names from all transformers.

        Returns
        -------
        feature_names : list of strings
            Names of the features produced by transform.
        """
        feature_names = []
        for name, (trans, column) in sorted(self.transformers.items()):
            if not hasattr(trans, 'get_feature_names'):
                raise AttributeError("Transformer %s does not provide"
                                     " get_feature_names." % str(name))
            feature_names.extend([name + "__" + f for f in
                                  trans.get_feature_names()])
        return feature_names

    def get_params(self, deep=True):
        if not deep:
            return super(ColumnTransformer, self).get_params(deep=False)
        else:
            out = dict(self.transformers)
            for name, (trans, _) in self.transformers.items():
                for key, value in iteritems(trans.get_params(deep=True)):
                    out['%s__%s' % (name, key)] = value
            out.update(super(ColumnTransformer, self).get_params(deep=False))
            return out

    def fit(self, X, y=None):
        """Fit all transformers using X.

        Parameters
        ----------
        X : array-like or sparse matrix, shape (n_samples, n_features)
            Input data, used to fit transformers.
        """
        transformers = Parallel(n_jobs=self.n_jobs)(
            delayed(_fit_one_transformer)(trans, X[column], y)
            for name, (trans, column) in sorted(self.transformers.items()))
        self._update_transformers(transformers)
        return self

    def fit_transform(self, X, y=None, **fit_params):
        """Fit all transformers using X, transform the data and concatenate
        results.

        Parameters
        ----------
        X : array-like or sparse matrix, shape (n_samples, n_features)
            Input data to be transformed.

        Returns
        -------
        X_t : array-like or sparse matrix, shape (n_samples, sum_n_components)
            hstack of results of transformers. sum_n_components is the
            sum of n_components (output dimension) over transformers.
        """
        result = Parallel(n_jobs=self.n_jobs)(
            delayed(_fit_transform_one)(trans, name, X[column], y,
                                        self.transformer_weights,
                                        **fit_params)
            for name, (trans, column) in sorted(self.transformers.items()))

        Xs, transformers = zip(*result)
        self._update_transformers(transformers)
        if any(sparse.issparse(f) for f in Xs):
            Xs = sparse.hstack(Xs).tocsr()
        else:
            Xs = np.hstack(Xs)
        return Xs

    def transform(self, X):
        """Transform X separately by each transformer, concatenate results.

        Parameters
        ----------
        X : array-like or sparse matrix, shape (n_samples, n_features)
            Input data to be transformed.

        Returns
        -------
        X_t : array-like or sparse matrix, shape (n_samples, sum_n_components)
            hstack of results of transformers. sum_n_components is the
            sum of n_components (output dimension) over transformers.
        """
        Xs = Parallel(n_jobs=self.n_jobs)(
            delayed(_transform_one)(trans, name, X[column], self.transformer_weights)
            for name, (trans, column) in sorted(self.transformers.items()))
        if any(sparse.issparse(f) for f in Xs):
            Xs = sparse.hstack(Xs).tocsr()
        else:
            Xs = np.hstack(Xs)
        return Xs

    def _update_transformers(self, transformers):
        # use a dict constructor instaed of a dict comprehension for python2.6
        self.transformers.update(dict(
            (name, (new, column))
            for ((name, (old, column)), new) in zip(sorted(self.transformers.items()), transformers))
        )
