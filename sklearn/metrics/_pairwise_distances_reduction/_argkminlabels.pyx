
from cython cimport floating, integral
from cython.parallel cimport parallel, prange
from libcpp.map cimport map as cmap, pair
from libc.stdlib cimport free

cimport numpy as cnp

cnp.import_array()

from ...utils._typedefs cimport ITYPE_t, DTYPE_t
from ...utils._typedefs import ITYPE, DTYPE
from ...utils._sorting cimport simultaneous_sort
import numpy as np
from scipy.sparse import issparse
from sklearn.utils.fixes import threadpool_limits

cpdef enum WeightingStrategy:
    uniform = 0
    distance = 1
    other = 2
from ._argkmin cimport ArgKmin64, EuclideanArgKmin64
from ._datasets_pair cimport DatasetsPair64

cdef class ArgKminLabels64(ArgKmin64):
    """
    64bit implementation of ArgKminLabel.
    """
    cdef:
        const ITYPE_t[:] labels,
        DTYPE_t[:, :] label_weights
        cmap[ITYPE_t, ITYPE_t] labels_to_index
        WeightingStrategy weight_type

    @classmethod
    def compute(
        cls,
        X,
        Y,
        ITYPE_t k,
        weights,
        labels,
        str metric="euclidean",
        chunk_size=None,
        dict metric_kwargs=None,
        str strategy=None,
    ):
        """Compute the argkmin reduction.

        This classmethod is responsible for introspecting the arguments
        values to dispatch to the most appropriate implementation of
        :class:`ArgKmin64`.

        This allows decoupling the API entirely from the implementation details
        whilst maintaining RAII: all temporarily allocated datastructures necessary
        for the concrete implementation are therefore freed when this classmethod
        returns.

        No instance should directly be created outside of this class method.
        """
        if (
            (
                metric in ("euclidean", "sqeuclidean")
                or metric=="minkowski" and (metric_kwargs is None or metric_kwargs.get("p", 2)==2)
            )
            and not (issparse(X) ^ issparse(Y))  # "^" is the XOR operator
        ):
            # Specialized implementation of ArgKminLabels for the Euclidean distance
            # for the dense-dense and sparse-sparse cases.
            # This implementation computes the distances by chunk using
            # a decomposition of the Squared Euclidean distance.
            # This specialisation has an improved arithmetic intensity for both
            # the dense and sparse settings, allowing in most case speed-ups of
            # several orders of magnitude compared to the generic ArgKmin
            # implementation.
            # For more information see MiddleTermComputer.
            use_squared_distances = metric == "sqeuclidean"
            pda = EuclideanArgKminLabels64(
                X=X, Y=Y, k=k,
                use_squared_distances=use_squared_distances,
                chunk_size=chunk_size,
                strategy=strategy,
                metric_kwargs=metric_kwargs,
                weights=weights,
                labels=labels,
            )
        else:
            # Fall back on a generic implementation that handles most scipy
            # metrics by computing the distances between 2 vectors at a time.
            pda = ArgKminLabels64(
                datasets_pair=DatasetsPair64.get_for(X, Y, metric, metric_kwargs),
                k=k,
                chunk_size=chunk_size,
                strategy=strategy,
                weights=weights,
                labels=labels,
            )

        # Limit the number of threads in second level of nested parallelism for BLAS
        # to avoid threads over-subscription (in GEMM for instance).
        with threadpool_limits(limits=1, user_api="blas"):
            if pda.execute_in_parallel_on_Y:
                pda._parallel_on_Y()
            else:
                pda._parallel_on_X()

        return pda._finalize_results()

    def __init__(
        self,
        DatasetsPair64 datasets_pair,
        const ITYPE_t[:] labels,
        chunk_size=None,
        strategy=None,
        ITYPE_t k=1,
        weights=None,
    ):
        super().__init__(
            datasets_pair=datasets_pair,
            chunk_size=chunk_size,
            strategy=strategy,
            k=k,
        )

        if weights == "uniform":
            self.weight_type = WeightingStrategy.uniform
        elif weights == "distance":
            self.weight_type = WeightingStrategy.distance
        else:
            self.weight_type = WeightingStrategy.other
        self.labels = labels

        cdef ITYPE_t[:] unique_labels = np.unique(labels)

        cdef ITYPE_t idx, label
        # Map from set of unique labels to their indices in `label_weights`
        for idx, label in enumerate(unique_labels):
            self.labels_to_index.insert(pair[ITYPE_t, ITYPE_t](label, idx))

        # Buffer used in building a histogram for one-pass weighted mode
        self.label_weights = np.zeros((self.n_samples_X,  len(unique_labels)), dtype=DTYPE)

    def _finalize_results(self):
        probabilities = np.asarray(self.label_weights)
        probabilities /= probabilities.sum(axis=1, keepdims=True)
        return probabilities

    cdef inline void weighted_histogram_mode(
        self,
        ITYPE_t sample_index,
        ITYPE_t* indices,
        DTYPE_t* distances,
   ) nogil:
        cdef:
            ITYPE_t y_idx, label, label_index, multi_output_index
            DTYPE_t label_weight = 1

        # Iterate through the sample k-nearest neighbours
        for jdx in range(self.k):
            # Absolute indice of the jdx-th Nearest Neighbors
            # in range [0, n_samples_Y)
            if self.weight_type == WeightingStrategy.distance:
                label_weight = 1 / distances[jdx]
            y_idx = indices[jdx]
            label = self.labels[y_idx]
            label_index = self.labels_to_index[label]
            self.label_weights[sample_index][label_index] += label_weight
        return

    cdef void _parallel_on_X_prange_iter_finalize(
        self,
        ITYPE_t thread_num,
        ITYPE_t X_start,
        ITYPE_t X_end,
    ) nogil:
        cdef:
            ITYPE_t idx, sample_index
        # Sorting the main heaps portion associated to `X[X_start:X_end]`
        # in ascending order w.r.t the distances.
        for idx in range(X_end - X_start):
            simultaneous_sort(
                self.heaps_r_distances_chunks[thread_num] + idx * self.k,
                self.heaps_indices_chunks[thread_num] + idx * self.k,
                self.k
            )
            # One-pass top-one weighted mode
            # Compute the absolute index in [0, n_samples_X)
            sample_index = X_start + idx
            max_label_weight = -1
            self.weighted_histogram_mode(
                sample_index,
                &self.heaps_indices_chunks[thread_num][0],
                &self.heaps_r_distances_chunks[thread_num][0],
            )
        return

    cdef void _parallel_on_Y_finalize(
        self,
    ) nogil:
        cdef:
            ITYPE_t sample_index, thread_num

        with nogil, parallel(num_threads=self.chunks_n_threads):
            # Deallocating temporary datastructures
            for thread_num in prange(self.chunks_n_threads, schedule='static'):
                free(self.heaps_r_distances_chunks[thread_num])
                free(self.heaps_indices_chunks[thread_num])

            # Sorting the main in ascending order w.r.t the distances.
            # This is done in parallel sample-wise (no need for locks).
            for sample_index in prange(self.n_samples_X, schedule='static'):
                simultaneous_sort(
                    &self.argkmin_distances[sample_index, 0],
                    &self.argkmin_indices[sample_index, 0],
                    self.k,
                )
                self.weighted_histogram_mode(
                    sample_index,
                    &self.argkmin_indices[sample_index][0],
                    &self.argkmin_distances[sample_index][0],
                )
        return

cdef class EuclideanArgKminLabels64(EuclideanArgKmin64):
    """
    64bit implementation of ArgKminLabel.
    """
    cdef:
        const ITYPE_t[:] labels,
        DTYPE_t[:, :] label_weights
        cmap[ITYPE_t, ITYPE_t] labels_to_index
        WeightingStrategy weight_type

    def __init__(
        self,
        X,
        Y,
        ITYPE_t k,
        bint use_squared_distances=False,
        chunk_size=None,
        strategy=None,
        metric_kwargs=None,
        weights=None,
        labels=None,
    ):
        super().__init__(
            X=X, Y=Y, k=k,
            use_squared_distances=use_squared_distances,
            chunk_size=chunk_size,
            strategy=strategy,
            metric_kwargs=metric_kwargs,
        )
        if weights == "uniform":
            self.weight_type = WeightingStrategy.uniform
        elif weights == "distance":
            self.weight_type = WeightingStrategy.distance
        else:
            self.weight_type = WeightingStrategy.other
        self.labels = labels

        cdef ITYPE_t[:] unique_labels = np.unique(labels)

        cdef ITYPE_t idx, label
        # Map from set of unique labels to their indices in `label_weights`
        for idx, label in enumerate(unique_labels):
            self.labels_to_index.insert(pair[ITYPE_t, ITYPE_t](label, idx))

        # Buffer used in building a histogram for one-pass weighted mode
        self.label_weights = np.zeros((self.n_samples_X,  len(unique_labels)), dtype=DTYPE)

    def _finalize_results(self):
        probabilities = np.asarray(self.label_weights)
        probabilities /= probabilities.sum(axis=1, keepdims=True)
        return probabilities

    cdef inline void weighted_histogram_mode(
        self,
        ITYPE_t sample_index,
        ITYPE_t* indices,
        DTYPE_t* distances,
   ) nogil:
        cdef:
            ITYPE_t y_idx, label, label_index, multi_output_index
            DTYPE_t label_weight = 1

        # Iterate through the sample k-nearest neighbours
        for jdx in range(self.k):
            # Absolute indice of the jdx-th Nearest Neighbors
            # in range [0, n_samples_Y)
            if self.weight_type == WeightingStrategy.distance:
                label_weight = 1 / distances[jdx]
            y_idx = indices[jdx]
            label = self.labels[y_idx]
            label_index = self.labels_to_index[label]
            self.label_weights[sample_index][label_index] += label_weight
        return

    cdef void _parallel_on_X_prange_iter_finalize(
        self,
        ITYPE_t thread_num,
        ITYPE_t X_start,
        ITYPE_t X_end,
    ) nogil:
        cdef:
            ITYPE_t idx, sample_index
        # Sorting the main heaps portion associated to `X[X_start:X_end]`
        # in ascending order w.r.t the distances.
        for idx in range(X_end - X_start):
            simultaneous_sort(
                self.heaps_r_distances_chunks[thread_num] + idx * self.k,
                self.heaps_indices_chunks[thread_num] + idx * self.k,
                self.k
            )
            # One-pass top-one weighted mode
            # Compute the absolute index in [0, n_samples_X)
            sample_index = X_start + idx
            max_label_weight = -1
            self.weighted_histogram_mode(
                sample_index,
                &self.heaps_indices_chunks[thread_num][0],
                &self.heaps_r_distances_chunks[thread_num][0],
            )
        return

    cdef void _parallel_on_Y_finalize(
        self,
    ) nogil:
        cdef:
            ITYPE_t sample_index, thread_num

        with nogil, parallel(num_threads=self.chunks_n_threads):
            # Deallocating temporary datastructures
            for thread_num in prange(self.chunks_n_threads, schedule='static'):
                free(self.heaps_r_distances_chunks[thread_num])
                free(self.heaps_indices_chunks[thread_num])

            # Sorting the main in ascending order w.r.t the distances.
            # This is done in parallel sample-wise (no need for locks).
            for sample_index in prange(self.n_samples_X, schedule='static'):
                simultaneous_sort(
                    &self.argkmin_distances[sample_index, 0],
                    &self.argkmin_indices[sample_index, 0],
                    self.k,
                )
                self.weighted_histogram_mode(
                    sample_index,
                    &self.argkmin_indices[sample_index][0],
                    &self.argkmin_distances[sample_index][0],
                )
        return
from ._argkmin cimport ArgKmin32, EuclideanArgKmin32
from ._datasets_pair cimport DatasetsPair32

cdef class ArgKminLabels32(ArgKmin32):
    """
    32bit implementation of ArgKminLabel.
    """
    cdef:
        const ITYPE_t[:] labels,
        DTYPE_t[:, :] label_weights
        cmap[ITYPE_t, ITYPE_t] labels_to_index
        WeightingStrategy weight_type

    @classmethod
    def compute(
        cls,
        X,
        Y,
        ITYPE_t k,
        weights,
        labels,
        str metric="euclidean",
        chunk_size=None,
        dict metric_kwargs=None,
        str strategy=None,
    ):
        """Compute the argkmin reduction.

        This classmethod is responsible for introspecting the arguments
        values to dispatch to the most appropriate implementation of
        :class:`ArgKmin32`.

        This allows decoupling the API entirely from the implementation details
        whilst maintaining RAII: all temporarily allocated datastructures necessary
        for the concrete implementation are therefore freed when this classmethod
        returns.

        No instance should directly be created outside of this class method.
        """
        if (
            (
                metric in ("euclidean", "sqeuclidean")
                or metric=="minkowski" and (metric_kwargs is None or metric_kwargs.get("p", 2)==2)
            )
            and not (issparse(X) ^ issparse(Y))  # "^" is the XOR operator
        ):
            # Specialized implementation of ArgKminLabels for the Euclidean distance
            # for the dense-dense and sparse-sparse cases.
            # This implementation computes the distances by chunk using
            # a decomposition of the Squared Euclidean distance.
            # This specialisation has an improved arithmetic intensity for both
            # the dense and sparse settings, allowing in most case speed-ups of
            # several orders of magnitude compared to the generic ArgKmin
            # implementation.
            # For more information see MiddleTermComputer.
            use_squared_distances = metric == "sqeuclidean"
            pda = EuclideanArgKminLabels32(
                X=X, Y=Y, k=k,
                use_squared_distances=use_squared_distances,
                chunk_size=chunk_size,
                strategy=strategy,
                metric_kwargs=metric_kwargs,
                weights=weights,
                labels=labels,
            )
        else:
            # Fall back on a generic implementation that handles most scipy
            # metrics by computing the distances between 2 vectors at a time.
            pda = ArgKminLabels32(
                datasets_pair=DatasetsPair32.get_for(X, Y, metric, metric_kwargs),
                k=k,
                chunk_size=chunk_size,
                strategy=strategy,
                weights=weights,
                labels=labels,
            )

        # Limit the number of threads in second level of nested parallelism for BLAS
        # to avoid threads over-subscription (in GEMM for instance).
        with threadpool_limits(limits=1, user_api="blas"):
            if pda.execute_in_parallel_on_Y:
                pda._parallel_on_Y()
            else:
                pda._parallel_on_X()

        return pda._finalize_results()

    def __init__(
        self,
        DatasetsPair32 datasets_pair,
        const ITYPE_t[:] labels,
        chunk_size=None,
        strategy=None,
        ITYPE_t k=1,
        weights=None,
    ):
        super().__init__(
            datasets_pair=datasets_pair,
            chunk_size=chunk_size,
            strategy=strategy,
            k=k,
        )

        if weights == "uniform":
            self.weight_type = WeightingStrategy.uniform
        elif weights == "distance":
            self.weight_type = WeightingStrategy.distance
        else:
            self.weight_type = WeightingStrategy.other
        self.labels = labels

        cdef ITYPE_t[:] unique_labels = np.unique(labels)

        cdef ITYPE_t idx, label
        # Map from set of unique labels to their indices in `label_weights`
        for idx, label in enumerate(unique_labels):
            self.labels_to_index.insert(pair[ITYPE_t, ITYPE_t](label, idx))

        # Buffer used in building a histogram for one-pass weighted mode
        self.label_weights = np.zeros((self.n_samples_X,  len(unique_labels)), dtype=DTYPE)

    def _finalize_results(self):
        probabilities = np.asarray(self.label_weights)
        probabilities /= probabilities.sum(axis=1, keepdims=True)
        return probabilities

    cdef inline void weighted_histogram_mode(
        self,
        ITYPE_t sample_index,
        ITYPE_t* indices,
        DTYPE_t* distances,
   ) nogil:
        cdef:
            ITYPE_t y_idx, label, label_index, multi_output_index
            DTYPE_t label_weight = 1

        # Iterate through the sample k-nearest neighbours
        for jdx in range(self.k):
            # Absolute indice of the jdx-th Nearest Neighbors
            # in range [0, n_samples_Y)
            if self.weight_type == WeightingStrategy.distance:
                label_weight = 1 / distances[jdx]
            y_idx = indices[jdx]
            label = self.labels[y_idx]
            label_index = self.labels_to_index[label]
            self.label_weights[sample_index][label_index] += label_weight
        return

    cdef void _parallel_on_X_prange_iter_finalize(
        self,
        ITYPE_t thread_num,
        ITYPE_t X_start,
        ITYPE_t X_end,
    ) nogil:
        cdef:
            ITYPE_t idx, sample_index
        # Sorting the main heaps portion associated to `X[X_start:X_end]`
        # in ascending order w.r.t the distances.
        for idx in range(X_end - X_start):
            simultaneous_sort(
                self.heaps_r_distances_chunks[thread_num] + idx * self.k,
                self.heaps_indices_chunks[thread_num] + idx * self.k,
                self.k
            )
            # One-pass top-one weighted mode
            # Compute the absolute index in [0, n_samples_X)
            sample_index = X_start + idx
            max_label_weight = -1
            self.weighted_histogram_mode(
                sample_index,
                &self.heaps_indices_chunks[thread_num][0],
                &self.heaps_r_distances_chunks[thread_num][0],
            )
        return

    cdef void _parallel_on_Y_finalize(
        self,
    ) nogil:
        cdef:
            ITYPE_t sample_index, thread_num

        with nogil, parallel(num_threads=self.chunks_n_threads):
            # Deallocating temporary datastructures
            for thread_num in prange(self.chunks_n_threads, schedule='static'):
                free(self.heaps_r_distances_chunks[thread_num])
                free(self.heaps_indices_chunks[thread_num])

            # Sorting the main in ascending order w.r.t the distances.
            # This is done in parallel sample-wise (no need for locks).
            for sample_index in prange(self.n_samples_X, schedule='static'):
                simultaneous_sort(
                    &self.argkmin_distances[sample_index, 0],
                    &self.argkmin_indices[sample_index, 0],
                    self.k,
                )
                self.weighted_histogram_mode(
                    sample_index,
                    &self.argkmin_indices[sample_index][0],
                    &self.argkmin_distances[sample_index][0],
                )
        return

cdef class EuclideanArgKminLabels32(EuclideanArgKmin32):
    """
    32bit implementation of ArgKminLabel.
    """
    cdef:
        const ITYPE_t[:] labels,
        DTYPE_t[:, :] label_weights
        cmap[ITYPE_t, ITYPE_t] labels_to_index
        WeightingStrategy weight_type

    def __init__(
        self,
        X,
        Y,
        ITYPE_t k,
        bint use_squared_distances=False,
        chunk_size=None,
        strategy=None,
        metric_kwargs=None,
        weights=None,
        labels=None,
    ):
        super().__init__(
            X=X, Y=Y, k=k,
            use_squared_distances=use_squared_distances,
            chunk_size=chunk_size,
            strategy=strategy,
            metric_kwargs=metric_kwargs,
        )
        if weights == "uniform":
            self.weight_type = WeightingStrategy.uniform
        elif weights == "distance":
            self.weight_type = WeightingStrategy.distance
        else:
            self.weight_type = WeightingStrategy.other
        self.labels = labels

        cdef ITYPE_t[:] unique_labels = np.unique(labels)

        cdef ITYPE_t idx, label
        # Map from set of unique labels to their indices in `label_weights`
        for idx, label in enumerate(unique_labels):
            self.labels_to_index.insert(pair[ITYPE_t, ITYPE_t](label, idx))

        # Buffer used in building a histogram for one-pass weighted mode
        self.label_weights = np.zeros((self.n_samples_X,  len(unique_labels)), dtype=DTYPE)

    def _finalize_results(self):
        probabilities = np.asarray(self.label_weights)
        probabilities /= probabilities.sum(axis=1, keepdims=True)
        return probabilities

    cdef inline void weighted_histogram_mode(
        self,
        ITYPE_t sample_index,
        ITYPE_t* indices,
        DTYPE_t* distances,
   ) nogil:
        cdef:
            ITYPE_t y_idx, label, label_index, multi_output_index
            DTYPE_t label_weight = 1

        # Iterate through the sample k-nearest neighbours
        for jdx in range(self.k):
            # Absolute indice of the jdx-th Nearest Neighbors
            # in range [0, n_samples_Y)
            if self.weight_type == WeightingStrategy.distance:
                label_weight = 1 / distances[jdx]
            y_idx = indices[jdx]
            label = self.labels[y_idx]
            label_index = self.labels_to_index[label]
            self.label_weights[sample_index][label_index] += label_weight
        return

    cdef void _parallel_on_X_prange_iter_finalize(
        self,
        ITYPE_t thread_num,
        ITYPE_t X_start,
        ITYPE_t X_end,
    ) nogil:
        cdef:
            ITYPE_t idx, sample_index
        # Sorting the main heaps portion associated to `X[X_start:X_end]`
        # in ascending order w.r.t the distances.
        for idx in range(X_end - X_start):
            simultaneous_sort(
                self.heaps_r_distances_chunks[thread_num] + idx * self.k,
                self.heaps_indices_chunks[thread_num] + idx * self.k,
                self.k
            )
            # One-pass top-one weighted mode
            # Compute the absolute index in [0, n_samples_X)
            sample_index = X_start + idx
            max_label_weight = -1
            self.weighted_histogram_mode(
                sample_index,
                &self.heaps_indices_chunks[thread_num][0],
                &self.heaps_r_distances_chunks[thread_num][0],
            )
        return

    cdef void _parallel_on_Y_finalize(
        self,
    ) nogil:
        cdef:
            ITYPE_t sample_index, thread_num

        with nogil, parallel(num_threads=self.chunks_n_threads):
            # Deallocating temporary datastructures
            for thread_num in prange(self.chunks_n_threads, schedule='static'):
                free(self.heaps_r_distances_chunks[thread_num])
                free(self.heaps_indices_chunks[thread_num])

            # Sorting the main in ascending order w.r.t the distances.
            # This is done in parallel sample-wise (no need for locks).
            for sample_index in prange(self.n_samples_X, schedule='static'):
                simultaneous_sort(
                    &self.argkmin_distances[sample_index, 0],
                    &self.argkmin_indices[sample_index, 0],
                    self.k,
                )
                self.weighted_histogram_mode(
                    sample_index,
                    &self.argkmin_indices[sample_index][0],
                    &self.argkmin_distances[sample_index][0],
                )
        return
