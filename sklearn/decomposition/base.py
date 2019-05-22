"""Principal Component Analysis Base Classes"""

# Author: Alexandre Gramfort <alexandre.gramfort@inria.fr>
#         Olivier Grisel <olivier.grisel@ensta.org>
#         Mathieu Blondel <mathieu@mblondel.org>
#         Denis A. Engemann <denis-alexander.engemann@inria.fr>
#         Kyle Kastner <kastnerkyle@gmail.com>
#
# License: BSD 3 clause

import numpy as np
from scipy import linalg

from ..base import BaseEstimator, TransformerMixin
from ..utils import check_array
from ..utils.validation import check_is_fitted
from abc import ABCMeta, abstractmethod


class _BasePCA(BaseEstimator, TransformerMixin, metaclass=ABCMeta):
    """Base class for PCA methods.

    Warning: This class should not be used directly.
    Use derived classes instead.
    """

    def _get_mat_inv_lemma_diag(self):
        '''
        returns diagonal terms of the D matrix as a 1xn array. This is given by 
        inverse of 1/noise_variance + inv(S**2 - noise_variance) or
        inverse of S**2/noise_variance + inv(S**2 - noise_variance) if whiten is True
        S**2 is the first n_components of explained_variance.
        '''
        
        exp_var = self.explained_variance_
        exp_var_diff = np.maximum(exp_var - self.noise_variance_, 0.)
        pre_precision = 1 / self.noise_variance_
#        if self.whiten: #old implementation for whiten==True is wrong. Uncomment to obtain same output as old implementation.
#            pre_precision *= exp_var
        
        pre_precision += 1 / exp_var_diff

        return (1 / pre_precision).reshape(1, -1)
		
        
    def _get_logdet_precision(self):
        n_features = self.mean_.shape[0]
        noise_var = self.noise_variance_

        exp_var = self.explained_variance_
#        if self.whiten: #old implementation for whiten==True is wrong. Uncomment to obtain same output as old implementation.
#            exp_var = exp_var * (exp_var - noise_var) + noise_var

        logdet = - np.sum(np.log(exp_var))
        logdet -= math.log(noise_var) * (n_features - self.n_components_)

        return logdet
		

    @abstractmethod
    def fit(X, y=None):
        """Placeholder for fit. Subclasses should implement this method!

        Fit the model with X.

        Parameters
        ----------
        X : array-like, shape (n_samples, n_features)
            Training data, where n_samples is the number of samples and
            n_features is the number of features.

        Returns
        -------
        self : object
            Returns the instance itself.
        """

    def transform(self, X):
        """Apply dimensionality reduction to X.

        X is projected on the first principal components previously extracted
        from a training set.

        Parameters
        ----------
        X : array-like, shape (n_samples, n_features)
            New data, where n_samples is the number of samples
            and n_features is the number of features.

        Returns
        -------
        X_new : array-like, shape (n_samples, n_components)

        Examples
        --------

        >>> import numpy as np
        >>> from sklearn.decomposition import IncrementalPCA
        >>> X = np.array([[-1, -1], [-2, -1], [-3, -2], [1, 1], [2, 1], [3, 2]])
        >>> ipca = IncrementalPCA(n_components=2, batch_size=3)
        >>> ipca.fit(X)
        IncrementalPCA(batch_size=3, copy=True, n_components=2, whiten=False)
        >>> ipca.transform(X) # doctest: +SKIP
        """
        check_is_fitted(self, ['mean_', 'components_'], all_or_any=all)

        X = check_array(X)
        if self.mean_ is not None:
            X = X - self.mean_
        X_transformed = np.dot(X, self.components_.T)
        if self.whiten:
            X_transformed /= np.sqrt(self.explained_variance_)
        return X_transformed

    def inverse_transform(self, X):
        """Transform data back to its original space.

        In other words, return an input X_original whose transform would be X.

        Parameters
        ----------
        X : array-like, shape (n_samples, n_components)
            New data, where n_samples is the number of samples
            and n_components is the number of components.

        Returns
        -------
        X_original array-like, shape (n_samples, n_features)

        Notes
        -----
        If whitening is enabled, inverse_transform will compute the
        exact inverse operation, which includes reversing whitening.
        """
        if self.whiten:
            return np.dot(X, np.sqrt(self.explained_variance_[:, np.newaxis]) *
                            self.components_) + self.mean_
        else:
            return np.dot(X, self.components_) + self.mean_
