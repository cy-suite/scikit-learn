"""
========================
Kernel PCA Approximation
========================

This example shows that using a limited number of components in Kernel PCA can
lead to a good approximation while being much faster to execute for large
datasets.
"""
from datetime import datetime

print(__doc__)

# Authors: Sylvain Marié
# License: BSD 3 clause

import numpy as np
import matplotlib.pyplot as plt

from sklearn.decomposition import KernelPCA
from sklearn.datasets import make_circles


# 1- Generate random data
# -----------------------
np.random.seed(0)
n_samples = 2000
X, y = make_circles(n_samples=n_samples, factor=.3, noise=.05)


# 2- Design experiment / Init plots
# ---------------------------------
grid_size = 5
n_components_range = [np.floor(np.exp((x / grid_size) * np.log(n_samples)))
                      for x in range(1, grid_size + 1)]
plt.figure(figsize=(15, 20))

# top left: original
nb_cols = 1 + len(n_components_range)
plt.subplot(2, nb_cols, 1, aspect='equal')
plt.title("Original space")
reds = y == 0
blues = y == 1
plt.scatter(X[reds, 0], X[reds, 1], c="red",
            s=20, edgecolor='k')
plt.scatter(X[blues, 0], X[blues, 1], c="blue",
            s=20, edgecolor='k')
plt.xlabel("$x_1$")
plt.ylabel("$x_2$")


# 2- Run experiments
# -----------------------
for i, n_compo in enumerate(n_components_range):
    print("Fitting kPCA for n_components=%i" % n_compo)

    try:
        start_time = datetime.now()
        kpca = KernelPCA(n_components=n_compo, kernel="rbf",
                         fit_inverse_transform=True, gamma=10)
        X_kpca = kpca.fit_transform(X)
        X_back = kpca.inverse_transform(X_kpca)
        elapsed = (datetime.now() - start_time).total_seconds()

        # original space after inverse transform
        plt.subplot(2, nb_cols, i + 2, aspect='equal')
        plt.scatter(X_back[reds, 0], X_back[reds, 1], c="red",
                    s=20, edgecolor='k')
        plt.scatter(X_back[blues, 0], X_back[blues, 1], c="blue",
                    s=20, edgecolor='k')
        plt.title("kPCA approx (n=%i)(%.2fs)" % (n_compo, elapsed))
        plt.xlabel("$x_1$")
        plt.ylabel("$x_2$")

        # plot the first two principal components
        plt.subplot(2, nb_cols, i + 2 + nb_cols, aspect='equal')
        plt.scatter(X_kpca[reds, 0], X_kpca[reds, 1], c="red",
                    s=20, edgecolor='k')
        plt.scatter(X_kpca[blues, 0], X_kpca[blues, 1], c="blue",
                    s=20, edgecolor='k')
        plt.title("First 2PC (n=%i)" % n_compo)
        plt.xlabel("1st PC in space induced by $\phi$")
        plt.ylabel("2nd component")
    except Exception as e:
        print(e)

plt.subplots_adjust(0.02, 0.10, 0.98, 0.94, 0.04, 0.35)
plt.show()
