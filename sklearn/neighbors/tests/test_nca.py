import pytest
import re
import numpy as np
from numpy.testing import assert_array_equal, assert_array_almost_equal
from scipy.optimize import check_grad
from sklearn import clone
from sklearn.exceptions import ConvergenceWarning
from sklearn.utils import check_random_state
from sklearn.utils.testing import (assert_raises, assert_equal,
                                   assert_raise_message, assert_warns_message,
                                   assert_true)
from sklearn.datasets import load_iris, make_classification
from sklearn.neighbors.nca import NeighborhoodComponentsAnalysis
from sklearn.metrics import pairwise_distances


rng = check_random_state(0)
# load and shuffle iris dataset
iris = load_iris()
perm = rng.permutation(iris.target.size)
iris_data = iris.data[perm]
iris_target = iris.target[perm]
EPS = np.finfo(float).eps


def test_simple_example():
    """Test on a simple example.

    Puts four points in the input space where the opposite labels points are
    next to each other. After transform the same labels points should be next
    to each other.

    """
    X = np.array([[0, 0], [0, 1], [2, 0], [2, 1]])
    y = np.array([1, 0, 1, 0])
    nca = NeighborhoodComponentsAnalysis(n_components=2, init='identity',
                                         random_state=42)
    nca.fit(X, y)
    X_t = nca.transform(X)
    np.testing.assert_equal(pairwise_distances(X_t).argsort()[:, 1],
                            np.array([2, 3, 0, 1]))


def test_toy_example_collapse_points():
    """Test on a toy example of three points that should collapse

    Test that on this simple example, the new points are collapsed:
    Two same label points with a different label point in the middle.
    The objective is 2/(1 + exp(d/2)), with d the euclidean distance
    between the two same labels points. This is maximized for d=0
    (because d>=0), with an objective equal to 1 (loss=-1.).

    """
    input_dim = 5
    two_points = rng.randn(2, input_dim)
    X = np.vstack([two_points, two_points.mean(axis=0)[np.newaxis, :]])
    y = [0, 0, 1]
    nca = NeighborhoodComponentsAnalysis(random_state=42,
                                         store_opt_result=True)
    X_t = nca.fit_transform(X, y)
    print(X_t)
    # test that points are collapsed into one point
    assert_array_almost_equal(X_t - X_t[0], 0.)
    assert nca.opt_result_.fun + 1 < 1e-10


def test_finite_differences():
    """Test gradient of loss function

    Assert that the gradient is almost equal to its finite differences
    approximation.
    """
    # Initialize the transformation `M`, as well as `X` and `y` and `NCA`
    X, y = make_classification()
    M = rng.randn(rng.randint(1, X.shape[1] + 1), X.shape[1])
    nca = NeighborhoodComponentsAnalysis()
    nca.n_iter_ = 0
    mask = y[:, np.newaxis] == y[np.newaxis, :]

    def fun(M): return nca._loss_grad_lbfgs(M, X, mask)[0]

    def grad(M): return nca._loss_grad_lbfgs(M, X, mask)[1]

    # compute relative error
    rel_diff = check_grad(fun, grad, M.ravel()) / np.linalg.norm(grad(M))
    np.testing.assert_almost_equal(rel_diff, 0., decimal=5)


def test_params_validation():
    # Test that invalid parameters raise value error
    X = np.arange(12).reshape(4, 3)
    y = [1, 1, 2, 2]
    NCA = NeighborhoodComponentsAnalysis

    # TypeError
    assert_raises(TypeError, NCA(max_iter='21').fit, X, y)
    assert_raises(TypeError, NCA(verbose='true').fit, X, y)
    assert_raises(TypeError, NCA(tol=1).fit, X, y)
    assert_raises(TypeError, NCA(n_components='invalid').fit, X, y)
    assert_raises(TypeError, NCA(warm_start=1).fit, X, y)

    # ValueError
    assert_raise_message(ValueError,
                         "`init` must be 'auto', 'pca', 'lda', 'identity', "
                         "'random' or a numpy array of shape "
                         "(n_components, n_features).",
                         NCA(init=1).fit, X, y)
    assert_raise_message(ValueError,
                         '`max_iter`= -1, must be >= 1.',
                         NCA(max_iter=-1).fit, X, y)

    init = rng.rand(5, 3)
    assert_raise_message(ValueError,
                         'The output dimensionality ({}) of the given linear '
                         'transformation `init` cannot be greater than its '
                         'input dimensionality ({}).'
                         .format(init.shape[0], init.shape[1]),
                         NCA(init=init).fit, X, y)

    n_components = 10
    assert_raise_message(ValueError,
                         'The preferred embedding dimensionality '
                         '`n_components` ({}) cannot be greater '
                         'than the given data dimensionality ({})!'
                         .format(n_components, X.shape[1]),
                         NCA(n_components=n_components).fit, X, y)


def test_transformation_dimensions():
    X = np.arange(12).reshape(4, 3)
    y = [1, 1, 2, 2]

    # Fail if transformation input dimension does not match inputs dimensions
    transformation = np.array([[1, 2], [3, 4]])
    assert_raises(ValueError,
                  NeighborhoodComponentsAnalysis(init=transformation).fit,
                  X, y)

    # Fail if transformation output dimension is larger than
    # transformation input dimension
    transformation = np.array([[1, 2], [3, 4], [5, 6]])
    # len(transformation) > len(transformation[0])
    assert_raises(ValueError,
                  NeighborhoodComponentsAnalysis(init=transformation).fit,
                  X, y)

    # Pass otherwise
    transformation = np.arange(9).reshape(3, 3)
    NeighborhoodComponentsAnalysis(init=transformation).fit(X, y)


def test_n_components():
    X = np.arange(12).reshape(4, 3)
    y = [1, 1, 2, 2]

    init = rng.rand(X.shape[1] - 1, 3)

    # n_components = X.shape[1] != transformation.shape[0]
    n_components = X.shape[1]
    nca = NeighborhoodComponentsAnalysis(init=init, n_components=n_components)
    assert_raise_message(ValueError,
                         'The preferred embedding dimensionality '
                         '`n_components` ({}) does not match '
                         'the output dimensionality of the given '
                         'linear transformation `init` ({})!'
                         .format(n_components, init.shape[0]),
                         nca.fit, X, y)

    # n_components > X.shape[1]
    n_components = X.shape[1] + 2
    nca = NeighborhoodComponentsAnalysis(init=init, n_components=n_components)
    assert_raise_message(ValueError,
                         'The preferred embedding dimensionality '
                         '`n_components` ({}) cannot be greater '
                         'than the given data dimensionality ({})!'
                         .format(n_components, X.shape[1]),
                         nca.fit, X, y)

    # n_components < X.shape[1]
    nca = NeighborhoodComponentsAnalysis(n_components=2, init='identity')
    nca.fit(X, y)


def test_init_transformation():
    X, y = make_classification(n_samples=30, n_features=5,
                               n_redundant=0, random_state=0)

    # Start learning from scratch
    nca = NeighborhoodComponentsAnalysis(init='identity')
    nca.fit(X, y)

    # Initialize with random
    nca_random = NeighborhoodComponentsAnalysis(init='random')
    nca_random.fit(X, y)

    # Initialize with auto
    nca_auto = NeighborhoodComponentsAnalysis(init='auto')
    nca_auto.fit(X, y)

    # Initialize with PCA
    nca_pca = NeighborhoodComponentsAnalysis(init='pca')
    nca_pca.fit(X, y)

    # Initialize with LDA
    nca_lda = NeighborhoodComponentsAnalysis(init='lda')
    nca_lda.fit(X, y)

    init = rng.rand(X.shape[1], X.shape[1])
    nca = NeighborhoodComponentsAnalysis(init=init)
    nca.fit(X, y)

    # init.shape[1] must match X.shape[1]
    init = rng.rand(X.shape[1], X.shape[1] + 1)
    nca = NeighborhoodComponentsAnalysis(init=init)
    assert_raise_message(ValueError,
                         'The input dimensionality ({}) of the given '
                         'linear transformation `init` must match the '
                         'dimensionality of the given inputs `X` ({}).'
                         .format(init.shape[1], X.shape[1]),
                         nca.fit, X, y)

    # init.shape[0] must be <= init.shape[1]
    init = rng.rand(X.shape[1] + 1, X.shape[1])
    nca = NeighborhoodComponentsAnalysis(init=init)
    assert_raise_message(ValueError,
                         'The output dimensionality ({}) of the given '
                         'linear transformation `init` cannot be '
                         'greater than its input dimensionality ({}).'
                         .format(init.shape[0], init.shape[1]),
                         nca.fit, X, y)

    # init.shape[0] must match n_components
    init = rng.rand(X.shape[1], X.shape[1])
    n_components = X.shape[1] - 2
    nca = NeighborhoodComponentsAnalysis(init=init, n_components=n_components)
    assert_raise_message(ValueError,
                         'The preferred embedding dimensionality '
                         '`n_components` ({}) does not match '
                         'the output dimensionality of the given '
                         'linear transformation `init` ({})!'
                         .format(n_components, init.shape[0]),
                         nca.fit, X, y)


@pytest.mark.parametrize('n_samples', [17, 19, 23, 29])
@pytest.mark.parametrize('n_features', [17, 19, 23, 29])
@pytest.mark.parametrize('n_classes', [17, 19, 23])
@pytest.mark.parametrize('n_components', [17, 19, 23, 29])
def test_auto_init(n_samples, n_features, n_classes, n_components):
    # Test that auto choose the init as expected with every configuration
    # of order of n_samples, n_features, n_classes and n_components.
    nca_base = NeighborhoodComponentsAnalysis(init='auto',
                                              n_components=n_components,
                                              max_iter=1, random_state=rng)
    if n_classes >= n_samples:
        pass
        # n_classes > n_samples is impossible, and n_classes == n_samples
        # throws an error from lda but is an absurd case
    else:
        X = rng.randn(n_samples, n_features)
        y = np.tile(range(n_classes), n_samples // n_classes + 1)[:n_samples]
        if n_components > n_features:
            pass
        else:
            nca = clone(nca_base)
            nca.fit(X, y)
            if n_components <= n_classes:
                nca_other = clone(nca_base).set_params(init='lda')
            elif n_components < min(n_features, n_samples):
                nca_other = clone(nca_base).set_params(init='pca')
            else:
                nca_other = clone(nca_base).set_params(init='identity')
            nca_other.fit(X, y)
            assert_array_almost_equal(nca.components_, nca_other.components_)


def test_warm_start_validation():
    X, y = make_classification(n_samples=30, n_features=5, n_classes=4,
                               n_redundant=0, n_informative=5, random_state=0)

    nca = NeighborhoodComponentsAnalysis(warm_start=True, max_iter=5)
    nca.fit(X, y)

    X_less_features, y = make_classification(n_samples=30, n_features=4,
                                             n_classes=4, n_redundant=0,
                                             n_informative=4, random_state=0)
    assert_raise_message(ValueError,
                         'The new inputs dimensionality ({}) does not '
                         'match the input dimensionality of the '
                         'previously learned transformation ({}).'
                         .format(X_less_features.shape[1],
                                 nca.components_.shape[1]),
                         nca.fit, X_less_features, y)


def test_warm_start_effectiveness():
    # A 1-iteration second fit on same data should give almost same result
    # with warm starting, and quite different result without warm starting.

    X, y = load_iris(return_X_y=True)

    nca_warm = NeighborhoodComponentsAnalysis(warm_start=True, random_state=0)
    nca_warm.fit(X, y)
    transformation_warm = nca_warm.components_
    nca_warm.max_iter = 1
    nca_warm.fit(X, y)
    transformation_warm_plus_one = nca_warm.components_

    nca_cold = NeighborhoodComponentsAnalysis(warm_start=False, random_state=0)
    nca_cold.fit(X, y)
    transformation_cold = nca_cold.components_
    nca_cold.max_iter = 1
    nca_cold.fit(X, y)
    transformation_cold_plus_one = nca_cold.components_

    diff_warm = np.sum(np.abs(transformation_warm_plus_one -
                              transformation_warm))
    diff_cold = np.sum(np.abs(transformation_cold_plus_one -
                              transformation_cold))

    assert_true(diff_warm < 3.0,
                "Transformer changed significantly after one iteration even "
                "though it was warm-started.")

    assert_true(diff_cold > diff_warm,
                "Cold-started transformer changed less significantly than "
                "warm-started transformer after one iteration.")


@pytest.mark.parametrize('init_name', ['pca', 'lda', 'identity', 'random',
                                       'precomputed'])
def test_verbose(init_name, capsys):
    # assert there is proper output when verbose = 1, for every initialization
    # except auto because auto will call one of the others
    regexp_init = r'... done in \ *\d+\.\d{2}s'
    msgs = {'pca': "Finding principal components" + regexp_init,
            'lda': "Finding most discriminative components" + regexp_init}
    if init_name == 'precomputed':
        init = rng.randn(iris_data.shape[1], iris_data.shape[1])
    else:
        init = init_name
    nca = NeighborhoodComponentsAnalysis(verbose=1, init=init)
    nca.fit(iris_data, iris_target)
    out, _ = capsys.readouterr()

    # check output
    lines = re.split('\n+', out)
    # if pca or lda init, an additional line is printed, so we test
    # it and remove it to test the rest equally among initializations
    if init_name in ['pca', 'lda']:
        assert re.match(msgs[init_name], lines[0])
        lines = lines[1:]
    assert lines[0] == '[NeighborhoodComponentsAnalysis]'
    header = '{:>10} {:>20} {:>10}'.format('Iteration', 'Objective Value',
                                           'Time(s)')
    assert lines[1] == '[NeighborhoodComponentsAnalysis] {}'.format(header)
    assert lines[2] == ('[NeighborhoodComponentsAnalysis] {}'
                        .format('-' * len(header)))
    for line in lines[3:-2]:
        # The following regex will match for instance:
        # '[NeighborhoodComponentsAnalysis]  0    6.988936e+01   0.01'
        assert re.match(r'\[NeighborhoodComponentsAnalysis\] *\d+ *\d\.\d{6}e'
                        r'[+|-]\d+\ *\d+\.\d{2}', line)
    assert re.match(r'\[NeighborhoodComponentsAnalysis\] Training took\ *'
                    r'\d+\.\d{2}s\.', lines[-2])
    assert lines[-1] == ''


def test_no_verbose(capsys):
    # assert by default there is no output (verbose=0)
    nca = NeighborhoodComponentsAnalysis()
    nca.fit(iris_data, iris_target)
    out, _ = capsys.readouterr()
    # check output
    assert(out == '')


def test_singleton_class():
    X = iris_data
    y = iris_target

    # one singleton class
    singleton_class = 1
    ind_singleton, = np.where(y == singleton_class)
    y[ind_singleton] = 2
    y[ind_singleton[0]] = singleton_class

    nca = NeighborhoodComponentsAnalysis(max_iter=30)
    nca.fit(X, y)

    # One non-singleton class
    ind_1, = np.where(y == 1)
    ind_2, = np.where(y == 2)
    y[ind_1] = 0
    y[ind_1[0]] = 1
    y[ind_2] = 0
    y[ind_2[0]] = 2

    nca = NeighborhoodComponentsAnalysis(max_iter=30)
    nca.fit(X, y)

    # Only singleton classes
    ind_0, = np.where(y == 0)
    ind_1, = np.where(y == 1)
    ind_2, = np.where(y == 2)
    X = X[[ind_0[0], ind_1[0], ind_2[0]]]
    y = y[[ind_0[0], ind_1[0], ind_2[0]]]

    nca = NeighborhoodComponentsAnalysis(init='identity', max_iter=30)
    nca.fit(X, y)
    assert_array_equal(X, nca.transform(X))


def test_one_class():
    X = iris_data[iris_target == 0]
    y = iris_target[iris_target == 0]

    nca = NeighborhoodComponentsAnalysis(max_iter=30,
                                         n_components=X.shape[1],
                                         init='identity')
    nca.fit(X, y)
    assert_array_equal(X, nca.transform(X))


def test_callback(capsys):
    X = iris_data
    y = iris_target

    nca = NeighborhoodComponentsAnalysis(callback='my_cb')
    assert_raises(ValueError, nca.fit, X, y)

    max_iter = 10

    def my_cb(transformation, n_iter):
        rem_iter = max_iter - n_iter
        print('{} iterations remaining...'.format(rem_iter))

    # assert that my_cb is called
    nca = NeighborhoodComponentsAnalysis(max_iter=max_iter,
                                         callback=my_cb, verbose=1)
    nca.fit(iris_data, iris_target)
    out, _ = capsys.readouterr()

    # check output
    assert('{} iterations remaining...'.format(max_iter - 1) in out)


def test_store_opt_result():
    X = iris_data
    y = iris_target

    nca = NeighborhoodComponentsAnalysis(max_iter=5,
                                         store_opt_result=True)
    nca.fit(X, y)
    transformation = nca.opt_result_.x
    assert_equal(transformation.size, X.shape[1]**2)


def test_convergence_warning():
    nca = NeighborhoodComponentsAnalysis(max_iter=2, verbose=1)
    cls_name = nca.__class__.__name__
    assert_warns_message(ConvergenceWarning,
                         '[{}] NCA did not converge'.format(cls_name),
                         nca.fit, iris_data, iris_target)
