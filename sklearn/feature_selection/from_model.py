# Authors: Gilles Louppe, Mathieu Blondel, Maheshakya Wijewardena
# License: BSD 3 clause

import numpy as np
import numbers

from .base import SelectorMixin
from ..base import BaseEstimator, clone, MetaEstimatorMixin, is_classifier

from ..exceptions import NotFittedError
from ..utils.metaestimators import if_delegate_has_method, _safe_split
from ..utils._joblib import Parallel, delayed, effective_n_jobs
from sklearn.model_selection import check_cv


def _sfm_single_fit(sfm, estimator, X, y, train, test):
    """
    Return the _feature_importances for a fit across one fold.
    """
    X_train, y_train = _safe_split(estimator, X, y, train)
    X_test, y_test = _safe_split(estimator, X, y, test, train)
    sfm._fit(X_train, y_train)
    return _get_feature_importances(sfm.estimator_)


def _get_feature_importances(estimator, norm_order=1):
    """Retrieve or aggregate feature importances from estimator"""
    importances = getattr(estimator, "feature_importances_", None)

    coef_ = getattr(estimator, "coef_", None)
    if importances is None and coef_ is not None:
        if estimator.coef_.ndim == 1:
            importances = np.abs(coef_)

        else:
            importances = np.linalg.norm(coef_, axis=0,
                                         ord=norm_order)

    elif importances is None:
        raise ValueError(
            "The underlying estimator %s has no `coef_` or "
            "`feature_importances_` attribute. Either pass a fitted estimator"
            " to SelectFromModel or call fit before calling transform."
            % estimator.__class__.__name__)

    return importances


def _calculate_threshold(estimator, importances, threshold):
    """Interpret the threshold value"""

    if threshold is None:
        # determine default from estimator
        est_name = estimator.__class__.__name__
        if ((hasattr(estimator, "penalty") and estimator.penalty == "l1") or
                "Lasso" in est_name):
            # the natural default threshold is 0 when l1 penalty was used
            threshold = 1e-5
        else:
            threshold = "mean"

    if isinstance(threshold, str):
        if "*" in threshold:
            scale, reference = threshold.split("*")
            scale = float(scale.strip())
            reference = reference.strip()

            if reference == "median":
                reference = np.median(importances)
            elif reference == "mean":
                reference = np.mean(importances)
            else:
                raise ValueError("Unknown reference: " + reference)

            threshold = scale * reference

        elif threshold == "median":
            threshold = np.median(importances)

        elif threshold == "mean":
            threshold = np.mean(importances)

        else:
            raise ValueError("Expected threshold='mean' or threshold='median' "
                             "got %s" % threshold)

    else:
        threshold = float(threshold)

    return threshold


class SelectFromModel(BaseEstimator, SelectorMixin, MetaEstimatorMixin):
    """Meta-transformer for selecting features based on importance weights.

    .. versionadded:: 0.17

    Parameters
    ----------
    estimator : object
        The base estimator from which the transformer is built.
        This can be both a fitted (if ``prefit`` is set to True)
        or a non-fitted estimator. The estimator must have either a
        ``feature_importances_`` or ``coef_`` attribute after fitting.

    threshold : string, float, optional default None
        The threshold value to use for feature selection. Features whose
        importance is greater or equal are kept while the others are
        discarded. If "median" (resp. "mean"), then the ``threshold`` value is
        the median (resp. the mean) of the feature importances. A scaling
        factor (e.g., "1.25*mean") may also be used. If None and if the
        estimator has a parameter penalty set to l1, either explicitly
        or implicitly (e.g, Lasso), the threshold used is 1e-5.
        Otherwise, "mean" is used by default.

    prefit : bool, default False
        Whether a prefit model is expected to be passed into the constructor
        directly or not. If True, ``transform`` must be called directly
        and SelectFromModel cannot be used with ``cross_val_score``,
        ``GridSearchCV`` and similar utilities that clone the estimator.
        Otherwise train the model using ``fit`` and then ``transform`` to do
        feature selection.

    norm_order : non-zero int, inf, -inf, default 1
        Order of the norm used to filter the vectors of coefficients below
        ``threshold`` in the case where the ``coef_`` attribute of the
        estimator is of dimension 2.

    max_features : int or None, optional
        The maximum number of features selected scoring above ``threshold``.
        To disable ``threshold`` and only select based on ``max_features``,
        set ``threshold=-np.inf``.

        .. versionadded:: 0.20

    Attributes
    ----------
    estimator_ : an estimator
        The base estimator from which the transformer is built.
        This is stored only when a non-fitted estimator is passed to the
        ``SelectFromModel``, i.e when prefit is False.

    threshold_ : float
        The threshold value used for feature selection.
    """
    def __init__(self, estimator, threshold=None, prefit=False,
                 norm_order=1, max_features=None):
        self.estimator = estimator
        self.threshold = threshold
        self.prefit = prefit
        self.norm_order = norm_order
        self.max_features = max_features

    def _get_support_mask(self):
        # SelectFromModel can directly call on transform.
        if self.prefit:
            estimator = self.estimator
        elif hasattr(self, 'estimator_'):
            estimator = self.estimator_
        else:
            raise ValueError('Either fit the model before transform or set'
                             ' "prefit=True" while passing the fitted'
                             ' estimator to the constructor.')
        scores = _get_feature_importances(estimator, self.norm_order)
        threshold = _calculate_threshold(estimator, scores, self.threshold)
        if self.max_features is not None:
            mask = np.zeros_like(scores, dtype=bool)
            candidate_indices = \
                np.argsort(-scores, kind='mergesort')[:self.max_features]
            mask[candidate_indices] = True
        else:
            mask = np.ones_like(scores, dtype=bool)
        mask[scores < threshold] = False
        return mask

    def fit(self, X, y=None, **fit_params):
        """Fit the SelectFromModel meta-transformer.

        Parameters
        ----------
        X : array-like of shape (n_samples, n_features)
            The training input samples.

        y : array-like, shape (n_samples,)
            The target values (integers that correspond to classes in
            classification, real numbers in regression).

        **fit_params : Other estimator specific parameters

        Returns
        -------
        self : object
        """
        if self.max_features is not None:
            if not isinstance(self.max_features, numbers.Integral):
                raise TypeError("'max_features' should be an integer between"
                                " 0 and {} features. Got {!r} instead."
                                .format(X.shape[1], self.max_features))
            elif self.max_features < 0 or self.max_features > X.shape[1]:
                raise ValueError("'max_features' should be 0 and {} features."
                                 "Got {} instead."
                                 .format(X.shape[1], self.max_features))

        if self.prefit:
            raise NotFittedError(
                "Since 'prefit=True', call transform directly")
        return self._fit(X, y, **fit_params)

    def _fit(self, X, y=None, **fit_params):
        self.estimator_ = clone(self.estimator)
        self.estimator_.fit(X, y, **fit_params)
        return self

    @property
    def threshold_(self):
        scores = _get_feature_importances(self.estimator_, self.norm_order)
        return _calculate_threshold(self.estimator, scores, self.threshold)

    @if_delegate_has_method('estimator')
    def partial_fit(self, X, y=None, **fit_params):
        """Fit the SelectFromModel meta-transformer only once.

        Parameters
        ----------
        X : array-like of shape (n_samples, n_features)
            The training input samples.

        y : array-like, shape (n_samples,)
            The target values (integers that correspond to classes in
            classification, real numbers in regression).

        **fit_params : Other estimator specific parameters

        Returns
        -------
        self : object
        """
        if self.prefit:
            raise NotFittedError(
                "Since 'prefit=True', call transform directly")
        if not hasattr(self, "estimator_"):
            self.estimator_ = clone(self.estimator)
        self.estimator_.partial_fit(X, y, **fit_params)
        return self


class SelectFromModelCV(BaseEstimator, SelectorMixin, MetaEstimatorMixin):
    """Meta-transformer for selecting features based on importance weights.
    .. versionadded:: 0.17
    Parameters
    ----------
    estimator : object
        The base estimator from which the transformer is built.
        This can be both a fitted (if ``prefit`` is set to True)
        or a non-fitted estimator. The estimator must have either a
        ``feature_importances_`` or ``coef_`` attribute after fitting.
    threshold : string, float, optional default None
        The threshold value to use for feature selection. Features whose
        importance is greater or equal are kept while the others are
        discarded. If "median" (resp. "mean"), then the ``threshold`` value is
        the median (resp. the mean) of the feature importances. A scaling
        factor (e.g., "1.25*mean") may also be used. If None and if the
        estimator has a parameter penalty set to l1, either explicitly
        or implicitly (e.g, Lasso), the threshold used is 1e-5.
        Otherwise, "mean" is used by default.
    norm_order : non-zero int, inf, -inf, default 1
        Order of the norm used to filter the vectors of coefficients below
        ``threshold`` in the case where the ``coef_`` attribute of the
        estimator is of dimension 2.
    max_features : int or None, optional
        The maximum number of features selected scoring above ``threshold``.
        To disable ``threshold`` and only select based on ``max_features``,
        set ``threshold=-np.inf``.
        .. versionadded:: 0.20
    n_jobs : int or None, optional (default=None)
        Number of jobs to run in parallel.
        ``None`` means 1 unless in a :obj:`joblib.parallel_backend` context.
        ``-1`` means using all processors. See :term:`Glossary <n_jobs>`
        for more details.
    cv : int, cross-validation generator or an iterable, optional
        Determines the cross-validation splitting strategy.
        Possible inputs for cv are:
        - None, to use the default 3-fold cross-validation,
        - integer, to specify the number of folds.
        - :term:`CV splitter`,
        - An iterable yielding (train, test) splits as arrays of indices.
        For integer/None inputs, if ``y`` is binary or multiclass,
        :class:`sklearn.model_selection.StratifiedKFold` is used. If the
        estimator is a classifier or if ``y`` is neither binary nor multiclass,
        :class:`sklearn.model_selection.KFold` is used.
        Refer :ref:`User Guide <cross_validation>` for the various
        cross-validation strategies that can be used here.
        .. versionchanged:: 0.20
            ``cv`` default value of None will change from 3-fold to 5-fold
            in v0.22.
    Attributes
    ----------
    estimator_ : an estimator
        The base estimator from which the transformer is built.
        This is stored only when a non-fitted estimator is passed to the
        ``SelectFromModel``, i.e when prefit is False.
    threshold_ : float
        The threshold value used for feature selection.
    """
    def __init__(self, estimator, threshold=None, norm_order=1,
                 max_features=None, n_jobs=None, cv='warn'):
        self.estimator = estimator
        self.threshold = threshold
        self.norm_order = norm_order
        self.max_features = max_features
        self.n_jobs = n_jobs
        self.cv = cv

    def _get_support_mask(self):
        # SelectFromModel can directly call on transform.
        if hasattr(self, 'feature_importances_cv'):
            scores = np.mean(self.feature_importances_cv, axis=0)
        else:
            raise ValueError('Fit the model before transform.')
        threshold = _calculate_threshold(self.estimator, scores,
                                         self.threshold)
        if self.max_features is not None:
            mask = np.zeros_like(scores, dtype=bool)
            candidate_indices = \
                np.argsort(-scores, kind='mergesort')[:self.max_features]
            mask[candidate_indices] = True
        else:
            mask = np.ones_like(scores, dtype=bool)
        mask[scores < threshold] = False
        return mask

    def fit(self, X, y=None, groups=None, **fit_params):
        """Fit the SelectFromModel meta-transformer.
        Parameters
        ----------
        X : array-like of shape (n_samples, n_features)
            The training input samples.
        y : array-like, shape (n_samples,)
            The target values (integers that correspond to classes in
            classification, real numbers in regression).
        groups : array-like, shape = [n_samples], optional
            Group labels for the samples used while splitting the dataset into
            train/test set.
        **fit_params : Other estimator specific parameters
        Returns
        -------
        self : object
        """
        cv = check_cv(self.cv, y, is_classifier(self.estimator))
        if self.max_features is not None:
            if not isinstance(self.max_features, numbers.Integral):
                raise TypeError("'max_features' should be an integer between"
                                " 0 and {} features. Got {!r} instead."
                                .format(X.shape[1], self.max_features))
            elif self.max_features < 0 or self.max_features > X.shape[1]:
                raise ValueError("'max_features' should be 0 and {} features."
                                 "Got {} instead."
                                 .format(X.shape[1], self.max_features))

        sfm = SelectFromModel(estimator=self.estimator,
                              threshold=self.threshold,
                              norm_order=self.norm_order,
                              max_features=self.max_features)

        if effective_n_jobs(self.n_jobs) == 1:
            parallel, func = list, _sfm_single_fit
        else:
            parallel = Parallel(n_jobs=self.n_jobs)
            func = delayed(_sfm_single_fit)

        self.feature_importances_cv = parallel(
            func(sfm, self.estimator, X, y, train, test)
            for train, test in cv.split(X, y, groups))

        return self

    @property
    def threshold_(self):
        scores = np.mean(self.feature_importances_cv, axis=0)
        return _calculate_threshold(self.estimator, scores, self.threshold)
