# Pairwise Distances Reductions
# =============================
#
#    Author: Julien Jerphanion <git@jjerphan.xyz>
#
#
# The routines defined here are used in various algorithms performing
# the same structure of operations on distances between vectors
# of a datasets pair (X, Y).
#
# Importantly, the core of the computation is chunked to make sure that the pairwise
# distance chunk matrices stay in CPU cache before applying the final reduction step.
# Furthermore, the chunking strategy is also used to leverage OpenMP-based parallelism
# (using Cython prange loops) which gives another multiplicative speed-up in
# favorable cases on many-core machines.
cimport numpy as np
import numpy as np
import warnings
import scipy.sparse

from .. import get_config
from libc.stdlib cimport free, malloc
from libc.float cimport DBL_MAX
from cython cimport final
from cython.parallel cimport parallel, prange

from ._dist_metrics cimport DatasetsPair, DenseDenseDatasetsPair
from ..utils._cython_blas cimport (
  BLAS_Order,
  BLAS_Trans,
  ColMajor,
  NoTrans,
  RowMajor,
  Trans,
  _dot,
  _gemm,
)
from ..utils._heap cimport simultaneous_sort, heap_push
from ..utils._openmp_helpers cimport _openmp_thread_num
from ..utils._typedefs cimport ITYPE_t, DTYPE_t, DITYPE_t

from numbers import Integral, Real
from typing import List
from scipy.sparse import issparse
from ._dist_metrics import BOOL_METRICS, METRIC_MAPPING
from ..utils import check_scalar, _in_unstable_openblas_configuration
from ..utils.fixes import threadpool_limits
from ..utils._openmp_helpers import _openmp_effective_n_threads
from ..utils._typedefs import ITYPE, DTYPE

np.import_array()

cpdef DTYPE_t[::1] _sqeuclidean_row_norms(
    const DTYPE_t[:, ::1] X,
    ITYPE_t num_threads,
):
    """Compute the squared euclidean norm of the rows of X in parallel.

    This is faster than using np.einsum("ij, ij->i") even when using a single thread.
    """
    cdef:
        # Casting for X to remove the const qualifier is needed because APIs
        # exposed via scipy.linalg.cython_blas aren't reflecting the arguments'
        # const qualifier.
        DTYPE_t * X_ptr = <DTYPE_t *> &X[0, 0]
        ITYPE_t idx = 0
        ITYPE_t n = X.shape[0]
        ITYPE_t d = X.shape[1]
        DTYPE_t[::1] row_norms = np.empty(n, dtype=DTYPE)

    for idx in prange(n, schedule='static', nogil=True, num_threads=num_threads):
        row_norms[idx] = _dot(d, X_ptr + idx * d, 1, X_ptr + idx * d, 1)

    return row_norms

cdef class PairwiseDistancesReduction:
    """Abstract base class for pairwise distance computation & reduction

    Subclasses of this class compute pairwise distances between a set of
    vectors (rows) X and another set of vectors (rows) Y and apply a
    reduction on top. The reduction takes a matrix of pairwise distances
    between rows of X and Y as input and outputs an aggregate data-structure
    for each row of X. The aggregate values are typically smaller than the number
    of rows in Y, hence the term reduction.

    For computational reasons, it is interesting to perform the reduction on
    the fly on chunks of rows of X and Y so as to keep intermediate
    data-structures in CPU cache and avoid unnecessary round trips of large
    distance arrays with the RAM that would otherwise severely degrade the
    speed by making the overall processing memory-bound.

    The base class provides the generic chunked parallelization template using
    OpenMP loops (Cython prange), either on rows of X or rows of Y depending on
    their respective sizes.

    The subclasses are specialized for reduction.

    The actual distance computation for a given pair of rows of X and Y are
    delegated to format-specific subclasses of the DatasetsPair companion base
    class.

    Parameters
    ----------
    datasets_pair: DatasetsPair
        The pair of dataset to use.

    chunk_size: int, default=None,
        The number of vectors per chunk. If None (default) looks-up in
        scikit-learn configuration for `pairwise_dist_chunk_size`,
        and use 256 if it is not set.

    n_threads: int, default=None
        The number of OpenMP threads to use for the reduction.
        Parallelism is done on chunks and the sharding of chunks
        depends on the `strategy` set on :method:`~PairwiseDistancesReduction.compute`.

        See _openmp_effective_n_threads, for details about
        the specification of n_threads.
    """

    cdef:
        readonly DatasetsPair datasets_pair

        ITYPE_t n_threads
        ITYPE_t effective_omp_n_thread
        ITYPE_t n_samples_chunk, chunk_size

        ITYPE_t n_samples_X, X_n_samples_chunk, X_n_chunks, X_n_samples_remainder
        ITYPE_t n_samples_Y, Y_n_samples_chunk, Y_n_chunks, Y_n_samples_remainder

    @classmethod
    def valid_metrics(cls) -> List[str]:
        excluded = {
            "pyfunc",  # is relatively slow because we need to coerce data as np arrays
            "mahalanobis", # is numerically unstable
            # TODO: In order to support discrete distance metrics, we need to have a
            # simultaneous sort which breaks ties on indices when distances are identical.
            # The best might be using a std::sort and a Comparator which might need
            # AoS instead of SoA (currently used).
            "hamming",
            *BOOL_METRICS,
        }
        return sorted({"fast_euclidean", "fast_sqeuclidean",
                       *METRIC_MAPPING.keys()}.difference(excluded))

    @classmethod
    def is_usable_for(cls, X, Y, metric) -> bool:
        """Return True if the PairwiseDistancesReduction can be used for the given parameters.

        Parameters
        ----------
        X : {ndarray, sparse matrix} of shape (n_samples_X, n_features)
            Input data.

        Y : {ndarray, sparse matrix} of shape (n_samples_Y, n_features)
            Input data.

        metric : str, default='euclidean'
            The distance metric to use.
            For a list of available metrics, see the documentation of
            :class:`~sklearn.metrics.DistanceMetric`.

        Returns
        -------
        True if the PairwiseDistancesReduction can be used, else False.
        """
        # Coercing to np.array to get the dtype
        # TODO: what is the best way to get lists' dtype?
        X = np.asarray(X) if not isinstance(X, (np.ndarray, scipy.sparse.spmatrix)) else X
        Y = np.asarray(Y) if not isinstance(Y, (np.ndarray, scipy.sparse.spmatrix)) else Y
        # TODO: support sparse arrays and 32 bits
        return (not issparse(X) and X.dtype == np.float64 and X.ndim == 2 and
                not issparse(Y) and Y.dtype == np.float64 and Y.ndim == 2 and
                metric in cls.valid_metrics())

    def __init__(
        self,
        DatasetsPair datasets_pair,
        chunk_size=None,
        n_threads=None,
     ):
        cdef:
            ITYPE_t n_samples_chunk, X_n_full_chunks, Y_n_full_chunks

        if chunk_size is None:
            chunk_size = get_config().get("pairwise_dist_chunk_size", 256)

        self.chunk_size = check_scalar(chunk_size, "chunk_size", Integral, min_val=20)

        self.effective_omp_n_thread = _openmp_effective_n_threads(n_threads)

        self.datasets_pair = datasets_pair

        self.n_samples_X = datasets_pair.n_samples_X()
        self.X_n_samples_chunk = min(self.n_samples_X, self.chunk_size)
        X_n_full_chunks = self.n_samples_X // self.X_n_samples_chunk
        self.X_n_samples_remainder = self.n_samples_X % self.X_n_samples_chunk

        self.n_samples_Y = datasets_pair.n_samples_Y()
        self.Y_n_samples_chunk = min(self.n_samples_Y, self.chunk_size)
        Y_n_full_chunks = self.n_samples_Y // self.Y_n_samples_chunk
        self.Y_n_samples_remainder = self.n_samples_Y % self.Y_n_samples_chunk

        # Counting remainder chunk in total number of chunks
        self.X_n_chunks = X_n_full_chunks + (self.X_n_samples_remainder != 0)
        self.Y_n_chunks = Y_n_full_chunks + (self.Y_n_samples_remainder != 0)

    def compute(
        self,
        str strategy=None,
        bint return_distance=False,
    ):
        """Compute the pairwise distances and the reduction of vectors (rows) of X on Y.

        Parameters
        ----------
        strategy : str, {'auto', 'parallel_on_X', 'parallel_on_Y'}, default=None
            The chunking strategy defining which dataset parallelization are made on.

            Strategies differs on the dispatching they use for chunks on threads:

              - 'parallel_on__X' dispatches chunks of X uniformly on threads.
              Each thread then iterates on all the chunks of Y. This strategy is
              embarrassingly parallel and comes with no datastructures synchronisation.

              - 'parallel_on_Y' dispatches chunks of Y uniformly on threads.
              Each thread then iterates on all the chunks of X. This strategy is
              embarrassingly parallel but uses intermediate datastructures
              synchronisation.

              - 'auto' relies on a simple heuristic to choose between
              'parallel_on__X' and 'parallel_on_Y'.

              - None (default) looks-up in scikit-learn configuration for
              `pairwise_dist_parallel_strategy`, and use 'auto' if it is not set.

        return_distance : boolean, default=False
            Return distances between each X vector and its
            argkmin if set to True.

        Returns
        -------
        If True, return the distances between each sample of X and
        the samples of Y selected by the reduction function.
        """

        if strategy is None:
            strategy = get_config().get("pairwise_dist_parallel_strategy", 'auto')

        if strategy == 'auto':
            # This is a simple heuristic whose constant for the
            # comparison has been chosen based on experiments.
            if 4 * self.chunk_size * self.effective_omp_n_thread < self.n_samples_X:
                strategy = 'parallel_on_X'
            else:
                strategy = 'parallel_on_Y'

        # Limit the number of threads in second level of nested parallelism for BLAS
        # to avoid threads over-subscription (in GEMM for instance).
        with threadpool_limits(limits=1, user_api="blas"):
            if strategy == 'parallel_on_Y':
                self._parallel_on_Y()
            elif strategy == 'parallel_on_X':
                self._parallel_on_X()
            else:
                raise RuntimeError(f"strategy must be 'parallel_on_X, 'parallel_on_Y', "
                                   f"or 'auto', but currently strategy='{strategy}'.")

        return self._finalize_results(return_distance)

    @final
    cdef void _parallel_on_X(self) nogil:
        """Compute the pairwise distances of each vector (row) of X on Y
        by parallelizing computation on chunks of X and reduce them.

        This strategy dispatches chunks of X uniformly on threads.
        Each thread then iterates on all the chunks of Y. This strategy is
        embarrassingly parallel and comes with no datastructures synchronisation.

        Private datastructures are modified internally by threads.

        Private template methods can be implemented on subclasses to
        interact with those datastructures at various stages.
        """
        cdef:
            ITYPE_t Y_start, Y_end, X_start, X_end, X_chunk_idx, Y_chunk_idx
            ITYPE_t num_threads = min(self.X_n_chunks, self.effective_omp_n_thread)
            ITYPE_t thread_num

        with nogil, parallel(num_threads=num_threads):
            thread_num = _openmp_thread_num()

            # Allocating thread datastructures
            self._parallel_on_X_parallel_init(thread_num)

            for X_chunk_idx in prange(self.X_n_chunks, schedule='static'):
                X_start = X_chunk_idx * self.X_n_samples_chunk
                if (X_chunk_idx == self.X_n_chunks - 1
                    and self.X_n_samples_remainder > 0):
                    X_end = X_start + self.X_n_samples_remainder
                else:
                    X_end = X_start + self.X_n_samples_chunk

                # Reinitializing thread datastructures for the new X chunk
                self._parallel_on_X_init_chunk(thread_num, X_start)

                for Y_chunk_idx in range(self.Y_n_chunks):
                    Y_start = Y_chunk_idx * self.Y_n_samples_chunk
                    if (Y_chunk_idx == self.Y_n_chunks - 1
                        and self.Y_n_samples_remainder > 0):
                        Y_end = Y_start + self.Y_n_samples_remainder
                    else:
                        Y_end = Y_start + self.Y_n_samples_chunk

                    self._compute_and_reduce_distances_on_chunks(
                        X_start, X_end,
                        Y_start, Y_end,
                        thread_num,
                    )

                # Adjusting thread datastructures on the full pass on Y
                self._parallel_on_X_prange_iter_finalize(thread_num, X_start, X_end)

            # end: for X_chunk_idx

            # Deallocating thread datastructures
            self._parallel_on_X_parallel_finalize(thread_num)

        # end: with nogil, parallel
        return

    @final
    cdef void _parallel_on_Y(self) nogil:
        """Compute the pairwise distances of each vector (row) of X on Y
        by parallelizing computation on chunks of Y and reduce them.

        This strategy dispatches chunks of Y uniformly on threads.
        Each thread then iterates on all the chunks of X. This strategy is
        embarrassingly parallel but uses intermediate datastructures
        synchronisation.

        Private datastructures are modified internally by threads.

        Private template methods can be implemented on subclasses to
        interact with those datastructures at various stages.
        """
        cdef:
            ITYPE_t Y_start, Y_end, X_start, X_end, X_chunk_idx, Y_chunk_idx
            ITYPE_t num_threads = min(self.Y_n_chunks, self.effective_omp_n_thread)
            ITYPE_t thread_num

        # Allocating datastructures
        self._parallel_on_Y_parallel_init(num_threads)

        for X_chunk_idx in range(self.X_n_chunks):
            X_start = X_chunk_idx * self.X_n_samples_chunk
            if X_chunk_idx == self.X_n_chunks - 1 and self.X_n_samples_remainder > 0:
                X_end = X_start + self.X_n_samples_remainder
            else:
                X_end = X_start + self.X_n_samples_chunk

            with nogil, parallel(num_threads=num_threads):
                thread_num = _openmp_thread_num()

                # Initializing datastructures used in this thread
                self._parallel_on_Y_init(thread_num)

                for Y_chunk_idx in prange(self.Y_n_chunks, schedule='static'):
                    Y_start = Y_chunk_idx * self.Y_n_samples_chunk
                    if Y_chunk_idx == self.Y_n_chunks - 1 \
                            and self.Y_n_samples_remainder > 0:
                        Y_end = Y_start + self.Y_n_samples_remainder
                    else:
                        Y_end = Y_start + self.Y_n_samples_chunk

                    self._compute_and_reduce_distances_on_chunks(
                        X_start, X_end,
                        Y_start, Y_end,
                        thread_num,
                    )
                # end: prange

                # Note: we don't need a _parallel_on_Y_finalize similarly.
                # This can be introduced if needed.

            # end: with nogil, parallel

            # Synchronizing the thread datastructures with the main ones
            self._parallel_on_Y_synchronize(num_threads, X_start, X_end)

        # end: for X_chunk_idx
        # Deallocating temporary datastructures and adjusting main datastructures
        self._parallel_on_Y_finalize(num_threads)
        return

    # Placeholder methods which have to be implemented

    cdef void _compute_and_reduce_distances_on_chunks(
        self,
        ITYPE_t X_start,
        ITYPE_t X_end,
        ITYPE_t Y_start,
        ITYPE_t Y_end,
        ITYPE_t thread_num,
    ) nogil:
        """Compute the pairwise distances on two chunks of X and Y and reduce them.

        This is the core critical region of PairwiseDistanceReductions' computations
        which must be implemented in subclasses.
        """
        return

    def _finalize_results(self, bint return_distance):
        """Call-back adapting datastructures before returning results.

        This must be implemented in subclasses.
        """
        return None

    # Placeholder methods which can be implemented

    cdef void compute_exact_distances(self) nogil:
        """Convert rank-preserving distances to exact distances or recompute them."""
        return

    cdef void _parallel_on_X_parallel_init(
        self,
        ITYPE_t thread_num,
    ) nogil:
        """Allocate datastructures used in a thread given its number."""
        return

    cdef void _parallel_on_X_init_chunk(
        self,
        ITYPE_t thread_num,
        ITYPE_t X_start,
    ) nogil:
        """Initialise datastructures used in a thread given its number."""
        return

    cdef void _parallel_on_X_prange_iter_finalize(
        self,
        ITYPE_t thread_num,
        ITYPE_t X_start,
        ITYPE_t X_end,
    ) nogil:
        """Interact with datastructures after a reduction on chunks."""
        return

    cdef void _parallel_on_X_parallel_finalize(
        self,
        ITYPE_t thread_num
    ) nogil:
        """Interact with datastructures after executing all the reductions."""
        return

    cdef void _parallel_on_Y_parallel_init(
        self,
        ITYPE_t num_threads,
    ) nogil:
        """Allocate datastructures used in all threads."""
        return

    cdef void _parallel_on_Y_init(
        self,
        ITYPE_t thread_num,
    ) nogil:
        """Initialise datastructures used in a thread given its number."""
        return

    cdef void _parallel_on_Y_synchronize(
        self,
        ITYPE_t num_threads,
        ITYPE_t X_start,
        ITYPE_t X_end,
    ) nogil:
        """Update thread datastructures before leaving a parallel region."""
        return

    cdef void _parallel_on_Y_finalize(
        self,
        ITYPE_t num_threads,
    ) nogil:
        """Update datastructures after executing all the reductions."""
        return

cdef class PairwiseDistancesArgKmin(PairwiseDistancesReduction):
    """Compute the argkmin of vectors (rows) of X on the ones of Y.

    Parameters
    ----------
    datasets_pair: DatasetsPair
        The dataset pairs (X, Y) for the reduction.

    k: int
        The k for the argkmin reduction.

    chunk_size: int, default=None,
        The number of vectors per chunk. If None (default) looks-up in
        scikit-learn configuration for `pairwise_dist_chunk_size`,
        and use 256 if it is not set.

    n_threads: int, default=None
        The number of OpenMP threads to use for the reduction.
        Parallelism is done on chunks and the sharding of chunks
        depends on the `strategy` set on :method:`~ArgKmin.compute`.

        See _openmp_effective_n_threads, for details about
        the specification of n_threads.
    """

    cdef:
        ITYPE_t k

        ITYPE_t[:, ::1] argkmin_indices
        DTYPE_t[:, ::1] argkmin_distances

        # Used as array of pointers to private datastructures used in threads.
        DTYPE_t ** heaps_r_distances_chunks
        ITYPE_t ** heaps_indices_chunks

    @classmethod
    def get_for(
        cls,
        X,
        Y,
        ITYPE_t k,
        str metric="fast_euclidean",
        chunk_size=None,
        dict metric_kwargs=None,
        n_threads=None,
    ) -> PairwiseDistancesArgKmin:
        """Return the PairwiseDistancesArgKmin implementation for the given arguments.

        Parameters
        ----------
        X : ndarray or CSR matrix of shape (n_samples_X, n_features)
            Input data.

        Y : ndarray or CSR matrix of shape (n_samples_Y, n_features)
            Input data.

        k : int
            The k for the argkmin reduction.

        metric : str, default='fast_euclidean'
            The distance metric to use for argkmin. The default metric is
            a fast implementation of the standard Euclidean metric.
            For a list of available metrics, see the documentation of
            :class:`~sklearn.metrics.DistanceMetric`.

        chunk_size : int, default=None,
            The number of vectors per chunk. If None (default) looks-up in
            scikit-learn configuration for `pairwise_dist_chunk_size`,
            and use 256 if it is not set.

        metric_kwargs : dict, default=None
            Keyword arguments to pass to specified metric function.

        n_threads : int, default=None
            The number of OpenMP threads to use for the reduction.
            Parallelism is done on chunks and the sharding of chunks
            depends on the `strategy` set on
            :method:`~PairwiseDistancesArgKmin.compute`.

            See _openmp_effective_n_threads, for details about
            the specification of n_threads.

        Returns
        -------
        argkmin: PairwiseDistancesArgKmin
            The suited PairwiseDistancesArgKmin implementation.
        """
        # This factory comes to handle specialisations.
        if metric in ("fast_euclidean", "fast_sqeuclidean") and not issparse(X) and not issparse(Y):
            use_squared_distances = metric == "fast_sqeuclidean"
            return FastEuclideanPairwiseDistancesArgKmin(
                X=X, Y=Y, k=k,
                use_squared_distances=use_squared_distances,
                chunk_size=chunk_size,
                metric_kwargs=metric_kwargs,
            )

        return PairwiseDistancesArgKmin(
            datasets_pair=DatasetsPair.get_for(X, Y, metric, metric_kwargs),
            k=k,
            chunk_size=chunk_size,
        )

    def __init__(
        self,
        DatasetsPair datasets_pair,
        ITYPE_t k,
        chunk_size=None,
        n_threads=None,
    ):
        super().__init__(datasets_pair, chunk_size, n_threads)

        self.k = check_scalar(k, "k", Integral, min_val=1)

        # Allocating pointers to datastructures but not the datastructures themselves.
        # There are as many pointers as available threads.
        # However, when reducing on small datasets, there can be more pointers than
        # actual threads.
        # In this case, some pointers will be dynamically allocated but there won't
        # be allocated yet unused data-structures referenced by them.
        #
        # For the sake of explicitness:
        #   - when parallelizing on X, those heaps pointers are referencing
        #   (with proper offsets) addresses of the two main heaps (see bellow)
        #   - when parallelizing on Y, those heaps pointer heaps are referencing
        #   small heaps which are thread-wise-allocated and whose content will be
        #   merged with the main heaps'.
        self.heaps_r_distances_chunks = <DTYPE_t **> malloc(
            sizeof(DTYPE_t *) * self.effective_omp_n_thread
        )
        self.heaps_indices_chunks = <ITYPE_t **> malloc(
            sizeof(ITYPE_t *) * self.effective_omp_n_thread
        )

        # Main heaps used by PairwiseDistancesArgKmin.compute to return results.
        self.argkmin_indices = np.full((self.n_samples_X, self.k), 0, dtype=ITYPE)
        self.argkmin_distances = np.full((self.n_samples_X, self.k), DBL_MAX, dtype=DTYPE)

    def __dealloc__(self):
        if self.heaps_indices_chunks is not NULL:
            free(self.heaps_indices_chunks)

        if self.heaps_r_distances_chunks is not NULL:
            free(self.heaps_r_distances_chunks)

    cdef void _compute_and_reduce_distances_on_chunks(
        self,
        ITYPE_t X_start,
        ITYPE_t X_end,
        ITYPE_t Y_start,
        ITYPE_t Y_end,
        ITYPE_t thread_num,
    ) nogil:
        cdef:
            ITYPE_t i, j
            ITYPE_t n_samples_X = X_end - X_start
            ITYPE_t n_samples_Y = Y_end - Y_start
            DTYPE_t *heaps_r_distances = self.heaps_r_distances_chunks[thread_num]
            ITYPE_t *heaps_indices = self.heaps_indices_chunks[thread_num]

        # Pushing the distance and their associated indices on heaps
        # which keep tracks of the argkmin.
        for i in range(n_samples_X):
            for j in range(n_samples_Y):
                heap_push(
                    heaps_r_distances + i * self.k,
                    heaps_indices + i * self.k,
                    self.k,
                    self.datasets_pair.surrogate_dist(X_start + i, Y_start + j),
                    Y_start + j,
                )

    @final
    cdef void _parallel_on_X_init_chunk(
        self,
        ITYPE_t thread_num,
        ITYPE_t X_start,
    ) nogil:
        # As this strategy is embarrassingly parallel, we can set the
        # thread heaps pointers to the proper position on the main heaps
        self.heaps_r_distances_chunks[thread_num] = &self.argkmin_distances[X_start, 0]
        self.heaps_indices_chunks[thread_num] = &self.argkmin_indices[X_start, 0]

    @final
    cdef void _parallel_on_X_prange_iter_finalize(
        self,
        ITYPE_t thread_num,
        ITYPE_t X_start,
        ITYPE_t X_end,
    ) nogil:
        cdef:
            ITYPE_t idx, jdx

        # Sorting indices of the argkmin for each query vector of X
        for idx in range(X_end - X_start):
            simultaneous_sort(
                self.heaps_r_distances_chunks[thread_num] + idx * self.k,
                self.heaps_indices_chunks[thread_num] + idx * self.k,
                self.k
            )

    cdef void _parallel_on_Y_parallel_init(
        self,
        ITYPE_t num_threads,
    ) nogil:
        cdef:
            # Maximum number of scalar elements (the last chunks can be smaller)
            ITYPE_t heaps_size = self.X_n_samples_chunk * self.k
            ITYPE_t thread_num

        # The allocation is done in parallel for data locality purposes: this way
        # the heaps used in each threads are allocated in pages which are closer
        # to processor core used by the thread.
        for thread_num in prange(num_threads, schedule='static', nogil=True,
                                 num_threads=num_threads):
            # As chunks of X are shared across threads, so must their
            # heaps. To solve this, each thread has its own heaps
            # which are then synchronised back in the main ones.
            self.heaps_r_distances_chunks[thread_num] = <DTYPE_t *> malloc(
                heaps_size * sizeof(DTYPE_t)
            )
            self.heaps_indices_chunks[thread_num] = <ITYPE_t *> malloc(
                heaps_size * sizeof(ITYPE_t)
            )

    @final
    cdef void _parallel_on_Y_init(
        self,
        ITYPE_t thread_num,
    ) nogil:
        # Initialising heaps (memset can't be used here)
        for idx in range(self.X_n_samples_chunk * self.k):
            self.heaps_r_distances_chunks[thread_num][idx] = DBL_MAX
            self.heaps_indices_chunks[thread_num][idx] = -1

    @final
    cdef void _parallel_on_Y_synchronize(
        self,
        ITYPE_t num_threads,
        ITYPE_t X_start,
        ITYPE_t X_end,
    ) nogil:
        cdef:
            ITYPE_t idx, jdx, thread_num
        with nogil, parallel(num_threads=self.effective_omp_n_thread):
            # Synchronising the thread heaps with the main heaps
            # This is done in parallel samples-wise (no need for locks)
            for idx in prange(X_end - X_start, schedule="static"):
                for thread_num in range(num_threads):
                    for jdx in range(self.k):
                        heap_push(
                            &self.argkmin_distances[X_start + idx, 0],
                            &self.argkmin_indices[X_start + idx, 0],
                            self.k,
                            self.heaps_r_distances_chunks[thread_num][idx * self.k + jdx],
                            self.heaps_indices_chunks[thread_num][idx * self.k + jdx],
                        )

    cdef void _parallel_on_Y_finalize(
        self,
        ITYPE_t num_threads,
    ) nogil:
        cdef:
            ITYPE_t idx, thread_num

        with nogil, parallel(num_threads=self.effective_omp_n_thread):
            # Deallocating temporary datastructures
            for thread_num in prange(num_threads, schedule='static'):
                free(self.heaps_r_distances_chunks[thread_num])
                free(self.heaps_indices_chunks[thread_num])

            # Sort the main heaps into arrays in parallel
            # in ascending order w.r.t the distances
            for idx in prange(self.n_samples_X, schedule='static'):
                simultaneous_sort(
                    &self.argkmin_distances[idx, 0],
                    &self.argkmin_indices[idx, 0],
                    self.k,
                )
        return

    cdef void compute_exact_distances(self) nogil:
        cdef:
            ITYPE_t i, j
            ITYPE_t[:, ::1] Y_indices = self.argkmin_indices
            DTYPE_t[:, ::1] distances = self.argkmin_distances
        for i in prange(self.n_samples_X, schedule='static', nogil=True,
                        num_threads=self.effective_omp_n_thread):
            for j in range(self.k):
                distances[i, j] = self.datasets_pair.distance_metric._rdist_to_dist(
                    # Guard against eventual -0., causing nan production.
                    max(distances[i, j], 0.)
                )

    def _finalize_results(self, bint return_distance=False):
        if return_distance:
            # We need to recompute distances because we relied on
            # surrogate distances for the reduction.
            self.compute_exact_distances()
            return np.asarray(self.argkmin_distances), np.asarray(self.argkmin_indices)

        return np.asarray(self.argkmin_indices)


cdef class FastEuclideanPairwiseDistancesArgKmin(PairwiseDistancesArgKmin):
    """Fast specialized alternative for PairwiseDistancesArgKmin on EuclideanDistance.

    The full pairwise squared distances matrix is computed as follows:

                  ||X - Y||² = ||X||² - 2 X.Y^T + ||Y||²

    The middle term gets computed efficiently bellow using BLAS Level 3 GEMM.

    Notes
    -----
    This implementation has a superior arithmetic intensity and hence
    better running time when the alternative is IO bound, but it can suffer
    from numerical instability caused by catastrophic cancellation potentially
    introduced by the subtraction in the arithmetic expression above.

    PairwiseDistancesArgKmin with EuclideanDistance must be used when higher
    numerical precision is needed.
    """

    cdef:
        const DTYPE_t[:, ::1] X
        const DTYPE_t[:, ::1] Y
        const DTYPE_t[::1] X_norm_squared
        const DTYPE_t[::1] Y_norm_squared

        # Buffers for GEMM
        DTYPE_t ** dist_middle_terms_chunks
        bint use_squared_distances

    @classmethod
    def is_usable_for(cls, X, Y, metric) -> bool:
        return (PairwiseDistancesArgKmin.is_usable_for(X, Y, metric) and
                not _in_unstable_openblas_configuration())

    def __init__(
        self,
        X,
        Y,
        ITYPE_t k,
        bint use_squared_distances=False,
        chunk_size=None,
        metric_kwargs=None,
    ):
        if metric_kwargs is not None and len(metric_kwargs) > 0:
            warnings.warn(
                f"Some metric_kwargs have been passed ({metric_kwargs}) but aren't"
                f"usable for this case ({self.__class__.__name__}) and will be ignored.",
                UserWarning,
                stacklevel=3,
            )

        super().__init__(
            # The datasets pair here is used for exact distances computations
            datasets_pair=DatasetsPair.get_for(X, Y, metric="euclidean"),
            k=k,
            chunk_size=chunk_size,
        )
        # X and Y are checked by the DatasetsPair implemented as a DenseDenseDatasetsPair
        cdef:
            DenseDenseDatasetsPair datasets_pair = <DenseDenseDatasetsPair> self.datasets_pair
        self.X, self.Y = datasets_pair.X, datasets_pair.Y

        if metric_kwargs is not None and "Y_norm_squared" in metric_kwargs:
            self.Y_norm_squared = metric_kwargs.pop("Y_norm_squared", None)
        else:
            self.Y_norm_squared = _sqeuclidean_row_norms(self.Y, self.effective_omp_n_thread)

        # Do not recompute norms if datasets are identical.
        self.X_norm_squared = (
            self.Y_norm_squared if X is Y else
            _sqeuclidean_row_norms(self.X, self.effective_omp_n_thread)
        )
        self.use_squared_distances = use_squared_distances

        # Temporary datastructures used in threads
        self.dist_middle_terms_chunks = <DTYPE_t **> malloc(
            sizeof(DTYPE_t *) * self.effective_omp_n_thread
        )

    def __dealloc__(self):
        if self.dist_middle_terms_chunks is not NULL:
            free(self.dist_middle_terms_chunks)

    @final
    cdef void compute_exact_distances(self) nogil:
        if not self.use_squared_distances:
            PairwiseDistancesArgKmin.compute_exact_distances(self)

    @final
    cdef void _parallel_on_X_parallel_init(
        self,
        ITYPE_t thread_num,
    ) nogil:
        PairwiseDistancesArgKmin._parallel_on_X_parallel_init(self, thread_num)

        # Temporary buffer for the `-2 * X_c @ Y_c.T` term
        self.dist_middle_terms_chunks[thread_num] = <DTYPE_t *> malloc(
            self.Y_n_samples_chunk * self.X_n_samples_chunk * sizeof(DTYPE_t)
        )

    @final
    cdef void _parallel_on_X_parallel_finalize(
        self,
        ITYPE_t thread_num
    ) nogil:
        PairwiseDistancesArgKmin._parallel_on_X_parallel_finalize(self, thread_num)
        free(self.dist_middle_terms_chunks[thread_num])

    @final
    cdef void _parallel_on_Y_parallel_init(
        self,
        ITYPE_t num_threads,
    ) nogil:
        cdef ITYPE_t thread_num
        PairwiseDistancesArgKmin._parallel_on_Y_parallel_init(self, num_threads)

        for thread_num in range(num_threads):
            # Temporary buffer for the `-2 * X_c @ Y_c.T` term
            self.dist_middle_terms_chunks[thread_num] = <DTYPE_t *> malloc(
                self.Y_n_samples_chunk * self.X_n_samples_chunk * sizeof(DTYPE_t)
            )

    @final
    cdef void _parallel_on_Y_finalize(
        self,
        ITYPE_t num_threads,
    ) nogil:
        cdef ITYPE_t thread_num
        PairwiseDistancesArgKmin._parallel_on_Y_finalize(self, num_threads)

        for thread_num in range(num_threads):
            free(self.dist_middle_terms_chunks[thread_num])

    @final
    cdef void _compute_and_reduce_distances_on_chunks(
        self,
        ITYPE_t X_start,
        ITYPE_t X_end,
        ITYPE_t Y_start,
        ITYPE_t Y_end,
        ITYPE_t thread_num,
    ) nogil:
        cdef:
            ITYPE_t i, j

            const DTYPE_t[:, ::1] X_c = self.X[X_start:X_end, :]
            const DTYPE_t[:, ::1] Y_c = self.Y[Y_start:Y_end, :]
            DTYPE_t *dist_middle_terms = self.dist_middle_terms_chunks[thread_num]
            DTYPE_t *heaps_r_distances = self.heaps_r_distances_chunks[thread_num]
            ITYPE_t *heaps_indices = self.heaps_indices_chunks[thread_num]

            # Careful: LDA, LDB and LDC are given for F-ordered arrays
            # in BLAS documentations, for instance:
            # https://www.netlib.org/lapack/explore-html/db/dc9/group__single__blas__level3_gafe51bacb54592ff5de056acabd83c260.html #noqa
            #
            # Here, we use their counterpart values to work with C-ordered arrays.
            BLAS_Order order = RowMajor
            BLAS_Trans ta = NoTrans
            BLAS_Trans tb = Trans
            ITYPE_t m = X_c.shape[0]
            ITYPE_t n = Y_c.shape[0]
            ITYPE_t K = X_c.shape[1]
            DTYPE_t alpha = - 2.
            # Casting for A and B to remove the const is needed because APIs exposed via
            # scipy.linalg.cython_blas aren't reflecting the arguments' const qualifier.
            DTYPE_t * A = <DTYPE_t*> & X_c[0, 0]
            ITYPE_t lda = X_c.shape[1]
            DTYPE_t * B = <DTYPE_t*> & Y_c[0, 0]
            ITYPE_t ldb = X_c.shape[1]
            DTYPE_t beta = 0.
            DTYPE_t * C = dist_middle_terms
            ITYPE_t ldc = Y_c.shape[0]

        # dist_middle_terms = `-2 * X_c @ Y_c.T`
        _gemm(order, ta, tb, m, n, K, alpha, A, lda, B, ldb, beta, C, ldc)

        # Pushing the distance and their associated indices on heaps
        # which keep tracks of the argkmin.
        for i in range(X_c.shape[0]):
            for j in range(Y_c.shape[0]):
                heap_push(
                    heaps_r_distances + i * self.k,
                    heaps_indices + i * self.k,
                    self.k,
                    # Using the squared euclidean distance as the rank-preserving distance:
                    #
                    #             ||X_c_i||² - 2 X_c_i.Y_c_j^T + ||Y_c_j||²
                    #
                    (
                        self.X_norm_squared[i + X_start] +
                        dist_middle_terms[i * Y_c.shape[0] + j] +
                        self.Y_norm_squared[j + Y_start]
                    ),
                    j + Y_start,
                )
