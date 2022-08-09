cimport numpy as cnp

from libcpp.memory cimport shared_ptr
from libcpp.vector cimport vector
from cython cimport final

from ._base cimport (
    PairwiseDistancesReduction64,
)
from ._gemm_term_computer cimport GEMMTermComputer64

cnp.import_array()

######################
## std::vector to np.ndarray coercion
# As type covariance is not supported for C++ containers via Cython,
# we need to redefine fused types.
ctypedef fused vector_INTP_FLOAT64_t:
    vector[cnp.intp_t]
    vector[cnp.float64_t]


ctypedef fused vector_vector_INTP_FLOAT64_t:
    vector[vector[cnp.intp_t]]
    vector[vector[cnp.float64_t]]

cdef cnp.ndarray[object, ndim=1] coerce_vectors_to_nd_arrays(
    shared_ptr[vector_vector_INTP_FLOAT64_t] vecs
)

#####################

cdef class PairwiseDistancesRadiusNeighborhood64(PairwiseDistancesReduction64):
    """64bit implementation of PairwiseDistancesRadiusNeighborhood ."""

    cdef:
        cnp.float64_t radius

        # DistanceMetric compute rank-preserving surrogate distance via rdist
        # which are proxies necessitating less computations.
        # We get the equivalent for the radius to be able to compare it against
        # vectors' rank-preserving surrogate distances.
        cnp.float64_t r_radius

        # Neighbors indices and distances are returned as np.ndarrays of np.ndarrays.
        #
        # For this implementation, we want resizable buffers which we will wrap
        # into numpy arrays at the end. std::vector comes as a handy container
        # for interacting efficiently with resizable buffers.
        #
        # Though it is possible to access their buffer address with
        # std::vector::data, they can't be stolen: buffers lifetime
        # is tied to their std::vector and are deallocated when
        # std::vectors are.
        #
        # To solve this, we dynamically allocate std::vectors and then
        # encapsulate them in a StdVectorSentinel responsible for
        # freeing them when the associated np.ndarray is freed.
        #
        # Shared pointers (defined via shared_ptr) are use for safer memory management.
        # Unique pointers (defined via unique_ptr) can't be used as datastructures
        # are shared across threads for parallel_on_X; see _parallel_on_X_init_chunk.
        shared_ptr[vector[vector[cnp.intp_t]]] neigh_indices
        shared_ptr[vector[vector[cnp.float64_t]]] neigh_distances

        # Used as array of pointers to private datastructures used in threads.
        vector[shared_ptr[vector[vector[cnp.intp_t]]]] neigh_indices_chunks
        vector[shared_ptr[vector[vector[cnp.float64_t]]]] neigh_distances_chunks

        bint sort_results

    @final
    cdef void _merge_vectors(
        self,
        cnp.intp_t idx,
        cnp.intp_t num_threads,
    ) nogil


cdef class FastEuclideanPairwiseDistancesRadiusNeighborhood64(PairwiseDistancesRadiusNeighborhood64):
    """EuclideanDistance-specialized 64bit implementation for PairwiseDistancesRadiusNeighborhood."""
    cdef:
        GEMMTermComputer64 gemm_term_computer
        const cnp.float64_t[::1] X_norm_squared
        const cnp.float64_t[::1] Y_norm_squared

        bint use_squared_distances
