# cython: cdivision=True
# cython: boundscheck=False
# cython: wraparound=False
# cython: language_level=3
from .common cimport BITSET_INNER_DTYPE_C
from .common cimport BITSET_DTYPE_C
from .common cimport X_DTYPE_C
from .common cimport X_BINNED_DTYPE_C

cdef inline void init_bitset(BITSET_DTYPE_C bitset) nogil: # OUT
    cdef:
        unsigned int i

    for i in range(8):
        bitset[i] = 0


cdef inline void set_bitset(BITSET_DTYPE_C bitset,  # OUT
                            X_BINNED_DTYPE_C val) nogil:
    bitset[val // 32] |= (1 << (val % 32))


cdef inline unsigned char in_bitset(BITSET_DTYPE_C bitset,
                                    X_BINNED_DTYPE_C val) nogil:

    return (bitset[val // 32] >> (val % 32)) & 1


cpdef inline unsigned char in_bitset_memoryview(const BITSET_INNER_DTYPE_C[:] bitset,
                                                X_BINNED_DTYPE_C val) nogil:
    return (bitset[val // 32] >> (val % 32)) & 1


cpdef inline void set_bitset_memoryview(BITSET_INNER_DTYPE_C[:] bitset,  # OUT
                                        X_BINNED_DTYPE_C val):
    bitset[val // 32] |= (1 << (val % 32))


def set_raw_bitset_from_binned_bitset(BITSET_INNER_DTYPE_C[:] raw_bitset,  # OUT
                                      BITSET_INNER_DTYPE_C[:] binned_bitset,
                                      X_DTYPE_C[:] categories):
    """Set the raw_bitset from the values of the binned bitset
    
    categories is a mapping from binned category value to raw category value.
    """
    cdef:
        int binned_cat_value, raw_cat_value
    
    for binned_cat_value, raw_cat_value in enumerate(categories):
        if in_bitset_memoryview(binned_bitset, binned_cat_value):
            set_bitset_memoryview(raw_bitset, raw_cat_value)
