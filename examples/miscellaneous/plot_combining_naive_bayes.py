"""
===================================================
Combining Naive Bayes Estimators using ColumnwiseNB
===================================================

.. currentmodule:: sklearn

This example shows how to use :class:`~naive_bayes.ColumnwiseNB`
meta-estimator to construct a naive Bayes model from base naive Bayes
estimators. The resulting model is applied to a dataset with a mixture of
discrete and continuous features.

We consider the titanic dataset, in which:

- numerical (continous) features "age" and "fare" are handled by
  :class:`~naive_bayes.GaussianNB`;
- categorical (discrete) features "embarked", "sex", and "pclass" are handled
  by :class:`~naive_bayes.CategoricalNB`.
"""

# Author: Andrey V. Melnik <andrey.melnik.maths@gmail.com>
#         Pedro Morales <part.morales@gmail.com>
#
# License: BSD 3 clause

# %%
import pandas as pd

from sklearn import set_config
from sklearn.datasets import fetch_openml

set_config(transform_output="pandas")

X, y = fetch_openml(
    "titanic", version=1, as_frame=True, return_X_y=True, n_retries=10, parser="auto"
)
X["pclass"] = X["pclass"].astype("category")
# Add a category for NaNs to the "embarked" feature:
X["embarked"] = X["embarked"].cat.add_categories("N/A").fillna("N/A")

# %%
# Build and use a pipeline around ``ColumnwiseNB``
# ------------------------------------------------

from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import accuracy_score
from sklearn.model_selection import GridSearchCV, train_test_split
from sklearn.naive_bayes import CategoricalNB, ColumnwiseNB, GaussianNB
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder

numeric_features = ["age", "fare"]
numeric_transformer = SimpleImputer(strategy="median")

categorical_features = ["embarked", "sex", "pclass"]
categories = [X[c].unique().to_list() for c in X[categorical_features]]
categorical_transformer = OrdinalEncoder(categories=categories)

preprocessor = ColumnTransformer(
    transformers=[
        ("num", numeric_transformer, numeric_features),
        ("cat", categorical_transformer, categorical_features),
    ],
    verbose_feature_names_out=False,
)

classifier = ColumnwiseNB(
    estimators=[
        ("gnb", GaussianNB(), numeric_features),
        ("cnb", CategoricalNB(), categorical_features),
    ]
)

pipe = Pipeline(steps=[("preprocessor", preprocessor), ("classifier", classifier)])
pipe
# %%
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=0)

pipe.fit(X_train, y_train)
y_pred = pipe.predict(X_test)
print(f"Test accuracy: {accuracy_score(y_test, y_pred)}")

# %%
# Compare choices of columns using ``GridSearchCV``
# --------------------------------------------------
#
# The allocation of columns to constituent subestimators can be regarded as a
# hyperparameter. We can explore the combinations of columns' choices and values
# of other hyperparameters with the help of :class:`~.model_selection.GridSearchCV`.

param_grid = {
    "classifier__estimators": [
        [
            ("gnb", GaussianNB(), ["age", "fare"]),
            ("cnb", CategoricalNB(), categorical_features),
        ],
        [("gnb", GaussianNB(), []), ("cnb", CategoricalNB(), ["pclass"])],
        [("gnb", GaussianNB(), ["embarked"]), ("cnb", CategoricalNB(), [])],
    ],
    "preprocessor__num__strategy": ["mean", "most_frequent"],
}

grid_search = GridSearchCV(pipe, param_grid, cv=10)
grid_search

# %%
# Calling `fit` triggers the cross-validated search for the best
# hyperparameters combination:

grid_search.fit(X_train, y_train)

print("Best params:")
print(grid_search.best_params_)

# %%
# As it turns out, the best results are achieved by the naive Bayes model when "sex"
# is the only feature used:

cv_results = pd.DataFrame(grid_search.cv_results_)
cv_results = cv_results.sort_values("mean_test_score", ascending=False)
cv_results["Columns dictionary"] = cv_results["param_classifier__estimators"].map(
    lambda l: {e[0]: e[-1] for e in l}
)
cv_results["'gnb' columns"] = cv_results["Columns dictionary"].map(lambda d: d["gnb"])
cv_results["'cnb' columns"] = cv_results["Columns dictionary"].map(lambda d: d["cnb"])
cv_results[
    [
        "mean_test_score",
        "std_test_score",
        "param_preprocessor__num__strategy",
        "'gnb' columns",
        "'cnb' columns",
    ]
]
