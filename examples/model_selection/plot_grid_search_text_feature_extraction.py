"""
==========================================================
Sample pipeline for text feature extraction and evaluation
==========================================================

The dataset used in this example is :ref:`20newsgroups_dataset` which will be
automatically downloaded, cached and reused for the document classification
example.

In this example we tune the hyperparameters of a particular classifier using a
:class:`~sklearn.model_selection.RandomizedSearchCV`. For a demo on the
performance of some other classifiers, see the
:ref:`sphx_glr_auto_examples_text_plot_document_classification_20newsgroups.py`
notebook.

"""

# Author: Olivier Grisel <olivier.grisel@ensta.org>
#         Peter Prettenhofer <peter.prettenhofer@gmail.com>
#         Mathieu Blondel <mathieu@mblondel.org>
#         Arturo Amor <david-arturo.amor-quiroz@inria.fr>
# License: BSD 3 clause

# %%
# Data loading
# ------------
# We load two categories from the training set. You can adjust the number of
# categories by adding their names to the list or setting `categories=None` in
# the dataset loader to get the 20 of them.

from sklearn.datasets import fetch_20newsgroups

categories = [
    "alt.atheism",
    "talk.religion.misc",
]

data_train = fetch_20newsgroups(
    subset="train",
    categories=categories,
    shuffle=True,
    random_state=42,
    remove=("headers", "footers", "quotes"),
)

data_test = fetch_20newsgroups(
    subset="test",
    categories=categories,
    shuffle=True,
    random_state=42,
    remove=("headers", "footers", "quotes"),
)

print(f"Loading 20 newsgroups dataset for {len(data_train.target_names)} categories:")
print(data_train.target_names)
print(f"{len(data_train.data)} documents")

# %%
# Pipeline with hyperparameter tuning
# -----------------------------------
# We define a pipeline combining a text feature vectorizer with a simple
# classifier.

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import ComplementNB
from sklearn.pipeline import Pipeline

pipeline = Pipeline(
    [
        ("vect", TfidfVectorizer()),
        ("clf", ComplementNB()),
    ]
)
pipeline

# %%
# We define a grid of hyperparameters to be explored by the
# :class:`~sklearn.model_selection.RandomizedSearchCV`. Using a
# :class:`~sklearn.model_selection.GridSearchCV` instead would explore all the
# possible combinations on the grid, which can be costly to compute, whereas the
# parameter `n_iter` of the :class:`~sklearn.model_selection.RandomizedSearchCV`
# controls the number of different random combination that are evaluated. Notice
# that setting `n_iter` larger than the number of possible combinations in a
# grid would lead to repeating already-explored combinations.

import numpy as np

parameters = {
    "vect__max_df": (0.2, 0.4, 0.6, 0.8, 1.0),
    "vect__min_df": (1, 3, 5, 10),
    "vect__ngram_range": ((1, 1), (1, 2)),  # unigrams or bigrams
    "vect__norm": ("l1", "l2"),
    "clf__alpha": np.logspace(-6, 6, 13),
}

# %%
# We search for the best parameters for both the feature extraction and the
# classifier. In this case `n_iter=40` is not an exhaustive search of the
# hyperparameter grid. In practice it would be interesting to increase the
# parameter `n_iter` to get a more informative analysis. The consequent increase
# in computing time can be handled by increasing the number of CPUs via the
# `n_jobs` parameter.

from pprint import pprint
from sklearn.model_selection import RandomizedSearchCV

random_search = RandomizedSearchCV(
    estimator=pipeline,
    param_distributions=parameters,
    n_iter=40,
    random_state=0,
    n_jobs=2,
    verbose=1,
)

print("Performing grid search...")
print("parameters:")
pprint(parameters)

# %%
from time import time

t0 = time()
random_search.fit(data_train.data, data_train.target)
print(f"done in {time() - t0:.3f}s")

# %%
print("Best parameters set:")
best_parameters = random_search.best_estimator_.get_params()
for param_name in sorted(parameters.keys()):
    print(f"{param_name}: {best_parameters[param_name]}")

# %%
test_accuracy = random_search.score(data_test.data, data_test.target)
print(
    "Accuracy of the best parameters using the inner CV of "
    f"the random search: {random_search.best_score_:.3f}"
)
print(f"Accuracy on test set: {test_accuracy:.3f}")

# %%
# The prefixes `vect` and `clf` are required to avoid possible ambiguities in
# the pipeline, but are not necessary for visualizing the results. Because of
# this, we define a function that will rename the tuned hyperparameters and
# improve the readability.

import pandas as pd


def shorten_param(param_name):
    if "__" in param_name:
        return param_name.rsplit("__", 1)[1]
    return param_name


cv_results = pd.DataFrame(random_search.cv_results_)
cv_results = cv_results.rename(shorten_param, axis=1)
# unigrams are mapped to index 1 and bigrams to index 2
cv_results["ngram_range"] = cv_results["ngram_range"].apply(lambda x: x[1])

# %%
# We can use a `plotly.express.scatter
# <https://plotly.com/python-api-reference/generated/plotly.express.scatter.html>`_
# to visualize the trade-off between scoring time and mean test score. Passing
# the cursor over a given point displays the corresponding parameters.

import plotly.express as px

param_names = [shorten_param(name) for name in parameters.keys()]
labels = {"mean_score_time": "score time (s)", "mean_test_score": "CV score"}
fig = px.scatter(
    cv_results,
    x="mean_score_time",
    y="mean_test_score",
    error_x="std_score_time",
    error_y="std_test_score",
    hover_data=param_names,
    labels=labels,
)
fig

# %%
# Notice that the cluster of models in the upper-left corner of the plot have
# the best trade-off between accuracy and scoring time. In this case, using
# bigrams increases the required scoring time without improving considerably the
# accuracy of the pipeline. For more information on how to customize an
# automated tuning to maximize score and minimize scoring time, see the example
# notebook
# :ref:`sphx_glr_auto_examples_model_selection_plot_grid_search_digits.py`.
#
# We can also use a `plotly.express.parallel_coordinates
# <https://plotly.com/python-api-reference/generated/plotly.express.parallel_coordinates.html>`_
# to further visualize the mean test score as a function of the tuned
# hyperparameters. This helps finding interactions between more than two
# hyperparameters and provide an intuition on the relevance they have for
# maximizing the performance of a pipeline.

import math

column_results = param_names + ["mean_test_score", "mean_score_time"]

transform_funcs = dict.fromkeys(column_results, lambda x: x)
transform_funcs["alpha"] = math.log10
transform_funcs["norm"] = lambda x: 2 if x == "l2" else 1

fig = px.parallel_coordinates(
    cv_results[column_results].apply(transform_funcs),
    color="mean_test_score",
    color_continuous_scale=px.colors.sequential.Viridis_r,
    labels=labels,
)
fig

# %%
# The parallel coordinates plot displays the values of the hyperparameters on
# different columns while the performance metric is color coded. It is possible
# to select a range of results by clicking and holding on any axis of the
# parallel coordinate plot. You can then slide (move) the range selection and
# cross two selections to see the intersections. You can undo a selection by
# clicking once again on the same axis.
#
# .. note:: We applied a `math.log10` transformation on the `alpha` axis to
#    spread the active range and improve the readability of the plot. A value
#    :math:`x` on said axis is to be understood as :math:`10^x`.
#
# In particular for this hyperparameter search, it is interesting to notice that
# the top performing models do not seem to depend on the regularization `norm`,
# but they do depend on a trade-off between `max_df`, `min_df` and the
# regularization strenght `alpha`. The reason is that including noisy features
# (i.e. `max_df` close to 1.0 or `min_df` close to 0) tend to overfit and
# therefore require a stronger regularization to compensate. Having less
# features require less regularization and less scoring time.
#
# The best accuracies are obtained when `alpha` is between :math:`10^{-6}` and
# :math:`10^0`, regardless of the hyperparameter `norm`.
