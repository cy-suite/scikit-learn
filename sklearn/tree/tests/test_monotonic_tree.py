import numpy as np
import pytest
from sklearn import datasets
from sklearn.tree import DecisionTreeRegressor
from sklearn.tree.tests.test_tree import REG_TREES, CLF_TREES


@pytest.mark.parametrize('seed', range(4))
@pytest.mark.parametrize('depth_first', (True, False))
def test_montonic_constraints(seed, depth_first):
    n_samples = 1000
    n_samples_train = 900
    X, y = datasets.make_hastie_10_2(n_samples=n_samples, random_state=0)
    train = np.arange(n_samples_train)
    test = np.arange(n_samples_train, n_samples)
    X_train = X[train]
    y_train = y[train]
    X_test = np.copy(X[test])

    X_test_incr = np.copy(X_test)
    X_test_decr = np.copy(X_test)
    X_test_incr[:, 0] += 10
    X_test_decr[:, 1] += 10
    monotonic_cst = np.zeros(X.shape[1])
    monotonic_cst[0] = 1
    monotonic_cst[1] = -1

    for name, TreeRegressor in REG_TREES.items():
        if depth_first:
            est = TreeRegressor(max_depth=None, monotonic_cst=monotonic_cst)
        else:
            est = TreeRegressor(max_depth=None, monotonic_cst=monotonic_cst,
                                max_leaf_nodes=n_samples_train)
        if hasattr(est, "random_state"):
            est.set_params(**{"random_state": seed})
        est.fit(X_train, y_train)
        y = est.predict(X_test)
        # increasing constraint
        y_incr = est.predict(X_test_incr)
        # y_incr should always be greater than y
        assert np.all(y_incr >= y)

        # decreasing constraint
        y_decr = est.predict(X_test_decr)
        # y_decr should always be lower than y
        assert np.all(y_decr <= y)

    for name, TreeClassifier in CLF_TREES.items():
        if depth_first:
            est = TreeClassifier(max_depth=None, monotonic_cst=monotonic_cst)
        else:
            est = TreeClassifier(max_depth=None, monotonic_cst=monotonic_cst,
                                 max_leaf_nodes=n_samples_train)
        if hasattr(est, "random_state"):
            est.set_params(**{"random_state": seed})
        est.fit(X_train, y_train)
        y = est.predict_proba(X_test)[:, 0]

        # increasing constraint
        y_incr = est.predict_proba(X_test_incr)[:, 0]
        # y_incr should always be greater than y
        assert np.all(y_incr >= y)

        # decreasing constraint
        y_decr = est.predict_proba(X_test_decr)[:, 0]
        # y_decr should always be lower than y
        assert np.all(y_decr <= y)


def test_multiclass_raises():
    X, y = datasets.make_hastie_10_2(n_samples=100, random_state=0)
    y[0] = 0
    monotonic_cst = np.zeros(X.shape[1])
    monotonic_cst[0] = -1
    monotonic_cst[1] = 1
    for name, TreeClassifier in CLF_TREES.items():
        est = TreeClassifier(max_depth=None, monotonic_cst=monotonic_cst,
                             random_state=0)
        if hasattr(est, "random_state"):
            est.set_params(**{"random_state": 0})

        msg = "Monotonic constraints are not supported with multiclass " \
              "classification"
        with pytest.raises(ValueError, match=msg):
            est.fit(X, y)


def assert_1d_reg_tree_children_monotonic_bounded(tree_, monotonic_sign):
    # Flip values to always check for increasing constraint
    values = monotonic_sign * tree_.value
    for i in range(tree_.node_count):
        if tree_.children_left[i] > i and tree_.children_right[i] > i:
            # Check monotonicity on children
            i_left = tree_.children_left[i]
            i_right = tree_.children_right[i]
            assert values[i_left] <= values[i_right]
            val_middle = values[i]
            # Check bounds on grand-children, filtering out leaf nodes
            if tree_.feature[i_left] >= 0:
                i_left_right = tree_.children_right[i_left]
                assert values[i_left_right] <= val_middle
            if tree_.feature[i_right] >= 0:
                i_right_left = tree_.children_left[i_right]
                assert val_middle <= values[i_right_left]


def assert_1d_reg_monotonic(clf, monotonic_sign, min_x, max_x, n_steps):
    X_grid = np.linspace(min_x, max_x, n_steps).reshape(-1, 1)
    y_pred_grid = clf.predict(X_grid)
    assert (monotonic_sign * np.diff(y_pred_grid) >= 0.0).all()


@pytest.mark.parametrize('monotonic_sign', (-1, 1))
@pytest.mark.parametrize('splitter', ("best", "random"))
@pytest.mark.parametrize('depth_first', (True, False))
@pytest.mark.parametrize('seed', range(4))
def test_1d_tree_nodes_values(monotonic_sign, splitter, depth_first, seed):
    # Adaptation from test_nodes_values in test_montonic_constraints.py
    # Build a single tree with only one feature, and make sure the nodes
    # values respect the monotonic constraints.

    # Considering the following tree with a monotonic POS constraint, we
    # should have:
    #
    #       root
    #      /    \
    #     a      b
    #    / \    / \
    #   c   d  e   f
    #
    # c <= d <= root <= e <= f

    rng = np.random.RandomState(seed)
    n_samples = 1000
    n_features = 1
    X = rng.rand(n_samples, n_features)
    y = rng.rand(n_samples)

    if depth_first:
        # No max_leaf_nodes, default depth first tree builder
        clf = DecisionTreeRegressor(splitter=splitter,
                                    monotonic_cst=[monotonic_sign],
                                    random_state=seed)
    else:
        # max_leaf_nodes triggers best first tree builder
        clf = DecisionTreeRegressor(splitter=splitter,
                                    monotonic_cst=[monotonic_sign],
                                    max_leaf_nodes=n_samples,
                                    random_state=seed)
    clf.fit(X, y)

    assert_1d_reg_tree_children_monotonic_bounded(clf.tree_, monotonic_sign)
    assert_1d_reg_monotonic(clf, monotonic_sign, np.min(X), np.max(X), 100)


def assert_nd_reg_tree_children_monotonic_bounded(tree_, monotonic_cst):
    upper_bound = np.full(tree_.node_count, np.inf)
    lower_bound = np.full(tree_.node_count, -np.inf)
    for i in range(tree_.node_count):
        feature = tree_.feature[i]
        assert tree_.value[i] <= upper_bound[i]
        assert tree_.value[i] >= lower_bound[i]
        if feature < 0:
            # leaf: nothing to do
            continue
        else:
            i_left = tree_.children_left[i]
            i_right = tree_.children_right[i]
            if monotonic_cst[feature] == 0:
                # unconstrained feature: propagate bounds down the tree
                upper_bound[i_left] = upper_bound[i]
                lower_bound[i_left] = lower_bound[i]
                upper_bound[i_right] = upper_bound[i]
                lower_bound[i_right] = lower_bound[i]
            else:
                # constrained feature
                # check montonicity
                assert monotonic_cst[feature] * tree_.value[i_left] \
                       <= monotonic_cst[feature] * tree_.value[i_right]
                # update and propagate bounds down the tree
                if monotonic_cst[feature] == 1:
                    upper_bound[i_left] = tree_.value[i]
                    lower_bound[i_left] = lower_bound[i]
                    upper_bound[i_right] = upper_bound[i]
                    lower_bound[i_right] = tree_.value[i]
                else:
                    upper_bound[i_left] = upper_bound[i]
                    lower_bound[i_left] = tree_.value[i]
                    upper_bound[i_right] = tree_.value[i]
                    lower_bound[i_right] = lower_bound[i]


@pytest.mark.parametrize('monotonic_sign', (-1, 1))
@pytest.mark.parametrize('splitter', ("best", "random"))
@pytest.mark.parametrize('depth_first', (True, False))
@pytest.mark.parametrize('seed', range(4))
def test_nd_tree_nodes_values(monotonic_sign, splitter, depth_first, seed):
    # Build tree with several features, and make sure the nodes
    # values respect the monotonic constraints.

    # Considering the following tree with a monotonic POS constraint on X[0],
    # we should have:
    #
    #            root
    #           X[0]<=t
    #          /       \
    #         a         b
    #     X[0]<=u   X[1]<=v
    #    /       \   /     \
    #   c        d  e       f
    #
    # i)   a <= root <= b
    # ii)  c <= a <= d <= root
    # iii) root <= min(e,f)
    # For iii) we check that each node value is within the proper lower and
    # upper bounds.

    rng = np.random.RandomState(seed)
    n_samples = 10000
    n_features = 2
    monotonic_cst = [monotonic_sign, 0]
    X = rng.rand(n_samples, n_features)
    y = rng.rand(n_samples)

    if depth_first:
        # No max_leaf_nodes, default depth first tree builder
        clf = DecisionTreeRegressor(splitter=splitter,
                                    monotonic_cst=monotonic_cst,
                                    random_state=seed)
    else:
        # max_leaf_nodes triggers best first tree builder
        clf = DecisionTreeRegressor(splitter=splitter,
                                    monotonic_cst=monotonic_cst,
                                    max_leaf_nodes=n_samples,
                                    random_state=seed)
    clf.fit(X, y)
    assert_nd_reg_tree_children_monotonic_bounded(clf.tree_, monotonic_cst)
