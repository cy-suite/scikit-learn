
from cython cimport floating, integral
from cython.parallel cimport parallel, prange
from libcpp.map cimport map as cmap, pair
from libcpp.vector cimport vector
from libc.stdlib cimport free

cimport numpy as cnp

cnp.import_array()

from ...utils._typedefs cimport ITYPE_t, DTYPE_t
from ...utils._typedefs import ITYPE, DTYPE
from ...utils._sorting cimport simultaneous_sort
import numpy as np

from sklearn.utils.fixes import threadpool_limits

cpdef enum WeightingStrategy:
    uniform = 0
    distance = 1
    other = 2

cdef struct FakeMemView:
    DTYPE_t * data
    ITYPE_t ncols

def _normalize(arr):
    arr /= arr.sum(axis=1, keepdims=True)
    return arr
from ._argkmin cimport PairwiseDistancesArgKmin64
from ._datasets_pair cimport DatasetsPair64

cdef class PairwiseDistancesArgKminLabels64(PairwiseDistancesArgKmin64):
    """
    64bit implementation of PairwiseDistancesArgKminLabel.
    """
    cdef:
        ITYPE_t n_outputs
        const ITYPE_t[:, :] labels,
        vector[FakeMemView] label_weights
        vector[cmap[ITYPE_t, ITYPE_t]] labels_to_index
        WeightingStrategy weight_type
        list label_weights_ndarrays

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
        :class:`PairwiseDistancesArgKmin64`.

        This allows decoupling the API entirely from the implementation details
        whilst maintaining RAII: all temporarily allocated datastructures necessary
        for the concrete implementation are therefore freed when this classmethod
        returns.

        No instance should directly be created outside of this class method.
        """
        pda = PairwiseDistancesArgKminLabels64(
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
        const ITYPE_t[:, :] labels,
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
        self.n_outputs = labels.shape[1]

        cdef:
            ITYPE_t idx, jdx, label
            FakeMemView mview
            ITYPE_t[:] unique_labels
            cmap[ITYPE_t, ITYPE_t] label_map
        self.label_weights_ndarrays = []

        for idx in range(self.n_outputs):
            unique_labels = np.unique(self.labels[:, idx])
            label_map = cmap[ITYPE_t, ITYPE_t]()

            # Map from set of unique labels to their indices in `label_weights`
            for jdx, label in enumerate(unique_labels):
                label_map.insert(pair[ITYPE_t, ITYPE_t](label, jdx))
            self.labels_to_index.push_back(label_map)

            # Buffer used in building a histogram for one-pass weighted mode
            self.label_weights_ndarrays.append(np.zeros((self.n_samples_X,  len(unique_labels)), dtype=DTYPE))
            mview.data = <DTYPE_t*>&(<cnp.ndarray>self.label_weights_ndarrays[idx]).data[0]
            mview.ncols = len(unique_labels)
            self.label_weights.push_back(mview)

    def _finalize_results(self):
        cdef Py_ssize_t idx
        probabilities = [_normalize(self.label_weights_ndarrays[idx]) for idx in range(self.n_outputs)]
        return probabilities

    cdef inline void weighted_histogram_mode(
        self,
        ITYPE_t sample_index,
        ITYPE_t* indices,
        DTYPE_t* distances,
   ) nogil:
        cdef:
            ITYPE_t y_idx, jdx, kdx, label, label_index
            DTYPE_t label_weight = 1
            FakeMemView mview

        # Iterate through the sample k-nearest neighbours
        for jdx in range(self.k):
            # Absolute indice of the jdx-th Nearest Neighbors
            # in range [0, n_samples_Y)
            if self.weight_type == WeightingStrategy.distance:
                label_weight = 1 / distances[jdx]
            y_idx = indices[jdx]
            for kdx in range(self.n_outputs):
                label = self.labels[y_idx, kdx]
                label_index = self.labels_to_index[kdx][label]
                mview = self.label_weights[kdx]
                mview.data[mview.ncols * sample_index + label_index] += label_weight

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
from ._argkmin cimport PairwiseDistancesArgKmin32
from ._datasets_pair cimport DatasetsPair32

cdef class PairwiseDistancesArgKminLabels32(PairwiseDistancesArgKmin32):
    """
    32bit implementation of PairwiseDistancesArgKminLabel.
    """
    cdef:
        ITYPE_t n_outputs
        const ITYPE_t[:, :] labels,
        vector[FakeMemView] label_weights
        vector[cmap[ITYPE_t, ITYPE_t]] labels_to_index
        WeightingStrategy weight_type
        list label_weights_ndarrays

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
        :class:`PairwiseDistancesArgKmin32`.

        This allows decoupling the API entirely from the implementation details
        whilst maintaining RAII: all temporarily allocated datastructures necessary
        for the concrete implementation are therefore freed when this classmethod
        returns.

        No instance should directly be created outside of this class method.
        """
        pda = PairwiseDistancesArgKminLabels32(
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
        const ITYPE_t[:, :] labels,
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
        self.n_outputs = labels.shape[1]

        cdef:
            ITYPE_t idx, jdx, label
            FakeMemView mview
            ITYPE_t[:] unique_labels
            cmap[ITYPE_t, ITYPE_t] label_map
        self.label_weights_ndarrays = []

        for idx in range(self.n_outputs):
            unique_labels = np.unique(self.labels[:, idx])
            label_map = cmap[ITYPE_t, ITYPE_t]()

            # Map from set of unique labels to their indices in `label_weights`
            for jdx, label in enumerate(unique_labels):
                label_map.insert(pair[ITYPE_t, ITYPE_t](label, jdx))
            self.labels_to_index.push_back(label_map)

            # Buffer used in building a histogram for one-pass weighted mode
            self.label_weights_ndarrays.append(np.zeros((self.n_samples_X,  len(unique_labels)), dtype=DTYPE))
            mview.data = <DTYPE_t*>&(<cnp.ndarray>self.label_weights_ndarrays[idx]).data[0]
            mview.ncols = len(unique_labels)
            self.label_weights.push_back(mview)

    def _finalize_results(self):
        cdef Py_ssize_t idx
        probabilities = [_normalize(self.label_weights_ndarrays[idx]) for idx in range(self.n_outputs)]
        return probabilities

    cdef inline void weighted_histogram_mode(
        self,
        ITYPE_t sample_index,
        ITYPE_t* indices,
        DTYPE_t* distances,
   ) nogil:
        cdef:
            ITYPE_t y_idx, jdx, kdx, label, label_index
            DTYPE_t label_weight = 1
            FakeMemView mview

        # Iterate through the sample k-nearest neighbours
        for jdx in range(self.k):
            # Absolute indice of the jdx-th Nearest Neighbors
            # in range [0, n_samples_Y)
            if self.weight_type == WeightingStrategy.distance:
                label_weight = 1 / distances[jdx]
            y_idx = indices[jdx]
            for kdx in range(self.n_outputs):
                label = self.labels[y_idx, kdx]
                label_index = self.labels_to_index[kdx][label]
                mview = self.label_weights[kdx]
                mview.data[mview.ncols * sample_index + label_index] += label_weight

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
