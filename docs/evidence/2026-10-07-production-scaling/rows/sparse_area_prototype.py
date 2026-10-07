"""External finite-float32 experiment; not a default or CLI implementation."""
import numpy as np
from scipy.sparse import csr_matrix


def sparse_area_weights(n_in, n_out):
    scale = n_in/n_out
    starts = np.arange(n_out)*scale
    rows, cols = [], []
    for r, start in enumerate(starts):
        indices = range(max(0, int(np.floor(start))), min(n_in, int(np.ceil(start+scale))))
        cols.extend(indices)
        rows.extend([r]*len(indices))
    rows = np.asarray(rows, dtype=np.int64)
    cols = np.asarray(cols, dtype=np.int64)
    lo = np.maximum(cols, starts[rows])
    hi = np.minimum(cols+1, starts[rows]+scale)
    weights = (np.clip(hi-lo, 0, None)/scale).astype(np.float32)
    matrix = csr_matrix((weights, (rows, cols)), shape=(n_out, n_in))
    matrix.eliminate_zeros()
    return matrix


def sparse_area_resize(np, array, k):
    h, w = array.shape[0]//k, array.shape[1]//k
    y = sparse_area_weights(array.shape[0], h)
    x = sparse_area_weights(array.shape[1], w)
    return x.dot(y.dot(array).T).T
