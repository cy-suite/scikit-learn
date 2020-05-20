import numpy as np
import scipy.sparse as sp
import pytest

from sklearn.utils._testing import (assert_array_almost_equal,
                                   assert_allclose)

from sklearn.decomposition import PCA, KernelPCA
from sklearn.datasets import make_circles
from sklearn.datasets import make_blobs
from sklearn.exceptions import NotFittedError
from sklearn.linear_model import Perceptron
from sklearn.pipeline import Pipeline
from sklearn.model_selection import GridSearchCV
from sklearn.metrics.pairwise import rbf_kernel
from sklearn.utils.validation import _check_psd_eigenvalues


def test_kernel_pca():
    """ Nominal test for all solvers and all known kernels + a custom one.
    It tests
     - that fit_transform is equivalent to fit+transform
     - that the shapes of transforms and inverse transforms are correct """
    rng = np.random.RandomState(0)
    X_fit = rng.random_sample((5, 4))
    X_pred = rng.random_sample((2, 4))

    def histogram(x, y, **kwargs):
        # Histogram kernel implemented as a callable.
        assert kwargs == {}    # no kernel_params that we didn't ask for
        return np.minimum(x, y).sum()

    for eigen_solver in ("auto", "dense", "arpack", "randomized"):
        for kernel in ("linear", "rbf", "poly", histogram):
            # histogram kernel produces singular matrix inside linalg.solve
            # XXX use a least-squares approximation?
            inv = not callable(kernel)

            # transform fit data
            kpca = KernelPCA(4, kernel=kernel, eigen_solver=eigen_solver,
                             fit_inverse_transform=inv)
            X_fit_transformed = kpca.fit_transform(X_fit)
            X_fit_transformed2 = kpca.fit(X_fit).transform(X_fit)
            assert_array_almost_equal(np.abs(X_fit_transformed),
                                      np.abs(X_fit_transformed2))

            # non-regression test: previously, gamma would be 0 by default,
            # forcing all eigenvalues to 0 under the poly kernel
            assert X_fit_transformed.size != 0

            # transform new data
            X_pred_transformed = kpca.transform(X_pred)
            assert (X_pred_transformed.shape[1] ==
                         X_fit_transformed.shape[1])

            # inverse transform
            if inv:
                X_pred2 = kpca.inverse_transform(X_pred_transformed)
                assert X_pred2.shape == X_pred.shape


def test_kernel_pca_invalid_parameters():
    with pytest.raises(ValueError):
        KernelPCA(10, fit_inverse_transform=True, kernel='precomputed')


def test_kernel_pca_consistent_transform():
    """ Tests that after fitting a kPCA model, it is independent of the
    original data object (uses an inner copy) """
    # X_fit_ needs to retain the old, unmodified copy of X
    state = np.random.RandomState(0)
    X = state.rand(10, 10)
    kpca = KernelPCA(random_state=state).fit(X)
    transformed1 = kpca.transform(X)

    X_copy = X.copy()
    X[:, 0] = 666
    transformed2 = kpca.transform(X_copy)
    assert_array_almost_equal(transformed1, transformed2)


def test_kernel_pca_deterministic_output():
    rng = np.random.RandomState(0)
    X = rng.rand(10, 10)
    eigen_solver = ('arpack', 'dense')

    for solver in eigen_solver:
        transformed_X = np.zeros((20, 2))
        for i in range(20):
            kpca = KernelPCA(n_components=2, eigen_solver=solver,
                             random_state=rng)
            transformed_X[i, :] = kpca.fit_transform(X)[0]
        assert_allclose(
            transformed_X, np.tile(transformed_X[0, :], 20).reshape(20, 2))


def test_kernel_pca_sparse():
    """ Tests that kPCA works on a sparse data input. Same test as
    test_kernel_pca except inverse_transform since it's not implemented
    for sparse matrices"""
    rng = np.random.RandomState(0)
    X_fit = sp.csr_matrix(rng.random_sample((5, 4)))
    X_pred = sp.csr_matrix(rng.random_sample((2, 4)))

    for eigen_solver in ("auto", "arpack", "randomized"):
        for kernel in ("linear", "rbf", "poly"):
            # transform fit data
            kpca = KernelPCA(4, kernel=kernel, eigen_solver=eigen_solver,
                             fit_inverse_transform=False)
            X_fit_transformed = kpca.fit_transform(X_fit)
            X_fit_transformed2 = kpca.fit(X_fit).transform(X_fit)
            assert_array_almost_equal(np.abs(X_fit_transformed),
                                      np.abs(X_fit_transformed2))

            # transform new data
            X_pred_transformed = kpca.transform(X_pred)
            assert (X_pred_transformed.shape[1] ==
                         X_fit_transformed.shape[1])

            # inverse transform: not available for sparse matrices
            with pytest.raises(NotFittedError):
                kpca.inverse_transform(X_pred_transformed)


@pytest.mark.parametrize("solver", ["auto", "dense", "arpack", "randomized"],
                         ids="solver={}".format)
@pytest.mark.parametrize("n_features", [4, 10], ids="n_features={}".format)
def test_kernel_pca_linear_kernel(solver, n_features):
    """ Tests that kPCA with a linear kernel is equivalent to PCA for all
    solvers"""
    rng = np.random.RandomState(0)
    X_fit = rng.random_sample((5, n_features))
    X_pred = rng.random_sample((2, n_features))

    # for a linear kernel, kernel PCA should find the same projection as PCA
    # modulo the sign (direction)
    # fit only the first four components: fifth is near zero eigenvalue, so
    # can be trimmed due to roundoff error
    n_comps = 3 if solver == "arpack" else 4
    assert_array_almost_equal(
        np.abs(KernelPCA(n_comps, eigen_solver=solver).fit(X_fit)
               .transform(X_pred)),
        np.abs(PCA(n_comps, svd_solver=solver if solver != "dense" else "full")
               .fit(X_fit).transform(X_pred)))


def test_kernel_pca_n_components():
    """ Tests that the number of components selected is correctly taken into
    account for projections, for all solvers """
    rng = np.random.RandomState(0)
    X_fit = rng.random_sample((5, 4))
    X_pred = rng.random_sample((2, 4))

    for eigen_solver in ("dense", "arpack", "randomized"):
        for c in [1, 2, 4]:
            kpca = KernelPCA(n_components=c, eigen_solver=eigen_solver)
            shape = kpca.fit(X_fit).transform(X_pred).shape

            assert shape == (2, c)


def test_remove_zero_eig():
    """ Tests that the null-space (Zero) eigenvalues are removed when
    remove_zero_eig=True, whereas they are not by default """
    X = np.array([[1 - 1e-30, 1], [1, 1], [1, 1 - 1e-20]])

    # n_components=None (default) => remove_zero_eig is True
    kpca = KernelPCA()
    Xt = kpca.fit_transform(X)
    assert Xt.shape == (3, 0)

    kpca = KernelPCA(n_components=2)
    Xt = kpca.fit_transform(X)
    assert Xt.shape == (3, 2)

    kpca = KernelPCA(n_components=2, remove_zero_eig=True)
    Xt = kpca.fit_transform(X)
    assert Xt.shape == (3, 0)


def test_leave_zero_eig():
    """This test checks that fit().transform() returns the same result as
    fit_transform() in case of non-removed zero eigenvalue.
    Non-regression test for issue #12141 (PR #12143)"""
    X_fit = np.array([[1, 1], [0, 0]])

    # Assert that even with all np warnings on, there is no div by zero warning
    with pytest.warns(None) as record:
        with np.errstate(all='warn'):
            k = KernelPCA(n_components=2, remove_zero_eig=False,
                          eigen_solver="dense")
            # Fit, then transform
            A = k.fit(X_fit).transform(X_fit)
            # Do both at once
            B = k.fit_transform(X_fit)
            # Compare
            assert_array_almost_equal(np.abs(A), np.abs(B))

    for w in record:
        # There might be warnings about the kernel being badly conditioned,
        # but there should not be warnings about division by zero.
        # (Numpy division by zero warning can have many message variants, but
        # at least we know that it is a RuntimeWarning so lets check only this)
        assert not issubclass(w.category, RuntimeWarning)


def test_kernel_pca_precomputed():
    """ Tests that kPCA works when the kernel has been precomputed, for all
    solvers """
    rng = np.random.RandomState(0)
    X_fit = rng.random_sample((5, 4))
    X_pred = rng.random_sample((2, 4))

    for eigen_solver in ("dense", "arpack", "randomized"):
        X_kpca = KernelPCA(4, eigen_solver=eigen_solver).\
            fit(X_fit).transform(X_pred)
        X_kpca2 = KernelPCA(
            4, eigen_solver=eigen_solver, kernel='precomputed').fit(
                np.dot(X_fit, X_fit.T)).transform(np.dot(X_pred, X_fit.T))

        X_kpca_train = KernelPCA(
            4, eigen_solver=eigen_solver,
            kernel='precomputed').fit_transform(np.dot(X_fit, X_fit.T))
        X_kpca_train2 = KernelPCA(
            4, eigen_solver=eigen_solver, kernel='precomputed').fit(
                np.dot(X_fit, X_fit.T)).transform(np.dot(X_fit, X_fit.T))

        assert_array_almost_equal(np.abs(X_kpca),
                                  np.abs(X_kpca2))

        assert_array_almost_equal(np.abs(X_kpca_train),
                                  np.abs(X_kpca_train2))


def test_kernel_pca_invalid_kernel():
    """ Tests that using an invalid kernel name raises a ValueError at fit
    time"""
    rng = np.random.RandomState(0)
    X_fit = rng.random_sample((2, 4))
    kpca = KernelPCA(kernel="tototiti")
    with pytest.raises(ValueError):
        kpca.fit(X_fit)


def test_gridsearch_pipeline():
    # Test if we can do a grid-search to find parameters to separate
    # circles with a perceptron model.
    X, y = make_circles(n_samples=400, factor=.3, noise=.05,
                        random_state=0)
    kpca = KernelPCA(kernel="rbf", n_components=2)
    pipeline = Pipeline([("kernel_pca", kpca),
                         ("Perceptron", Perceptron(max_iter=5))])
    param_grid = dict(kernel_pca__gamma=2. ** np.arange(-2, 2))
    grid_search = GridSearchCV(pipeline, cv=3, param_grid=param_grid)
    grid_search.fit(X, y)
    assert grid_search.best_score_ == 1


def test_gridsearch_pipeline_precomputed():
    # Test if we can do a grid-search to find parameters to separate
    # circles with a perceptron model using a precomputed kernel.
    X, y = make_circles(n_samples=400, factor=.3, noise=.05,
                        random_state=0)
    kpca = KernelPCA(kernel="precomputed", n_components=2)
    pipeline = Pipeline([("kernel_pca", kpca),
                         ("Perceptron", Perceptron(max_iter=5))])
    param_grid = dict(Perceptron__max_iter=np.arange(1, 5))
    grid_search = GridSearchCV(pipeline, cv=3, param_grid=param_grid)
    X_kernel = rbf_kernel(X, gamma=2.)
    grid_search.fit(X_kernel, y)
    assert grid_search.best_score_ == 1


def test_nested_circles():
    # Test the linear separability of the first 2D KPCA transform
    X, y = make_circles(n_samples=400, factor=.3, noise=.05,
                        random_state=0)

    # 2D nested circles are not linearly separable
    train_score = Perceptron(max_iter=5).fit(X, y).score(X, y)
    assert train_score < 0.8

    # Project the circles data into the first 2 components of a RBF Kernel
    # PCA model.
    # Note that the gamma value is data dependent. If this test breaks
    # and the gamma value has to be updated, the Kernel PCA example will
    # have to be updated too.
    kpca = KernelPCA(kernel="rbf", n_components=2,
                     fit_inverse_transform=True, gamma=2.)
    X_kpca = kpca.fit_transform(X)

    # The data is perfectly linearly separable in that space
    train_score = Perceptron(max_iter=5).fit(X_kpca, y).score(X_kpca, y)
    assert train_score == 1.0


def test_kernel_conditioning():
    """ Test that ``_check_psd_eigenvalues`` is correctly called
    Non-regression test for issue #12140 (PR #12145)"""

    # create a pathological X leading to small non-zero eigenvalue
    X = [[5, 1],
         [5+1e-8, 1e-8],
         [5+1e-8, 0]]
    kpca = KernelPCA(kernel="linear", n_components=2,
                     fit_inverse_transform=True)
    kpca.fit(X)

    # check that the small non-zero eigenvalue was correctly set to zero
    assert kpca.lambdas_.min() == 0
    assert np.all(kpca.lambdas_ == _check_psd_eigenvalues(kpca.lambdas_))


@pytest.mark.parametrize("solver", ["auto", "dense", "arpack", "randomized"],
                         ids="solver={}".format)
def test_precomputed_kernel_not_psd(solver):
    """ Tests for all methods that an appropriate error is returned when the
    provided precomputed kernel is invalid """

    # a custom gram matrix purposedly not Positive Semi Definite
    K = np.diag([2., 0., 0., -2., -2.])

    # ask for enough components to get a negative even with truncated methods
    kpca = KernelPCA(kernel="precomputed", eigen_solver=solver, n_components=4)

    # make sure that the appropriate error is raised
    with pytest.raises(ValueError,
                       match="There are significant negative eigenvalues"):
        kpca.fit(K)


@pytest.mark.parametrize("n_components", [4, 10, 20],
                         ids="n_components={}".format)
def test_kernel_pca_solvers_equivalence(n_components):
    """Checks that 'dense', 'arpack' and 'randomized' solvers give similar
    results"""

    # Generate random data
    n_training_samples = 2000
    n_features = 10
    rng = np.random.RandomState(0)
    X_fit = rng.random_sample((n_training_samples, n_features))
    X_pred = rng.random_sample((100, n_features))

    # reference (full)
    ref_pred = KernelPCA(n_components, eigen_solver="dense")\
        .fit(X_fit).transform(X_pred)

    # arpack
    a_pred = KernelPCA(n_components, eigen_solver="arpack")\
        .fit(X_fit).transform(X_pred)
    # check that the result is still correct despite the approx
    assert_array_almost_equal(np.abs(a_pred), np.abs(ref_pred))

    # randomized
    r_pred = KernelPCA(n_components, eigen_solver="randomized")\
        .fit(X_fit).transform(X_pred)
    # check that the result is still correct despite the approximation
    assert_array_almost_equal(np.abs(r_pred), np.abs(ref_pred))


@pytest.mark.parametrize("kernel",
                         ["linear", "poly", "rbf", "sigmoid", "cosine"])
def test_kernel_pca_inverse_transform(kernel):
    X, *_ = make_blobs(n_samples=100, n_features=4, centers=[[1, 1, 1, 1]],
                       random_state=0)

    kp = KernelPCA(n_components=2, kernel=kernel, fit_inverse_transform=True)
    X_trans = kp.fit_transform(X)
    X_inv = kp.inverse_transform(X_trans)
    assert_allclose(X, X_inv)
