cimport numpy as cnp

from cython cimport final

from ._datasets_pair cimport DatasetsPair

cnp.import_array()


cpdef cnp.float64_t[::1] _sqeuclidean_row_norms64(
    const cnp.float64_t[:, ::1] X,
    cnp.intp_t num_threads,
)

cdef class PairwiseDistancesReduction64:
    """Base 64bit implementation of PairwiseDistancesReduction."""

    cdef:
        readonly DatasetsPair datasets_pair

        # The number of threads that can be used is stored in effective_n_threads.
        #
        # The number of threads to use in the parallelization strategy
        # (i.e. parallel_on_X or parallel_on_Y) can be smaller than effective_n_threads:
        # for small datasets, fewer threads might be needed to loop over pair of chunks.
        #
        # Hence, the number of threads that _will_ be used for looping over chunks
        # is stored in chunks_n_threads, allowing solely using what we need.
        #
        # Thus, an invariant is:
        #
        #                 chunks_n_threads <= effective_n_threads
        #
        cnp.intp_t effective_n_threads
        cnp.intp_t chunks_n_threads

        cnp.intp_t n_samples_chunk, chunk_size

        cnp.intp_t n_samples_X, X_n_samples_chunk, X_n_chunks, X_n_samples_last_chunk
        cnp.intp_t n_samples_Y, Y_n_samples_chunk, Y_n_chunks, Y_n_samples_last_chunk

        bint execute_in_parallel_on_Y

    @final
    cdef void _parallel_on_X(self) nogil

    @final
    cdef void _parallel_on_Y(self) nogil

    # Placeholder methods which have to be implemented

    cdef void _compute_and_reduce_distances_on_chunks(
        self,
        cnp.intp_t X_start,
        cnp.intp_t X_end,
        cnp.intp_t Y_start,
        cnp.intp_t Y_end,
        cnp.intp_t thread_num,
    ) nogil


    # Placeholder methods which can be implemented

    cdef void compute_exact_distances(self) nogil

    cdef void _parallel_on_X_parallel_init(
        self,
        cnp.intp_t thread_num,
    ) nogil

    cdef void _parallel_on_X_init_chunk(
        self,
        cnp.intp_t thread_num,
        cnp.intp_t X_start,
        cnp.intp_t X_end,
    ) nogil

    cdef void _parallel_on_X_pre_compute_and_reduce_distances_on_chunks(
        self,
        cnp.intp_t X_start,
        cnp.intp_t X_end,
        cnp.intp_t Y_start,
        cnp.intp_t Y_end,
        cnp.intp_t thread_num,
    ) nogil

    cdef void _parallel_on_X_prange_iter_finalize(
        self,
        cnp.intp_t thread_num,
        cnp.intp_t X_start,
        cnp.intp_t X_end,
    ) nogil

    cdef void _parallel_on_X_parallel_finalize(
        self,
        cnp.intp_t thread_num
    ) nogil

    cdef void _parallel_on_Y_init(
        self,
    ) nogil

    cdef void _parallel_on_Y_parallel_init(
        self,
        cnp.intp_t thread_num,
        cnp.intp_t X_start,
        cnp.intp_t X_end,
    ) nogil

    cdef void _parallel_on_Y_pre_compute_and_reduce_distances_on_chunks(
        self,
        cnp.intp_t X_start,
        cnp.intp_t X_end,
        cnp.intp_t Y_start,
        cnp.intp_t Y_end,
        cnp.intp_t thread_num,
    ) nogil

    cdef void _parallel_on_Y_synchronize(
        self,
        cnp.intp_t X_start,
        cnp.intp_t X_end,
    ) nogil

    cdef void _parallel_on_Y_finalize(
        self,
    ) nogil
