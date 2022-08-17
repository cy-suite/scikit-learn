"""
==================================================
Multiclass Receiver Operating Characteristic (ROC)
==================================================

Example of Receiver Operating Characteristic (ROC) metric to evaluate multiclass
classifiers quality.

ROC curves typically feature true positive rate on the Y axis, and false
positive rate on the X axis. This means that the top left corner of the plot is
the "ideal" point - a false positive rate of zero, and a true positive rate of
one. This is not very realistic, but it does mean that a larger area under the
curve (AUC) is usually better.

The "steepness" of ROC curves is also important, since it is ideal to maximize
the true positive rate while minimizing the false positive rate.

ROC curves are typically used in binary classification to study the output of a
classifier. In order to extend ROC curve and ROC area to multi-label
classification, it is necessary to binarize the output. One ROC curve can be
drawn per label, but one can also draw a ROC curve by considering each element
of the label indicator matrix as a binary prediction (micro-averaging).

Another evaluation measure for multi-label classification is macro-averaging,
which gives equal weight to the classification of each label.

.. note::

    See :ref:`sphx_glr_auto_examples_model_selection_plot_roc_crossval.py` for
    an extension of the present example estimating the variance of the ROC
    curves and their respective AUC.

"""

# %%
# Load and prepare data
# =====================
#
# We import the :ref:`iris_dataset` which contains 3 classes, each one
# corresponding to a type of iris plant. One class is linearly separable from
# the other 2; the latter are NOT linearly separable from each other.
#
# Here we binarize the output and add noisy features to make the problem harder.

import numpy as np
from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import label_binarize

(X, y) = load_iris(return_X_y=True)
target_names = load_iris()["target_names"]

random_state = np.random.RandomState(0)
n_samples, n_features = X.shape
n_classes = len(np.unique(y))
X = np.c_[X, random_state.randn(n_samples, 200 * n_features)]
(
    X_train,
    X_test,
    y_train,
    y_test,
) = train_test_split(X, y, test_size=0.5, stratify=y, random_state=0)

# %%
# We train a linear classifier that can naturaly handle multiclass problems.

from sklearn.linear_model import LogisticRegression

classifier = LogisticRegression()
y_score = classifier.fit(X_train, y_train).predict_proba(X_test)


# %%
# ROC curves are typically defined in binary classification, where the
# true/false positive rates can be defined unambiguosly. In the case of
# multiclass classifcation, a notion of true/false positive rates is obtained
# after "binarizing" the problem. This can be done in 2 different ways:
#
# - the One-vs-Rest scheme compares each class against all the others (assumed
#   as one);
# - the One-vs-One scheme compares every unique pairwise combination of classes.
#
# One-vs-Rest multiclass ROC
# ==========================
#
# The One-vs-the-Rest (OvR) multiclass strategy, also known as one-vs-all,
# consists in fitting one classifier per class. For each classifier, the class
# is fitted against all the other classes.
#
# ROC curve showing a specific class
# ----------------------------------
#
# In the following plot we show the resulting ROC curve when regarding the iris
# flowers as either "virginica" (`class_id=2`) or "non-virginica" (the rest).

import matplotlib.pyplot as plt
from sklearn.metrics import RocCurveDisplay

class_id = 2

y_onehot_test = label_binarize(y_test, classes=[0, 1, 2])

RocCurveDisplay.from_predictions(
    y_onehot_test[:, class_id],
    y_score[:, class_id],
    name=f"ROC curve for {target_names[class_id]} vs the rest",
    color="darkorange",
)
plt.plot([0, 1], [0, 1], "k--", label="ROC curve for chance level")
plt.title(f"One-vs-Rest ROC for class label {class_id}")
plt.show()

# %%
# ROC curve showing the "micro-average" of the 3 classes
# ------------------------------------------------------
#
# The micro-average aggregates the contributions from all the classes (using
# `.ravel`) to compute the average metric. In a multi-class classification
# setup, micro-average is preferable if you suspect there might be class
# imbalance.

RocCurveDisplay.from_predictions(
    y_onehot_test.ravel(),
    y_score.ravel(),
    name="One-vs-Rest ROC micro-averaged",
    color="darkorange",
)
plt.plot([0, 1], [0, 1], "k--", label="ROC curve for chance level")
plt.title("Receiver operating characteristic (micro-averaged)")
plt.show()

# %%
# In the case where the main interest is not the plot but the ROC-AUC score
# itself, we can reproduce the value shown in the plot using
# :class:`~sklearn.metrics.roc_auc_score`.

from sklearn.metrics import roc_auc_score

micro_roc_auc_ovr = roc_auc_score(
    y_onehot_test,
    y_score,
    average="micro",
)

print(f"Micro-averaged One-vs-Rest ROC AUC score:\n{micro_roc_auc_ovr:.2f}")

# %%
# This is equivalent to computing the ROC curve with
# :class:`~sklearn.metrics.roc_curve` and then the area under the curve with
# :class:`~sklearn.metrics.auc` for the raveled classes.

from sklearn.metrics import roc_curve, auc

fpr = dict()
tpr = dict()
roc_auc = dict()

# Compute micro-average ROC curve and ROC area
fpr["micro"], tpr["micro"], _ = roc_curve(y_onehot_test.ravel(), y_score.ravel())
roc_auc["micro"] = auc(fpr["micro"], tpr["micro"])

print(f"Micro-averaged One-vs-Rest ROC AUC score:\n{roc_auc['micro']:.2f}")

# %%
# Notice that by default, the computation of the ROC curve adds a single point
# at the maximal false positive rate by using linear interpolation and `McClish
# correction <https://pubmed.ncbi.nlm.nih.gov/2668680/>`_.
#
# ROC curve showing the "macro-average" of the 3 classes
# ------------------------------------------------------
#
# Obtaining the macro-average requires computing the metric independently for
# each class and then taking the average over them, hence treating all classes
# equally a priori. We first aggregate the true/false positive rates per class:

for i in range(n_classes):
    fpr[i], tpr[i], _ = roc_curve(y_onehot_test[:, i], y_score[:, i])
    roc_auc[i] = auc(fpr[i], tpr[i])

fpr_grid = np.linspace(0.0, 1.0, 1000)

# Interpolate all ROC curves at this points
mean_tpr = np.zeros_like(fpr_grid)
for i in range(n_classes):
    mean_tpr += np.interp(fpr_grid, fpr[i], tpr[i])

# Average it and compute AUC
mean_tpr /= n_classes

fpr["macro"] = fpr_grid
tpr["macro"] = mean_tpr
roc_auc["macro"] = auc(fpr["macro"], tpr["macro"])

print(f"Macro-averaged One-vs-Rest ROC AUC score:\n{roc_auc['macro']:.2f}")

# %%
# This computation is equivalent to simply calling

micro_roc_auc_ovr = roc_auc_score(y_onehot_test, y_score, average="macro")

print(f"Macro-averaged One-vs-Rest ROC AUC score:\n{micro_roc_auc_ovr:.2f}")

# %%
# Plot all OvR ROC curves together
# --------------------------------

from itertools import cycle

fig, ax = plt.subplots()

plt.plot(
    fpr["micro"],
    tpr["micro"],
    label=f"micro-average ROC curve (area = {roc_auc['micro']:.2f})",
    color="deeppink",
    linestyle=":",
    linewidth=4,
)

plt.plot(
    fpr["macro"],
    tpr["macro"],
    label=f"macro-average ROC curve (area = {roc_auc['macro']:.2f})",
    color="navy",
    linestyle=":",
    linewidth=4,
)

colors = cycle(["aqua", "darkorange", "cornflowerblue"])
for class_id, color in zip(range(n_classes), colors):
    RocCurveDisplay.from_predictions(
        y_onehot_test[:, class_id],
        y_score[:, class_id],
        name=f"ROC curve for {target_names[class_id]}",
        color=color,
        ax=ax,
    )

plt.plot([0, 1], [0, 1], "k--", label="ROC curve for chance level")
plt.xlim([0.0, 1.0])
plt.ylim([0.0, 1.05])
plt.xlabel("False Positive Rate")
plt.ylabel("True Positive Rate")
plt.title("Some extension of Receiver operating characteristic to multiclass")
plt.legend(loc="lower right")
plt.show()

# %%
# One-vs-One multiclass ROC
# =========================
#
# The One-vs-One (OvO) multiclass strategy consists in fitting one classifier
# per class pair. Since it requires to fit `n_classes` * (`n_classes` - 1) / 2
# classifiers, this method is usually slower than One-vs-Rest due to its
# O(`n_classes`^2) complexity.
#
# In this section, we demonstrate the macro-averaged AUC using the OvO scheme
# for the 3 posible combinations in the :ref:`iris_dataset`: "setosa" vs
# "versicolor", "versicolor" vs "virginica" and  "virginica" vs "setosa". Notice
# that micro-averaging is not defined for the OvO scheme.

pair_list = [[0, 1], [1, 2], [0, 2]]
ovo_fpr = dict()
ovo_tpr = dict()
ovo_roc_auc = dict()

fig, ax = plt.subplots()

for i, (idx_1, idx_2) in enumerate(pair_list):
    mask_train = np.isin(y_train, [idx_1, idx_2])
    mask_test = np.isin(y_test, [idx_1, idx_2])

    y_score_ovo = classifier.fit(
        X_train[mask_train], y_train[mask_train]
    ).predict_proba(X_test[mask_test])

    ovo_fpr[i], ovo_tpr[i], _ = roc_curve(
        y_test[mask_test], y_score_ovo[:, 1], pos_label=idx_2
    )
    ovo_roc_auc[i] = auc(fpr[i], tpr[i])

    RocCurveDisplay.from_predictions(
        y_test[mask_test],
        y_score_ovo[:, 1],
        pos_label=idx_2,
        name=f"ROC curve for {target_names[idx_1]} vs {target_names[idx_2]}",
        ax=ax,
    )

# compute macro-average by hand
mean_tpr = np.zeros_like(fpr_grid)
for i in range(n_classes):
    mean_tpr += np.interp(fpr_grid, ovo_fpr[i], ovo_tpr[i])
mean_tpr /= n_classes
ovo_fpr["macro"] = fpr_grid
ovo_tpr["macro"] = mean_tpr
ovo_roc_auc["macro"] = auc(ovo_fpr["macro"], ovo_tpr["macro"])

plt.plot(
    ovo_fpr["macro"],
    ovo_tpr["macro"],
    label=f"One-vs-One macro-average ROC curve (area = {ovo_roc_auc['macro']:.2f})",
    color="navy",
    linestyle=":",
    linewidth=4,
)
plt.show()

# %%
# We confirm that the clases "versicolor" and "virginica" are not well
# identified by a linear classifier. One can also assert that the macro-average
# we computed "by hand" is equivalent to the implemented `average="macro"`
# option of the :class:`~sklearn.metrics.roc_auc_score` function.

macro_roc_auc_ovo = roc_auc_score(y_test, y_score, multi_class="ovo", average="macro")

print(f"One-vs-One ROC AUC scores:\n{macro_roc_auc_ovo:.5f}")

# %%
# Notice that the "virginica"-vs-the-rest ROC-AUC score (0.77) is between the
# OvO ROC-AUC scores for "versicolor" vs "virginica" (0.65) and "setosa" vs
# "virginica" (0.93). Indeed, the OvO strategy is more informative to understand
# the overlap between classes, at the expense of computational cost.
#
# The OvO strategy is recomended if the user is mainly interested in correctly
# identifying a given class or subset of classes, whereas evaluating the global
# performance of a classifier can be correctly resumed by a given averaging
# strategy.
