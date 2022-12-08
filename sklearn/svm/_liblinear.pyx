"""
Wrapper for liblinear

Author: fabian.pedregosa@inria.fr
"""

import  numpy as np
cimport numpy as cnp

from ..utils._cython_blas cimport _dot, _axpy, _scal, _nrm2

include "_liblinear.pxi"

cnp.import_array()


def train_wrap(
    object X,
    cnp.float64_t[::1] Y,
    bint is_sparse,
    int solver_type,
    double eps,
    double bias,
    double C,
    cnp.float64_t[:] class_weight,
    int max_iter,
    unsigned random_seed,
    double epsilon,
    cnp.float64_t[::1] sample_weight
):
    cdef parameter *param
    cdef problem *problem
    cdef model *model
    cdef char_const_ptr error_msg
    cdef int len_w

    # The implementation for float32 and float64 uses a single interface.
    # This is done by accepting the data as a pointer to a buffer of bytes.
    # In this regard, we define a pointer to pass the address of the first
    # element of the buffer seen as raw bytes (hence the use of `char *`).
    #
    # We proceed in two steps using intermediate memory views to have Cython
    # have sufficient typing information not to use PyObjects.
    cdef cnp.float64_t[::1] X_data_64
    cdef cnp.float32_t[::1] X_data_32
    cdef char * X_data_as_bytes_ptr = NULL

    # The same is done for `indices` and `indptr` in the CSR case.
    cdef cnp.int32_t[::1] X_indices
    cdef char * X_indices_as_bytes_ptr = NULL

    cdef cnp.int32_t[::1] X_indptr
    cdef char * X_indptr_as_bytes_ptr = NULL

    cdef bint X_stores_float64_data = X.dtype == np.float64

    if is_sparse:
        # X is a CSR matrix here, a format which stores the values
        # as a contiguous buffer via a NumPy array in a `data` attribute.
        # We get the address of the first element of the buffer which
        # we reference using a pointer to bytes.
        if X_stores_float64_data:
            X_data_64 = X.data
            X_data_as_bytes_ptr = <char*> &X_data_64[0]
        else:
            X_data_32 = X.data
            X_data_as_bytes_ptr = <char*> &X_data_32[0]

        # Similar operations are to be performed for `indices` and `indptr`.
        X_indices = X.indices
        X_indices_as_bytes_ptr = <char *> &X_indices[0]

        X_indptr = X.indptr
        X_indptr_as_bytes_ptr = <char *> &X_indptr[0]

        problem = csr_set_problem(
            # Underneath, the data will be statically re-interpreted as
            # either float32 or float64 depending on the boolean passed as
            # the second argument.
            X_data_as_bytes_ptr,
            X_stores_float64_data,
            X_indices_as_bytes_ptr,
            X_indptr_as_bytes_ptr,
            (<cnp.int32_t>X.shape[0]),
            (<cnp.int32_t>X.shape[1]),
            (<cnp.int32_t>X.nnz),
            bias,
            <char *> &sample_weight[0],
            <char *> &Y[0]
        )
    else:
        # X simply is a 2D NumPy array in this case.
        # This is reshapeable to a 1D NumPy array in O(1) (only strides are changed).
        if X_stores_float64_data:
            X_data_64 = X.reshape(-1)
            X_data_as_bytes_ptr = <char*> &X_data_64[0]
        else:
            X_data_32 = X.reshape(-1)
            X_data_as_bytes_ptr = <char*> &X_data_32[0]

        problem = set_problem(
            X_data_as_bytes_ptr,
            X.dtype == np.float64,
            (<cnp.int32_t>X.shape[0]),
            (<cnp.int32_t>X.shape[1]),
            (<cnp.int32_t>np.count_nonzero(X)),
            bias,
            <char *> &sample_weight[0],
            <char *> &Y[0]
        )

    cdef cnp.int32_t[::1] class_weight_label = np.arange(class_weight.shape[0], dtype=np.intc)
    param = set_parameter(
        solver_type,
        eps,
        C,
        class_weight.shape[0],
        <char*> &class_weight_label[0] if class_weight_label.size > 0 else NULL,
        <char*> &class_weight[0] if class_weight.size > 0 else NULL,
        max_iter,
        random_seed,
        epsilon
    )

    error_msg = check_parameter(problem, param)
    if error_msg:
        free_problem(problem)
        free_parameter(param)
        raise ValueError(error_msg)

    cdef BlasFunctions blas_functions
    blas_functions.dot = _dot[double]
    blas_functions.axpy = _axpy[double]
    blas_functions.scal = _scal[double]
    blas_functions.nrm2 = _nrm2[double]

    # early return
    with nogil:
        model = train(problem, param, &blas_functions)

    ### FREE
    free_problem(problem)
    free_parameter(param)
    # destroy_param(param)  don't call this or it will destroy class_weight_label and class_weight

    # coef matrix holder created as fortran since that's what's used in liblinear
    cdef cnp.float64_t[::1, :] w
    cdef int nr_class = get_nr_class(model)

    cdef int labels_ = nr_class
    if nr_class == 2:
        labels_ = 1
    cdef cnp.int32_t[::1] n_iter = np.zeros(labels_, dtype=np.intc)
    get_n_iter(model, <int *> &n_iter[0])

    cdef int nr_feature = get_nr_feature(model)
    if bias > 0: nr_feature = nr_feature + 1
    if nr_class == 2 and solver_type != 4:  # solver is not Crammer-Singer
        w = np.empty((1, nr_feature), order='F')
        copy_w(&w[0, 0], model, nr_feature)
    else:
        len_w = (nr_class) * nr_feature
        w = np.empty((nr_class, nr_feature), order='F')
        copy_w(&w[0, 0], model, len_w)

    free_and_destroy_model(&model)

    return w.base, n_iter.base


def set_verbosity_wrap(int verbosity):
    """
    Control verbosity of libsvm library
    """
    set_verbosity(verbosity)
