"""
=======================================================
Anomaly detection with Local Outlier Probability (LoOP)
=======================================================

This example presents the Local Outlier Probability (LoOP) estimator. The LoOP
algorithm is an unsupervised outlier detection method which computes the local
outlier probability of a given data point with respect to its neighbors.
Like LOF, it considers samples that have a substantially lower density than
their neighbors as having a higher probability of being an outlier but uses
the probabilistic density in this calculation.

The number of neighbors considered, (parameter n_neighbors) is typically
chosen 1) greater than the minimum number of objects a cluster has to contain,
so that other objects can be local outliers relative to this cluster, and 2)
smaller than the maximum number of close by objects that can potentially be
local outliers.

In practice, this information is generally not available, but taking
n_neighbors=20 appears to work well as a starting point for further exploration.
"""
print(__doc__)

import numpy as np
from matplotlib import pyplot as plt
from sklearn.neighbors import LocalOutlierProbability

np.random.seed(42)

# Generate train data
X = 0.3 * np.random.randn(100, 2)
# Generate some abnormal novel observations
X_outliers = np.random.uniform(low=-4, high=4, size=(20, 2))
X = np.r_[X + 2, X - 2, X_outliers]

# fit the model
clf = LocalOutlierProbability(n_neighbors=20)
y_pred = clf.fit_predict(X)
y_pred_outliers = y_pred[200:]

# plot the level sets of the decision function
xx, yy = np.meshgrid(np.linspace(-5, 5, 50), np.linspace(-5, 5, 50))
Z = clf._decision_function(np.c_[xx.ravel(), yy.ravel()])
Z = Z.reshape(xx.shape)

# plt.title("Local Outlier Probability (LoOP)")
# plt.contourf(xx, yy, Z, cmap=plt.cm.Blues_r)
#
# a = plt.scatter(X[:200, 0], X[:200, 1], c='white',
#                 edgecolor='k', s=20)
# b = plt.scatter(X[200:, 0], X[200:, 1], c='red',
#                 edgecolor='k', s=20)
# plt.axis('tight')
# plt.xlim((-5, 5))
# plt.ylim((-5, 5))
# plt.legend([a, b],
#            ["normal observations",
#             "abnormal observations"],
#            loc="upper left")
# plt.show()


import pandas as pd
from pydataset import data
iris = pd.DataFrame(data('iris'))
iris = pd.DataFrame(iris.drop('Species', 1))

clf = LocalOutlierProbability(n_neighbors=20)
clf.fit(iris)
# print(-clf.negative_local_outlier_probability_)
#
# import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D

iris['scores'] = -clf.negative_local_outlier_probability_

fig = plt.figure(figsize=(7, 7))
ax = fig.add_subplot(111, projection='3d')
ax.scatter(iris['Sepal.Width'], iris['Petal.Width'], iris['Sepal.Length'],
c=iris['scores'], cmap='seismic', s=50)
ax.set_xlabel('Sepal.Width')
ax.set_ylabel('Petal.Width')
ax.set_zlabel('Sepal.Length')
plt.show()
plt.clf()
plt.cla()
plt.close()


