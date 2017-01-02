"""
================
Precision-Recall
================

Example of Precision-Recall metric to evaluate classifier output quality.

In information retrieval, precision is a measure of result relevancy, while
recall is a measure of how many truly relevant results are returned. A high
area under the curve represents both high recall and high precision, where high
precision relates to a low false positive rate, and high recall relates to a
low false negative rate. High scores for both show that the classifier is
returning accurate results (high precision), as well as returning a majority of
all positive results (high recall).

A system with high recall but low precision returns many results, but most of
its predicted labels are incorrect when compared to the training labels. A
system with high precision but low recall is just the opposite, returning very
few results, but most of its predicted labels are correct when compared to the
training labels. An ideal system with high precision and high recall will
return many results, with all results labeled correctly.

Precision (:math:`P`) is defined as the number of true positives (:math:`T_p`)
over the number of true positives plus the number of false positives
(:math:`F_p`).

:math:`P = \\frac{T_p}{T_p+F_p}`

Recall (:math:`R`) is defined as the number of true positives (:math:`T_p`)
over the number of true positives plus the number of false negatives
(:math:`F_n`).

:math:`R = \\frac{T_p}{T_p + F_n}`

These quantities are also related to the (:math:`F_1`) score, which is defined
as the harmonic mean of precision and recall.

:math:`F1 = 2\\frac{P \\times R}{P+R}`

It is important to note that the precision may not decrease with recall. The
definition of precision (:math:`\\frac{T_p}{T_p + F_p}`) shows that lowering
the threshold of a classifier may increase the denominator, by increasing the
number of results returned. If the threshold was previously set too high, the
new results may all be true positives, which will increase precision. If the
previous threshold was about right or too low, further lowering the threshold
will introduce false positives, decreasing precision.

Recall is defined as :math:`\\frac{T_p}{T_p+F_n}`, where :math:`T_p+F_n` does
not depend on the classifier threshold. This means that lowering the classifier
threshold may increase recall, by increasing the number of true positive
results. It is also possible that lowering the threshold may leave recall
unchanged, while the precision fluctuates.

The relationship between recall and precision can be observed in the
stairstep area of the plot - at the edges of these steps a small change
in the threshold considerably reduces precision, with only a minor gain in
recall.

**Average precision** summarizes such a plot as the weighted mean of precisions
achieved at each threshold, with the increase in recall from the previous
threshold used as the weight:

:math:`\\text{AP} = \\sum_n (R_n - R_{n-1}) P_n`

where :math:`P_n` and :math:`R_n` are the precision and recall at the
:math:`n`th threshold. A pair :math:`(R_k, P_k)` is referred to as an
*operating point*.

In *interpolated* average precision, a set of desired recall values is
specified and for each desired value, we select the first operating point
that corresponds to a recall greater than or equal to it. The interpolated
average precision is the mean of the precisions of these operating points.
The most common choice is 'eleven point' interpolated precision, where the
desired recall values are [0, 0.1, 0.2, ..., 1.0]. This is the metric used in
`The PASCAL Visual Object Classes (VOC) Challenge <http://citeseerx.ist.psu.edu
/viewdoc/download?doi=10.1.1.157.5766&rep=rep1&type=pdf>`_. In the example
below, the eleven precision values are circled. Note that it's possible that
the same operating point might correspond to multiple desired recall values.

Precision-recall curves are typically used in binary classification to study
the output of a classifier. In order to extend the Precision-recall curve and
average precision to multi-class or multi-label classification, it is necessary
to binarize the output. One curve can be drawn per label, but one can also draw
a precision-recall curve by considering each element of the label indicator
matrix as a binary prediction (micro-averaging).

.. note::

    See also :func:`sklearn.metrics.average_precision_score`,
             :func:`sklearn.metrics.recall_score`,
             :func:`sklearn.metrics.precision_score`,
             :func:`sklearn.metrics.f1_score`
"""
print(__doc__)

import matplotlib.pyplot as plt
import numpy as np
from sklearn import svm, datasets
from sklearn.metrics import precision_recall_curve
from sklearn.metrics import average_precision_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import label_binarize
from sklearn.multiclass import OneVsRestClassifier

# import some data to play with
iris = datasets.load_iris()
X = iris.data
y = iris.target

# Binarize the output
y = label_binarize(y, classes=[0, 1, 2])
n_classes = y.shape[1]

# Add noisy features
random_state = np.random.RandomState(0)
n_samples, n_features = X.shape
X = np.c_[X, random_state.randn(n_samples, 200 * n_features)]

# Split into training and test
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=.5,
                                                    random_state=random_state)

# Run classifier
classifier = OneVsRestClassifier(svm.SVC(kernel='linear', probability=True,
                                 random_state=random_state))
y_score = classifier.fit(X_train, y_train).decision_function(X_test)


def reversed_precision_recall_curve(y_true, y_score):
    """Helper function to return precision, recall and thresholds
    in reverse order"""
    p, r, t = precision_recall_curve(y_true, y_score)
    return p[::-1], r[::-1], t[::-1]


def get_circle_coords(p, r):
    """Get coordinates of operating points chosen for 11-point interpolated
    average precision"""
    recall_circles = list()
    precision_circles = list()
    for threshold in np.arange(0, 1.1, 0.1):
        i = sum(r[1:] >= threshold)
        recall_circles.append(r[-i])
        precision_circles.append(p[-i])
    return recall_circles, precision_circles


def fill_beneath_step(x, y, color, alpha=0.2):
    """Fill an area underneath a step function"""
    x_long = [v for v in x for _ in (0, 1)][:-1]
    y_long = [v for v in y for _ in (0, 1)][1:]
    plt.fill_between(x_long, 0, y_long, alpha=alpha, color=color)


# Compute Precision-Recall, average precision and eleven-point interpolated
# average precision
precision = dict()
recall = dict()
average_precision = dict()
interpolated_average_precision = dict()
for i in range(n_classes):
    precision[i], recall[i], _ = reversed_precision_recall_curve(y_test[:, i],
                                                        y_score[:, i])
    average_precision[i] = average_precision_score(y_test[:, i], y_score[:, i])
    interpolated_average_precision[i] = average_precision_score(
        y_test[:, i], y_score[:, i], interpolation='eleven_point')

# Compute micro-average Precision-Recall curve and average precision
precision["micro"], recall["micro"], thresholds = \
    reversed_precision_recall_curve(y_test.ravel(), y_score.ravel())
average_precision["micro"] = average_precision_score(y_test, y_score,
                                                     average="micro")


# Plot micro-average Precision-Recall curve
plt.clf()
plt.step(recall["micro"], precision["micro"], label='Precision-Recall curve')
fill_beneath_step(recall["micro"], precision["micro"], color='b')
plt.xlabel('Recall')
plt.ylabel('Precision')
plt.ylim([0.0, 1.05])
plt.xlim([0.0, 1.0])
plt.title('Precision-Recall example: AUC={0:0.2f}'.format(
        average_precision["micro"]))
plt.legend(loc="lower left")
plt.show()

# Plot Precision-Recall curves for each class
plt.figure(figsize=(12, 10))
plt.clf()
colors = ['r', 'b', 'g']
eleven_point_precisions = dict()
for i in range(n_classes):
    plt.step(recall[i], precision[i], color=colors[i],
             label='Precision-recall curve of class {0} (area = {1:0.2f})'
                   ''.format(i, average_precision[i]))
    p_long = [v for v in precision[i] for _ in (0, 1)][1:]
    r_long = [v for v in recall[i] for _ in (0, 1)][:-1]
    c_r, c_p = get_circle_coords(precision[i], recall[i])
    eleven_point_precisions[i] = c_p
    for this_r, this_p in zip(c_r, c_p):
        t = plt.text(this_r + 0.0075, this_p + 0.01, "{:3.3f}".format(this_p),
                     color=colors[i])

    plt.scatter(c_r, c_p, marker='o', s=100, facecolor='none',
                edgecolor=colors[i],
                label='Eleven point interpolated precisions of class {0} '
                      '(mean = {1:0.2f})'.format(
                        i, interpolated_average_precision[i]))
    fill_beneath_step(recall[i], precision[i], colors[i])
plt.xlim([0.0, 1.0])
plt.ylim([0.0, 1.05])
plt.xlabel('Recall')
plt.ylabel('Precision')
plt.title('Extension of Precision-Recall curve to multi-class')
plt.legend(loc="lower right")
plt.show()
