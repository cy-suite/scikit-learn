# Authors: Andreas Mueller <amueller@ais.uni-bonn.de>
#          Joris Van den Bossche <jorisvandenbossche@gmail.com>
# License: BSD 3 clause

import numbers
import warnings

import numpy as np
from scipy import sparse

from ..base import BaseEstimator, TransformerMixin
from ..utils import check_array
from ..utils.fixes import _argmax
from ..utils.validation import check_is_fitted

from ._label import _encode, _encode_check_unknown


__all__ = [
    'OneHotEncoder',
    'OrdinalEncoder'
]


class _BaseEncoder(TransformerMixin, BaseEstimator):
    """
    Base class for encoders that includes the code to categorize and
    transform the input features.

    """

    def _check_X(self, X):
        """
        Perform custom check_array:
        - convert list of strings to object dtype
        - check for missing values for object dtype data (check_array does
          not do that)
        - return list of features (arrays): this list of features is
          constructed feature by feature to preserve the data types
          of pandas DataFrame columns, as otherwise information is lost
          and cannot be used, eg for the `categories_` attribute.

        """
        if not (hasattr(X, 'iloc') and getattr(X, 'ndim', 0) == 2):
            # if not a dataframe, do normal check_array validation
            X_temp = check_array(X, dtype=None)
            if (not hasattr(X, 'dtype')
                    and np.issubdtype(X_temp.dtype, np.str_)):
                X = check_array(X, dtype=np.object)
            else:
                X = X_temp
            needs_validation = False
        else:
            # pandas dataframe, do validation later column by column, in order
            # to keep the dtype information to be used in the encoder.
            needs_validation = True

        n_samples, n_features = X.shape
        X_columns = []

        for i in range(n_features):
            Xi = self._get_feature(X, feature_idx=i)
            Xi = check_array(Xi, ensure_2d=False, dtype=None,
                             force_all_finite=needs_validation)
            X_columns.append(Xi)

        return X_columns, n_samples, n_features

    def _get_feature(self, X, feature_idx):
        if hasattr(X, 'iloc'):
            # pandas dataframes
            return X.iloc[:, feature_idx]
        # numpy arrays, sparse arrays
        return X[:, feature_idx]

    def _fit(self, X, handle_unknown='error', process_counts=None):
        X_list, n_samples, n_features = self._check_X(X)

        if self.categories != 'auto':
            if len(self.categories) != n_features:
                raise ValueError("Shape mismatch: if categories is an array,"
                                 " it has to be of shape (n_features,).")

        self.categories_ = []

        return_counts = process_counts is not None
        category_counts = [] if return_counts else None

        for i in range(n_features):
            Xi = X_list[i]

            result = None
            if self.categories == 'auto':
                result = _encode(Xi, return_counts=return_counts)
                cats = result["uniques"]
            else:
                cats = np.array(self.categories[i], dtype=Xi.dtype)
                if Xi.dtype != object:
                    if not np.all(np.sort(cats) == cats):
                        raise ValueError("Unsorted categories are not "
                                         "supported for numerical categories")
                if handle_unknown == 'error':
                    diff = _encode_check_unknown(Xi, cats)
                    if diff:
                        msg = ("Found unknown categories {0} in column {1}"
                               " during fit".format(diff, i))
                        raise ValueError(msg)
            self.categories_.append(cats)

            if return_counts:
                if result is None:
                    result = _encode(Xi, cats, return_counts=True)
                category_counts.append(result["counts"])

        if return_counts:
            process_counts(category_counts, n_samples)

    def _transform(self, X, handle_unknown='error',
                   process_valid_mask=None,
                   get_default_invalid_category=None):
        X_list, n_samples, n_features = self._check_X(X)

        X_int = np.zeros((n_samples, n_features), dtype=np.int)
        X_mask = np.ones((n_samples, n_features), dtype=np.bool)

        if n_features != len(self.categories_):
            raise ValueError(
                "The number of features in X is different to the number of "
                "features of the fitted data. The fitted data had {} features "
                "and the X has {} features."
                .format(len(self.categories_,), n_features)
            )

        for i in range(n_features):
            Xi = X_list[i]
            diff, valid_mask = _encode_check_unknown(Xi, self.categories_[i],
                                                     return_mask=True)
            if not np.all(valid_mask):
                if handle_unknown == 'error':
                    msg = ("Found unknown categories {0} in column {1}"
                           " during transform".format(diff, i))
                    raise ValueError(msg)
                else:
                    # Set the problematic rows to an acceptable value and
                    # continue `The rows are marked `X_mask` and will be
                    # removed later.
                    # cast Xi into the largest string type necessary
                    # to handle different lengths of numpy strings
                    if (self.categories_[i].dtype.kind in ('U', 'S')
                            and self.categories_[i].itemsize > Xi.itemsize):
                        Xi = Xi.astype(self.categories_[i].dtype)
                    else:
                        Xi = Xi.copy()

                    if get_default_invalid_category is not None:
                        invalid_index = get_default_invalid_category(i)
                    else:
                        invalid_index = 0

                    Xi[~valid_mask] = self.categories_[i][invalid_index]

                    if process_valid_mask is not None:
                        valid_mask = process_valid_mask(valid_mask, i)

                    X_mask[:, i] = valid_mask

            # We use check_unknown=False, since _encode_check_unknown was
            # already called above.
            encoded = _encode(Xi, self.categories_[i], encode=True,
                              check_unknown=False)["encoded"]
            X_int[:, i] = encoded

        return X_int, X_mask

    def _more_tags(self):
        return {'X_types': ['categorical']}


class OneHotEncoder(_BaseEncoder):
    """
    Encode categorical features as a one-hot numeric array.

    The input to this transformer should be an array-like of integers or
    strings, denoting the values taken on by categorical (discrete) features.
    The features are encoded using a one-hot (aka 'one-of-K' or 'dummy')
    encoding scheme. This creates a binary column for each category and
    returns a sparse matrix or dense array (depending on the ``sparse``
    parameter)

    By default, the encoder derives the categories based on the unique values
    in each feature. Alternatively, you can also specify the `categories`
    manually.

    This encoding is needed for feeding categorical data to many scikit-learn
    estimators, notably linear models and SVMs with the standard kernels.

    Note: a one-hot encoding of y labels should use a LabelBinarizer
    instead.

    Read more in the :ref:`User Guide <preprocessing_categorical_features>`.

    .. versionchanged:: 0.20

    Parameters
    ----------
    categories : 'auto' or a list of array-like, default='auto'
        Categories (unique values) per feature:

        - 'auto' : Determine categories automatically from the training data.
        - list : ``categories[i]`` holds the categories expected in the ith
          column. The passed categories should not mix strings and numeric
          values within a single feature, and should be sorted in case of
          numeric values.

        The used categories can be found in the ``categories_`` attribute.

    drop : {'first', 'if_binary'} or a array-like of shape (n_features,), \
            default=None
        Specifies a methodology to use to drop one of the categories per
        feature. This is useful in situations where perfectly collinear
        features cause problems, such as when feeding the resulting data
        into a neural network or an unregularized regression. Drop is not
        support when `min_frequency` or `max_levels` is set to combine
        infrequent categories.

        - None : retain all features (the default).
        - 'first' : drop the first category in each feature. If only one
          category is present, the feature will be dropped entirely.
        - 'if_binary' : drop the first category in each feature with two
          categories. Features with 1 or more than 2 categories are
          left intact.
        - array : ``drop[i]`` is the category in feature ``X[:, i]`` that
          should be dropped.

    sparse : bool, default=True
        Will return sparse matrix if set True else will return an array.

    dtype : number type, default=np.float
        Desired dtype of output.

    handle_unknown : {'error', 'ignore', 'auto'}, default='error'
        Whether to raise an error or ignore if an unknown categorical feature
        is present during transform (default is to raise). When this parameter
        is set to 'ignore' and an unknown category is encountered during
        transform, the resulting one-hot encoded columns for this feature
        will be all zeros. In the inverse transform, an unknown category
        will be denoted as None.

        When this parameter is set to 'auto' and an unknown category is
        encountered in transform:

            1. If there was no infrequent category during training, the
            resulting one-hot encoded columns for this feature will be all
            zeros. In the inverse transform, an unknown category will be
            denoted as None.

            2. If there is an infrequent category during training, the unknown
            category will be considered infrequent. In the inverse transform,
            an unknown category will be the most frequent infrequent category

        .. versionadded:: 0.23
            'auto' was added to automatically handle unknown categories

        .. deprecated:: 0.23
            'ignore' is deprecated in favor of 'auto'

    min_frequency : int or float, default=1
        Specifies the categories to be considered infrequent.

            1. If int, categories with a cardinality smaller will be considered
            infrequent.

            2. If float, categories with a cardinality smaller than
            `min_frequency * n_samples`  will be considered infrequent.

        .. versionadded:: 0.23

    max_levels : int, default=None
        Specifies an upper limit to the number of output features for each
        input feature when considering infrequent categories. `max_levels`
        includes the feature that combines infrequent categories. If `None`
        there is no limit to the number of output features.

        .. versionadded:: 0.23

    Attributes
    ----------
    categories_ : list of arrays
        The categories of each feature determined during fitting
        (in order of the features in X and corresponding with the output
        of ``transform``). This includes the category specified in ``drop``
        (if any).

    drop_idx_ : array of shape (n_features,)
        ``drop_idx_[i]`` is the index in ``categories_[i]`` of the category to
        be dropped for each feature.
        ``drop_idx_[i] = -1`` if no category is to be dropped from the feature
        with index ``i``, e.g. when `drop='if_binary'` and the feature isn't
        binary

        ``drop_idx_ = None`` if all the transformed features will be retained.

    infrequent_indices_ : list of shape (n_features,)
        Defined when `min_frequency` or `max_levels` is set to a non-default
        value. `infrequent_indices_[i]` is an array of indices corresponding to
        `categories_[i]` of the infrequent categories. `infrequent_indices_[i]`
        is None if the ith input feature has no infrequent categories.

    See Also
    --------
    sklearn.preprocessing.OrdinalEncoder : Performs an ordinal (integer)
      encoding of the categorical features.
    sklearn.feature_extraction.DictVectorizer : Performs a one-hot encoding of
      dictionary items (also handles string-valued features).
    sklearn.feature_extraction.FeatureHasher : Performs an approximate one-hot
      encoding of dictionary items or strings.
    sklearn.preprocessing.LabelBinarizer : Binarizes labels in a one-vs-all
      fashion.
    sklearn.preprocessing.MultiLabelBinarizer : Transforms between iterable of
      iterables and a multilabel format, e.g. a (samples x classes) binary
      matrix indicating the presence of a class label.

    Examples
    --------
    Given a dataset with two features, we let the encoder find the unique
    values per feature and transform the data to a binary one-hot encoding.

    >>> from sklearn.preprocessing import OneHotEncoder

    One can discard categories not seen during `fit`:

    >>> enc = OneHotEncoder(handle_unknown='auto')
    >>> X = [['Male', 1], ['Female', 3], ['Female', 2]]
    >>> enc.fit(X)
    OneHotEncoder(handle_unknown='auto')
    >>> enc.categories_
    [array(['Female', 'Male'], dtype=object), array([1, 2, 3], dtype=object)]
    >>> enc.transform([['Female', 1], ['Male', 4]]).toarray()
    array([[1., 0., 1., 0., 0.],
           [0., 1., 0., 0., 0.]])
    >>> enc.inverse_transform([[0, 1, 1, 0, 0], [0, 0, 0, 1, 0]])
    array([['Male', 1],
           [None, 2]], dtype=object)
    >>> enc.get_feature_names(['gender', 'group'])
    array(['gender_Female', 'gender_Male', 'group_1', 'group_2', 'group_3'],
      dtype=object)

    One can always drop the first column for each feature:

    >>> drop_enc = OneHotEncoder(drop='first').fit(X)
    >>> drop_enc.categories_
    [array(['Female', 'Male'], dtype=object), array([1, 2, 3], dtype=object)]
    >>> drop_enc.transform([['Female', 1], ['Male', 2]]).toarray()
    array([[0., 0., 0.],
           [1., 1., 0.]])

    Or drop a column for feature only having 2 categories:

    >>> drop_binary_enc = OneHotEncoder(drop='if_binary').fit(X)
    >>> drop_binary_enc.transform([['Female', 1], ['Male', 2]]).toarray()
    array([[0., 1., 0., 0.],
           [1., 0., 1., 0.]])
    """

    def __init__(self, categories='auto', drop=None, sparse=True,
                 dtype=np.float64, handle_unknown='error',
                 min_frequency=1, max_levels=None):
        self.categories = categories
        self.sparse = sparse
        self.dtype = dtype
        self.handle_unknown = handle_unknown
        self.drop = drop
        self.min_frequency = min_frequency
        self.max_levels = max_levels

    def _validate_keywords(self):

        if self.handle_unknown not in ('error', 'ignore', 'auto'):
            msg = ("handle_unknown should be either 'error', 'ignore', 'auto'"
                   "got {0}.".format(self.handle_unknown))
            raise ValueError(msg)
        # If we have both dropped columns and ignored unknown
        # values, there will be ambiguous cells. This creates difficulties
        # in interpreting the model.
        if self.drop is not None and self.handle_unknown != 'error':
            raise ValueError(
                "`handle_unknown` must be 'error' when the drop parameter is "
                "specified, as both would create categories that are all "
                "zero.")

        # validates infrequent category features
        if self.drop is not None and self._infrequent_enabled:
            raise ValueError("infrequent categories are not supported when "
                             "drop is specified")

        # TODO: Remove when handle_unknown='ignore' is deprecated
        if self.handle_unknown == 'ignore':
            warnings.warn("handle_unknown='ignore' is deprecated in favor "
                          "of 'auto' in version 0.23 and will be removed in "
                          "version 0.25", FutureWarning)
            if self._infrequent_enabled:
                raise ValueError("infrequent categories are only supported "
                                 "when handle_unknown is 'error' or 'auto'")

        if self.max_levels is not None and self.max_levels <= 1:
            raise ValueError("max_levels must be greater than 1")

        if isinstance(self.min_frequency, numbers.Integral):
            if not self.min_frequency >= 1:
                raise ValueError("min_frequency must be an integer at least "
                                 "1 or a float in (0.0, 1.0); got the "
                                 "integer {}".format(self.min_frequency))
        else:  # float
            if not 0.0 < self.min_frequency < 1.0:
                raise ValueError("min_frequency must be an integer at least "
                                 "1 or a float in (0.0, 1.0); got the "
                                 "float {}".format(self.min_frequency))

    def _compute_drop_idx(self):
        if self.drop is None:
            return None
        elif isinstance(self.drop, str):
            if self.drop == 'first':
                return np.zeros(len(self.categories_), dtype=np.int_)
            elif self.drop == 'if_binary':
                return np.array([0 if len(cats) == 2 else -1
                                for cats in self.categories_], dtype=np.int_)
            else:
                msg = (
                    "Wrong input for parameter `drop`. Expected "
                    "'first', 'if_binary', None or array of objects, got {}"
                    )
                raise ValueError(msg.format(type(self.drop)))

        else:
            try:
                self.drop = np.asarray(self.drop, dtype=object)
                droplen = len(self.drop)
            except (ValueError, TypeError):
                msg = (
                    "Wrong input for parameter `drop`. Expected "
                    "'first', 'if_binary', None or array of objects, got {}"
                    )
                raise ValueError(msg.format(type(self.drop)))
            if droplen != len(self.categories_):
                msg = ("`drop` should have length equal to the number "
                       "of features ({}), got {}")
                raise ValueError(msg.format(len(self.categories_),
                                            len(self.drop)))
            missing_drops = [(i, val) for i, val in enumerate(self.drop)
                             if val not in self.categories_[i]]
            if any(missing_drops):
                msg = ("The following categories were supposed to be "
                       "dropped, but were not found in the training "
                       "data.\n{}".format(
                           "\n".join(
                                ["Category: {}, Feature: {}".format(c, v)
                                    for c, v in missing_drops])))
                raise ValueError(msg)
            return np.array([np.where(cat_list == val)[0][0]
                             for (val, cat_list) in
                             zip(self.drop, self.categories_)], dtype=np.int_)

    @property
    def _infrequent_enabled(self):
        """Infrequent category is enabled."""
        return (self.max_levels is not None and self.max_levels > 1 or
                (isinstance(self.min_frequency, numbers.Integral)
                    and self.min_frequency > 1) or
                (isinstance(self.min_frequency, numbers.Real)
                    and 0.0 < self.min_frequency < 1.0))

    def _identify_infrequent(self, category_count, n_samples, col_idx):
        """Compute the infrequent indicies based on max_levels and
        min_frequency.

        Parameters
        ----------
        category_count : ndarray of shape (n_cardinality,)
            category counts

        n_samples : int
            number of samples

        col_idx : int
            index of current category only used for the error message

        Returns
        -------
        output : ndarray of shape (n_infrequent_categories,) or None
            If there are infrequent categories, indicies of infrequent
            categories. Otherwise None.
        """
        # categories with no count are infrequent
        infrequent_mask = category_count == 0

        if isinstance(self.min_frequency, numbers.Integral):
            if self.min_frequency > 1:
                category_mask = category_count < self.min_frequency
                infrequent_mask |= category_mask
        else:  # float
            if 0.0 < self.min_frequency < 1.0:
                min_frequency_abs = n_samples * self.min_frequency
                category_mask = category_count < min_frequency_abs
                infrequent_mask |= category_mask

        if (self.max_levels is not None and self.max_levels > 1
                and self.max_levels < category_count.size):
            # stable sort to preserve original count order
            smallest_levels = np.argsort(category_count, kind='mergesort'
                                         )[:-self.max_levels + 1]
            infrequent_mask[smallest_levels] = True

        output = np.flatnonzero(infrequent_mask)

        if output.size == category_count.size:
            raise ValueError("All categories in column {} are infrequent"
                             .format(col_idx))
        return output if output.size > 0 else None

    def _fit_infrequent_category_mapping(self, category_counts, n_samples):
        """Fit infrequent categories.

        Defines:
            1. infrequent_indices_ to be the categories that are infrequent.
            2. _default_to_infrequent_mappings to be the mapping from the
               default mapping provided by _encode to the infrequent categories
            3. _largest_infreq_indices to be the indices of the most frequent
               infrequent category

        Parameters
        ----------
        category_counts : list of ndarrays
            list of category counts

        n_samples : int
            number of samples
        """
        self.infrequent_indices_ = [
            self._identify_infrequent(category_count, n_samples, col_idx)
            for col_idx, category_count in enumerate(category_counts)]

        # compute mapping from default mapping to infrequent mapping
        default_to_infrequent_mappings = []
        largest_infreq_idxs = []

        for category_count, infreq_idx in zip(category_counts,
                                              self.infrequent_indices_):
            # no infrequent categories
            if infreq_idx is None:
                default_to_infrequent_mappings.append(None)
                largest_infreq_idxs.append(None)
                continue

            # infrequent indicies exist
            mapping = np.empty_like(category_count, dtype=np.int)
            n_cats = mapping.size
            n_infrequent_cats = infreq_idx.size

            n_frequent_cats = n_cats - n_infrequent_cats
            mapping[infreq_idx] = n_frequent_cats

            frequent_indices = np.setdiff1d(np.arange(n_cats), infreq_idx)
            mapping[frequent_indices] = np.arange(n_frequent_cats)

            default_to_infrequent_mappings.append(mapping)

            # compute infrequent category with the largest cardinality
            largest_infreq_idx = np.argmax(category_count[infreq_idx])
            largest_infreq_idxs.append(infreq_idx[largest_infreq_idx])

        self._default_to_infrequent_mappings = default_to_infrequent_mappings
        self._largest_infreq_indices = largest_infreq_idxs

    def _map_to_infrequent_categories(self, X_int):
        """Map categories to infrequent categories.
        This modifies X_int in-place.

        Parameters
        ----------
        X_int: ndarray of shape (n_samples, n_features)
            integer encoded categories
        """
        if not self._infrequent_enabled:
            return

        for i, mapping in enumerate(self._default_to_infrequent_mappings):
            if mapping is None:
                continue
            X_int[:, i] = np.take(mapping, X_int[:, i])

    def _get_default_invalid_category(self, col_idx):
        """Get default invalid category for column index during `_transform`.

        This function is pasesd to `_transform` to set the invalid categories.
        """
        infrequent_idx = self.infrequent_indices_[col_idx]
        return 0 if infrequent_idx is None else infrequent_idx[0]

    def _process_valid_mask(self, valid_mask, col_idx):
        """Process the valid mask during `_transform`

        This function is passed to `_transform` to adjust the mask depending
        on if the infrequent column exists or not.

        Parameters
        ----------
        valid_mask : array of shape (n_samples, )
            boolean mask representing if a sample was seen during training

        col_idx : int
            column index

        Returns
        -------
        valid_mask : array of shape (n_samples,) or None
            boolean mask to use for constructing X_mask in `_transform`.
        """
        if self.handle_unknown != 'auto':
            return valid_mask

        # handle_unknown == 'auto'
        infrequent_idx = self.infrequent_indices_[col_idx]

        # infrequent column does not exists
        # returning the original mask to allow the column to be ignored
        if infrequent_idx is None:
            return valid_mask

        # infrequent column exists
        # the unknown categories will be mapped to the infrequent category
        return np.ones_like(valid_mask, dtype=bool)

    def _compute_transformed_categories(self, i):
        """Compute the transformed categories used for column `i`.

        1. Dropped columns are removed.
        2. If there are infrequent categories, the infrequent category with
        the largest cardinality is placed at the end.
        """
        cats = self.categories_[i]

        if self.drop is not None:
            # early exit because infrequent categories and drop is forbidden
            return np.delete(cats, self.drop_idx_[i])

        # drop is None
        if not self._infrequent_enabled:
            return cats

        # infrequent is enabled
        infreq_idx = self.infrequent_indices_[i]
        if infreq_idx is None:
            return cats

        largest_infreq_idx = self._largest_infreq_indices[i]
        largest_infreq_cat = cats[largest_infreq_idx]
        frequent_indices = np.setdiff1d(np.arange(len(cats)), infreq_idx)

        return np.r_[cats[frequent_indices], [largest_infreq_cat]]

    @property
    def _n_transformed_features(self):
        """Number of transformed features."""
        if self.drop is not None:
            if self.drop == 'first':
                return [len(cats) - 1 for cats in self.categories_]

            # drop == 'if_binary
            return [1 if len(cats) == 2 else len(cats)
                    for cats in self.categories_]

        # drop is None
        output = [len(cats) for cats in self.categories_]

        if not self._infrequent_enabled:
            return output

        # infrequent is enabled
        for i, infreq_idx in enumerate(self.infrequent_indices_):
            if infreq_idx is None:
                continue
            output[i] = output[i] - infreq_idx.size + 1

        return output

    @property
    def _transformed_categories(self):
        """Transformed categories."""
        return [self._compute_transformed_categories(i)
                for i in range(len(self.categories_))]

    def fit(self, X, y=None):
        """
        Fit OneHotEncoder to X.

        Parameters
        ----------
        X : array-like, shape [n_samples, n_features]
            The data to determine the categories of each feature.

        y : None
            Ignored. This parameter exists only for compatibility with
            :class:`sklearn.pipeline.Pipeline`.

        Returns
        -------
        self
        """
        self._validate_keywords()

        process_counts = (self._fit_infrequent_category_mapping
                          if self._infrequent_enabled else None)
        self._fit(X, handle_unknown=self.handle_unknown,
                  process_counts=process_counts)
        self.drop_idx_ = self._compute_drop_idx()
        return self

    def fit_transform(self, X, y=None):
        """
        Fit OneHotEncoder to X, then transform X.

        Equivalent to fit(X).transform(X) but more convenient.

        Parameters
        ----------
        X : array-like, shape [n_samples, n_features]
            The data to encode.

        y : None
            Ignored. This parameter exists only for compatibility with
            :class:`sklearn.pipeline.Pipeline`.

        Returns
        -------
        X_out : sparse matrix if sparse=True else a 2-d array
            Transformed input.
        """
        self._validate_keywords()
        return super().fit_transform(X, y)

    def transform(self, X):
        """
        Transform X using one-hot encoding.

        Parameters
        ----------
        X : array-like, shape [n_samples, n_features]
            The data to encode.

        Returns
        -------
        X_out : sparse matrix if sparse=True else a 2-d array
            Transformed input.
        """
        check_is_fitted(self)
        # validation of X happens in _check_X called by _transform
        transform_kws = {"handle_unknown": self.handle_unknown}
        if self._infrequent_enabled:
            transform_kws.update({
                "process_valid_mask": self._process_valid_mask,
                "get_default_invalid_category":
                self._get_default_invalid_category
            })

        X_int, X_mask = self._transform(X, **transform_kws)
        self._map_to_infrequent_categories(X_int)

        n_samples, n_features = X_int.shape

        if self.drop is not None:
            to_drop = self.drop_idx_.copy()
            # We remove all the dropped categories from mask, and decrement all
            # categories that occur after them to avoid an empty column.
            keep_cells = X_int != to_drop
            for i, cats in enumerate(self.categories_):
                # drop='if_binary' but feature isn't binary
                if to_drop[i] == -1:
                    # set to cardinality to not drop from X_int
                    to_drop[i] = len(cats)

            to_drop = to_drop.reshape(1, -1)
            X_int[X_int > to_drop] -= 1
            X_mask &= keep_cells

        n_values = self._n_transformed_features

        mask = X_mask.ravel()
        feature_indices = np.cumsum([0] + n_values)
        indices = (X_int + feature_indices[:-1]).ravel()[mask]

        indptr = np.empty(n_samples + 1, dtype=np.int)
        indptr[0] = 0
        np.sum(X_mask, axis=1, out=indptr[1:])
        np.cumsum(indptr[1:], out=indptr[1:])
        data = np.ones(indptr[-1])

        out = sparse.csr_matrix((data, indices, indptr),
                                shape=(n_samples, feature_indices[-1]),
                                dtype=self.dtype)
        if not self.sparse:
            return out.toarray()
        else:
            return out

    def inverse_transform(self, X):
        """
        Convert the data back to the original representation.

        In case unknown categories are encountered (all zeros in the
        one-hot encoding), ``None`` is used to represent this category.

        For a given input feature, if there is an infrequent category, the most
        frequent infrequent category will be used to represent this category.

        Parameters
        ----------
        X : array-like or sparse matrix, shape [n_samples, n_encoded_features]
            The transformed data.

        Returns
        -------
        X_tr : array-like, shape [n_samples, n_features]
            Inverse transformed array.
        """
        check_is_fitted(self)
        X = check_array(X, accept_sparse='csr')

        n_samples, _ = X.shape
        n_features = len(self.categories_)
        n_transformed_features = sum(self._n_transformed_features)

        # validate shape of passed X
        msg = ("Shape of the passed X data is not correct. Expected {0} "
               "columns, got {1}.")
        if X.shape[1] != n_transformed_features:
            raise ValueError(msg.format(n_transformed_features, X.shape[1]))

        # create resulting array of appropriate dtype
        dt = np.find_common_type([cat.dtype for cat in self.categories_], [])
        X_tr = np.empty((n_samples, n_features), dtype=dt)

        j = 0
        found_unknown = {}

        if self._infrequent_enabled:
            infrequent_indices = self.infrequent_indices_
        else:
            infrequent_indices = [None] * n_features

        for i in range(n_features):
            n_categories = self._n_transformed_features[i]
            cats = self._transformed_categories[i]

            # Only happens if there was a column with a unique
            # category. In this case we just fill the column with this
            # unique category value.
            if n_categories == 0:
                X_tr[:, i] = self.categories_[i][self.drop_idx_[i]]
                j += n_categories
                continue
            sub = X[:, j:j + n_categories]
            # for sparse X argmax returns 2D matrix, ensure 1D array
            labels = np.asarray(_argmax(sub, axis=1)).flatten()
            X_tr[:, i] = cats[labels]

            if (self.handle_unknown == 'ignore' or
                (self.handle_unknown == 'auto' and
                 infrequent_indices[i] is None)):
                unknown = np.asarray(sub.sum(axis=1) == 0).flatten()
                # ignored unknown categories: we have a row of all zero
                if unknown.any():
                    found_unknown[i] = unknown
            # drop will either be None or handle_unknown will be error. If
            # self.drop is not None, then we can safely assume that all of
            # the nulls in each column are the dropped value
            elif self.drop is not None:
                dropped = np.asarray(sub.sum(axis=1) == 0).flatten()
                if dropped.any():
                    X_tr[dropped, i] = self.categories_[i][self.drop_idx_[i]]

            j += n_categories

        # if ignored are found: potentially need to upcast result to
        # insert None values
        if found_unknown:
            if X_tr.dtype != object:
                X_tr = X_tr.astype(object)

            for idx, mask in found_unknown.items():
                X_tr[mask, idx] = None

        return X_tr

    def get_feature_names(self, input_features=None):
        """
        Return feature names for output features.

        For a given input feature, if there is an infrequent category, the most
        frequent infrequent category will be used as a feature name.

        Parameters
        ----------
        input_features : list of str of shape (n_features,)
            String names for input features if available. By default,
            "x0", "x1", ... "xn_features" is used.

        Returns
        -------
        output_feature_names : ndarray of shape (n_output_features,)
            Array of feature names.
        """
        check_is_fitted(self)
        cats = self._transformed_categories
        if input_features is None:
            input_features = ['x%d' % i for i in range(len(cats))]
        elif len(input_features) != len(cats):
            raise ValueError(
                "input_features should have length equal to number of "
                "features ({}), got {}".format(len(cats), len(input_features)))

        feature_names = []
        for i in range(len(cats)):
            names = [input_features[i] + '_' + str(t) for t in cats[i]]
            feature_names.extend(names)

        return np.array(feature_names, dtype=object)


class OrdinalEncoder(_BaseEncoder):
    """
    Encode categorical features as an integer array.

    The input to this transformer should be an array-like of integers or
    strings, denoting the values taken on by categorical (discrete) features.
    The features are converted to ordinal integers. This results in
    a single column of integers (0 to n_categories - 1) per feature.

    Read more in the :ref:`User Guide <preprocessing_categorical_features>`.

    .. versionchanged:: 0.20.1

    Parameters
    ----------
    categories : 'auto' or a list of array-like, default='auto'
        Categories (unique values) per feature:

        - 'auto' : Determine categories automatically from the training data.
        - list : ``categories[i]`` holds the categories expected in the ith
          column. The passed categories should not mix strings and numeric
          values, and should be sorted in case of numeric values.

        The used categories can be found in the ``categories_`` attribute.

    dtype : number type, default np.float64
        Desired dtype of output.

    Attributes
    ----------
    categories_ : list of arrays
        The categories of each feature determined during fitting
        (in order of the features in X and corresponding with the output
        of ``transform``).

    See Also
    --------
    sklearn.preprocessing.OneHotEncoder : Performs a one-hot encoding of
      categorical features.
    sklearn.preprocessing.LabelEncoder : Encodes target labels with values
      between 0 and n_classes-1.

    Examples
    --------
    Given a dataset with two features, we let the encoder find the unique
    values per feature and transform the data to an ordinal encoding.

    >>> from sklearn.preprocessing import OrdinalEncoder
    >>> enc = OrdinalEncoder()
    >>> X = [['Male', 1], ['Female', 3], ['Female', 2]]
    >>> enc.fit(X)
    OrdinalEncoder()
    >>> enc.categories_
    [array(['Female', 'Male'], dtype=object), array([1, 2, 3], dtype=object)]
    >>> enc.transform([['Female', 3], ['Male', 1]])
    array([[0., 2.],
           [1., 0.]])

    >>> enc.inverse_transform([[1, 0], [0, 1]])
    array([['Male', 1],
           ['Female', 2]], dtype=object)
    """

    def __init__(self, categories='auto', dtype=np.float64):
        self.categories = categories
        self.dtype = dtype

    def fit(self, X, y=None):
        """
        Fit the OrdinalEncoder to X.

        Parameters
        ----------
        X : array-like, shape [n_samples, n_features]
            The data to determine the categories of each feature.

        y : None
            Ignored. This parameter exists only for compatibility with
            :class:`sklearn.pipeline.Pipeline`.

        Returns
        -------
        self
        """
        self._fit(X)

        return self

    def transform(self, X):
        """
        Transform X to ordinal codes.

        Parameters
        ----------
        X : array-like, shape [n_samples, n_features]
            The data to encode.

        Returns
        -------
        X_out : sparse matrix or a 2-d array
            Transformed input.
        """
        X_int, _ = self._transform(X)
        return X_int.astype(self.dtype, copy=False)

    def inverse_transform(self, X):
        """
        Convert the data back to the original representation.

        Parameters
        ----------
        X : array-like or sparse matrix, shape [n_samples, n_encoded_features]
            The transformed data.

        Returns
        -------
        X_tr : array-like, shape [n_samples, n_features]
            Inverse transformed array.
        """
        check_is_fitted(self)
        X = check_array(X, accept_sparse='csr')

        n_samples, _ = X.shape
        n_features = len(self.categories_)

        # validate shape of passed X
        msg = ("Shape of the passed X data is not correct. Expected {0} "
               "columns, got {1}.")
        if X.shape[1] != n_features:
            raise ValueError(msg.format(n_features, X.shape[1]))

        # create resulting array of appropriate dtype
        dt = np.find_common_type([cat.dtype for cat in self.categories_], [])
        X_tr = np.empty((n_samples, n_features), dtype=dt)

        for i in range(n_features):
            labels = X[:, i].astype('int64', copy=False)
            X_tr[:, i] = self.categories_[i][labels]

        return X_tr
