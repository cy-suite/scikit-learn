"""
=========================================
Kernel PCA Solvers comparison benchmark 2
=========================================

This example shows that the approximate solvers provided in Kernel PCA can help
drastically improve its execution speed when an approximate solution (small
`n_components`) is acceptable. In many real-world datasets a few hundreds of
principal components are indeed sufficient enough to capture the underlying
distribution.

Description:
------------
An increasing number of examples is used to train a KernelPCA, between
`min_n_samples` (default: 101) and `max_n_samples` (default: 3000) with
`n_samples_grid_size` positions (default: 3). For each training sample size,
KernelPCA models are trained for the various possible `eigen_solver` values.
All of them are trained to obtain 100 principal components (default: 100).
The execution times are displayed in a plot at the end of the experiment.

What you can observe:
---------------------
When the number of samples provided gets large, the dense solver takes a lot
of time to complete, while the randomized method returns similar results in
much shorter execution times.

Going further:
--------------
You can increase `max_n_samples` and `nb_n_samples_to_try` if you wish to
explore a wider range of values for `n_samples`.

You can also set `include_arpack=True` to add this other solver in the
experiments.
"""
print(__doc__)

# Authors: Sylvain MARIE
# License: BSD 3 clause

from datetime import datetime

import numpy as np
import matplotlib.pyplot as plt

from sklearn.utils.testing import assert_array_almost_equal
from sklearn.decomposition import KernelPCA
from sklearn.datasets import make_circles


# 1- Design the Experiment
# ------------------------
min_n_samples, max_n_samples = 101, 3000  # min and max n_samples to try
n_samples_grid_size = 3                   # nb of positions in the grid to try
# generate the grid
n_samples_range = [min_n_samples + np.floor((x / (n_samples_grid_size - 1))
                                            * (max_n_samples - min_n_samples))
                   for x in range(0, n_samples_grid_size)]

n_components = 100      # the number of principal components we want to use
n_iter = 3              # the number of times each experiment will be repeated
include_arpack = False  # set to True if you wish to run arpack too


# 2- Generate random data
# -----------------------
np.random.seed(0)
n_features = 2
X, y = make_circles(n_samples=max_n_samples, factor=.3, noise=.05)


# 3- Benchmark
# ------------
# init
ref_time = np.empty((len(n_samples_range), n_iter)) * np.nan
a_time = np.empty((len(n_samples_range), n_iter)) * np.nan
r_time = np.empty((len(n_samples_range), n_iter)) * np.nan

# loop
for j, n_samples in enumerate(n_samples_range):

    n_samples = int(n_samples)
    print("Performing kPCA with n_samples = %i" % n_samples)

    X_train = X[:n_samples, :]
    X_test = X_train

    # A- reference (dense)
    print("  - dense")
    for i in range(n_iter):
        start_time = datetime.now()
        ref_pred = KernelPCA(n_components, eigen_solver="dense") \
            .fit(X_train).transform(X_test)
        ref_time[j, i] = (datetime.now() - start_time).total_seconds()

    # B- arpack
    if include_arpack:
        print("  - arpack")
        for i in range(n_iter):
            start_time = datetime.now()
            a_pred = KernelPCA(n_components, eigen_solver="arpack") \
                .fit(X_train).transform(X_test)
            # check that the result is still correct despite the approx
            assert_array_almost_equal(np.abs(a_pred), np.abs(ref_pred))
            a_time[j, i] = (datetime.now() - start_time).total_seconds()

    # C- randomized
    print("  - randomized")
    for i in range(n_iter):
        start_time = datetime.now()
        r_pred = KernelPCA(n_components, eigen_solver="randomized") \
            .fit(X_train).transform(X_test)
        # check that the result is still correct despite the approximation
        assert_array_almost_equal(np.abs(r_pred), np.abs(ref_pred))
        r_time[j, i] = (datetime.now() - start_time).total_seconds()

# Compute statistics for the 3 methods
avg_ref_time = ref_time.mean(axis=1)
std_ref_time = ref_time.std(axis=1)
avg_a_time = a_time.mean(axis=1)
std_a_time = a_time.std(axis=1)
avg_r_time = r_time.mean(axis=1)
std_r_time = r_time.std(axis=1)


# 4- Plots
# --------
plt.figure(figsize=(15, 20))

# Display 1 plot with error bars per method
plt.errorbar(n_samples_range, avg_ref_time, yerr=std_ref_time,
             marker='x', linestyle='', color='r', label='full')
if include_arpack:
    plt.errorbar(n_samples_range, avg_a_time, yerr=std_a_time, marker='x',
                 linestyle='', color='g', label='arpack')
plt.errorbar(n_samples_range, avg_r_time, yerr=std_r_time, marker='x',
             linestyle='', color='b', label='randomized')
plt.legend(loc='upper left')

# customize axes
ax = plt.gca()
ax.set_xlim(min(n_samples_range) * 0.9, max(n_samples_range) * 1.1)
ax.set_ylabel("Execution time (s)")
ax.set_xlabel("n_samples")

plt.title("Execution time comparison of kPCA with %i components on samples "
          "with %i features, according to the choice of `eigen_solver`"
          "" % (n_components, n_features))

plt.show()
