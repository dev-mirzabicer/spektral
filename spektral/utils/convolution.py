import copy
import warnings
from functools import partial

import numpy as np
import tensorflow as tf
from scipy import linalg
from scipy import sparse as sp
from scipy.sparse.linalg import ArpackNoConvergence


def degree_matrix(A):
    """
    Computes the degree matrix of the given adjacency matrix.
    :param A: rank 2 array or sparse matrix.
    :return: if A is a dense array, a dense array; if A is sparse, a sparse
    matrix in DIA format.
    """
    if isinstance(A, tf.sparse.SparseTensor):
        return degree_matrix_tf(A)
    degrees = np.array(A.sum(1)).flatten()
    if sp.issparse(A):
        D = sp.diags(degrees)
    else:
        D = np.diag(degrees)
    return D

def degree_matrix_tf(A):
    """
    TensorFlow implementation of degree_matrix for SparseTensor input.
    
    :param A: tf.sparse.SparseTensor, the input adjacency matrix
    :return: tf.sparse.SparseTensor, the degree matrix
    """
    if not isinstance(A, tf.sparse.SparseTensor):
        raise ValueError("Input must be a TensorFlow SparseTensor")

    degrees = tf.sparse.reduce_sum(A, axis=1)
    n = tf.shape(A)[0]
    indices = tf.stack([tf.range(n, dtype=tf.int64), tf.range(n, dtype=tf.int64)], axis=1)
    
    return tf.sparse.SparseTensor(
        indices=indices,
        values=degrees,
        dense_shape=[n, n]
    )

def degree_power(A, k):
    r"""
    Computes \(\D^{k}\) from the given adjacency matrix. Useful for computing
    normalised Laplacian.
    :param A: rank 2 array or sparse matrix.
    :param k: exponent to which elevate the degree matrix.
    :return: if A is a dense array, a dense array; if A is sparse, a sparse
    matrix in DIA format.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        degrees = np.power(np.array(A.sum(1)), k).ravel()
    degrees[np.isinf(degrees)] = 0.0
    if sp.issparse(A):
        D = sp.diags(degrees)
    else:
        D = np.diag(degrees)
    return D


def normalized_adjacency(A, symmetric=True):
    r"""
    Normalizes the given adjacency matrix using the degree matrix as either
    \(\D^{-1}\A\) or \(\D^{-1/2}\A\D^{-1/2}\) (symmetric normalization).
    :param A: rank 2 array or sparse matrix;
    :param symmetric: boolean, compute symmetric normalization;
    :return: the normalized adjacency matrix.
    """
    if isinstance(A, tf.sparse.SparseTensor):
        return normalized_adjacency_tf(A, symmetric)
    if symmetric:
        normalized_D = degree_power(A, -0.5)
        return normalized_D.dot(A).dot(normalized_D)
    else:
        normalized_D = degree_power(A, -1.0)
        return normalized_D.dot(A)

def normalized_adjacency_tf(A, symmetric=True):
    """
    TensorFlow implementation of normalized_adjacency for SparseTensor input.
    
    :param A: tf.sparse.SparseTensor, the input adjacency matrix
    :param symmetric: boolean, compute symmetric normalization
    :return: tf.sparse.SparseTensor, the normalized adjacency matrix
    """
    if not isinstance(A, tf.sparse.SparseTensor):
        raise ValueError("Input must be a TensorFlow SparseTensor")

    # Compute degree
    D = tf.cast(tf.sparse.reduce_sum(A, axis=1), dtype=tf.float32)
    A = tf.cast(A, dtype=tf.float32)

    if symmetric:
        # Symmetric normalization: D^(-1/2) * A * D^(-1/2)
        D_inv_sqrt = tf.pow(D, -0.5)
        D_inv_sqrt = tf.where(tf.math.is_inf(D_inv_sqrt), tf.zeros_like(D_inv_sqrt), D_inv_sqrt)
        
        D_inv_sqrt_i = tf.gather(D_inv_sqrt, A.indices[:, 0])
        D_inv_sqrt_j = tf.gather(D_inv_sqrt, A.indices[:, 1])
        
        normalized_values = D_inv_sqrt_i * A.values * D_inv_sqrt_j
    else:
        # Asymmetric normalization: D^(-1) * A
        D_inv = tf.pow(D, -1)
        D_inv = tf.where(tf.math.is_inf(D_inv), tf.zeros_like(D_inv), D_inv)
        
        D_inv_i = tf.gather(D_inv, A.indices[:, 0])
        
        normalized_values = D_inv_i * A.values

    return tf.sparse.SparseTensor(
        indices=A.indices,
        values=normalized_values,
        dense_shape=A.dense_shape
    )

def laplacian(A):
    r"""
    Computes the Laplacian of the given adjacency matrix as \(\D - \A\).
    :param A: rank 2 array or sparse matrix;
    :return: the Laplacian.
    """
    if isinstance(A, tf.sparse.SparseTensor):
        return tf.sparse.add(degree_matrix_tf(A), tf.sparse.map_values(tf.negative, A))
    return degree_matrix(A) - A

def normalized_laplacian_tf(A, symmetric=True):
    """
    TensorFlow implementation of normalized_laplacian for SparseTensor input.
    
    :param A: tf.sparse.SparseTensor, the input adjacency matrix
    :param symmetric: boolean, compute symmetric normalization
    :return: tf.sparse.SparseTensor, the normalized Laplacian
    """
    if not isinstance(A, tf.sparse.SparseTensor):
        raise ValueError("Input must be a TensorFlow SparseTensor")

    n = tf.shape(A)[0]
    normalized_adj = normalized_adjacency_tf(A, symmetric=symmetric)
    I = tf.sparse.eye(n, dtype=normalized_adj.dtype)
    return tf.sparse.add(I, tf.sparse.map_values(tf.negative, normalized_adj))

def normalized_laplacian(A, symmetric=True):
    r"""
    Computes a  normalized Laplacian of the given adjacency matrix as
    \(\I - \D^{-1}\A\) or \(\I - \D^{-1/2}\A\D^{-1/2}\) (symmetric normalization).
    :param A: rank 2 array or sparse matrix;
    :param symmetric: boolean, compute symmetric normalization;
    :return: the normalized Laplacian.
    """
    if isinstance(A, tf.sparse.SparseTensor):
        return normalized_laplacian_tf(A, symmetric)
    if sp.issparse(A):
        I = sp.eye(A.shape[-1], dtype=A.dtype)
    else:
        I = np.eye(A.shape[-1], dtype=A.dtype)
    normalized_adj = normalized_adjacency(A, symmetric=symmetric)
    return I - normalized_adj


def rescale_laplacian(L, lmax=None):
    """
    Rescales the Laplacian eigenvalues in [-1,1], using lmax as largest eigenvalue.
    :param L: rank 2 array or sparse matrix;
    :param lmax: if None, compute largest eigenvalue with scipy.linalg.eisgh.
    If the eigendecomposition fails, lmax is set to 2 automatically.
    If scalar, use this value as largest eigenvalue when rescaling.
    :return:
    """
    if isinstance(L, tf.sparse.SparseTensor):
        return rescale_laplacian_tf(L)
    if lmax is None:
        try:
            if sp.issparse(L):
                lmax = sp.linalg.eigsh(L, 1, which="LM", return_eigenvectors=False)[0]
            else:
                n = L.shape[-1]
                lmax = linalg.eigh(L, eigvals_only=True, eigvals=[n - 2, n - 1])[-1]
        except ArpackNoConvergence:
            lmax = 2
    if sp.issparse(L):
        I = sp.eye(L.shape[-1], dtype=L.dtype)
    else:
        I = np.eye(L.shape[-1], dtype=L.dtype)
    L_scaled = (2.0 / lmax) * L - I
    return L_scaled

def gcn_filter_tf(A, symmetric=True):
    """
    TensorFlow implementation of gcn_filter for SparseTensor input.
    
    :param A: tf.sparse.SparseTensor, the input adjacency matrix
    :param symmetric: boolean, whether to normalize the matrix as
        D^(-1/2) * A * D^(-1/2) (symmetric=True) or as D^(-1) * A (symmetric=False)
    :return: tf.sparse.SparseTensor, the filtered adjacency matrix
    """
    if not isinstance(A, tf.sparse.SparseTensor):
        raise ValueError("Input must be a TensorFlow SparseTensor")

    # Add self-loops
    n = tf.shape(A)[0]
    A = tf.cast(A, dtype=tf.float32)
    edge_index = tf.concat([A.indices, tf.stack([tf.range(n, dtype=A.indices.dtype), tf.range(n, dtype=A.indices.dtype)], axis=1)], axis=0)
    edge_weight = tf.concat([A.values, tf.ones(n, dtype=A.values.dtype)], axis=0)
    
    A_hat = tf.sparse.SparseTensor(
        indices=edge_index,
        values=edge_weight,
        dense_shape=[n, n]
    )
    A_hat = tf.sparse.reorder(A_hat)  # Ensure the SparseTensor is ordered

    # Compute node degrees
    D = tf.cast(tf.sparse.reduce_sum(A_hat, axis=1), dtype=tf.float32)

    if symmetric:
        # Symmetric normalization: D^(-1/2) * A * D^(-1/2)
        D_inv_sqrt = tf.pow(D, -0.5)
        D_inv_sqrt = tf.where(tf.math.is_inf(D_inv_sqrt), tf.zeros_like(D_inv_sqrt), D_inv_sqrt)
        
        # Use tf.gather to index into D_inv_sqrt
        D_inv_sqrt_i = tf.gather(D_inv_sqrt, A_hat.indices[:, 0])
        D_inv_sqrt_j = tf.gather(D_inv_sqrt, A_hat.indices[:, 1])
        
        edge_weight_norm = D_inv_sqrt_i * A_hat.values * D_inv_sqrt_j
        
        return tf.sparse.SparseTensor(
            indices=A_hat.indices,
            values=edge_weight_norm,
            dense_shape=A_hat.dense_shape
        )
    else:
        # Asymmetric normalization: D^(-1) * A
        D_inv = tf.pow(D, -1)
        D_inv = tf.where(tf.math.is_inf(D_inv), tf.zeros_like(D_inv), D_inv)
        
        # Use tf.gather to index into D_inv
        D_inv_i = tf.gather(D_inv, A_hat.indices[:, 0])
        
        edge_weight_norm = D_inv_i * A_hat.values
        
        return tf.sparse.SparseTensor(
            indices=A_hat.indices,
            values=edge_weight_norm,
            dense_shape=A_hat.dense_shape
        )


def gcn_filter(A, symmetric=True):
    r"""
    Computes the graph filter described in
    [Kipf & Welling (2017)](https://arxiv.org/abs/1609.02907).
    :param A: array or sparse matrix with rank 2 or 3;
    :param symmetric: boolean, whether to normalize the matrix as
    \(\D^{-\frac{1}{2}}\A\D^{-\frac{1}{2}}\) or as \(\D^{-1}\A\);
    :return: array or sparse matrix with rank 2 or 3, same as A;
    """
    if isinstance(A, tf.sparse.SparseTensor):
        return gcn_filter_tf(A, symmetric)
    out = copy.deepcopy(A)
    if isinstance(A, list) or (isinstance(A, np.ndarray) and A.ndim == 3):
        for i in range(len(A)):
            out[i] = A[i]
            out[i][np.diag_indices_from(out[i])] += 1
            out[i] = normalized_adjacency(out[i], symmetric=symmetric)
    else:
        if hasattr(out, "tocsr"):
            out = out.tocsr()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            out[np.diag_indices_from(out)] += 1
        out = normalized_adjacency(out, symmetric=symmetric)

    if sp.issparse(out):
        out.sort_indices()
    return out


def _triangular_adjacency(adjacency):
    """
    Gets the triangular version of the adjacency matrix, removing redundant
    values.

    :param adjacency: The full adjacency matrix, with shape
        ([batch], n_nodes, n_nodes).
    :return: The upper triangle of the adjacency matrix, with the lower
        triangle set to zero.
    """
    return tf.linalg.band_part(adjacency, 0, -1)


def _incidence_matrix_single(triangular_adjacency, *, num_edges):
    """
    Creates the corresponding incidence matrix for a graph with a particular
    adjacency matrix.

    :param triangular_adjacency: The binary adjacency matrix. Should have shape
        (n_nodes, n_nodes), and be triangular.
    :param num_edges: The number of edges to use in the output. Should be large
        enough to accommodate all the edges in the adjacency matrix.

    :return: The computed incidence matrix. It will have a shape of
        (n_nodes, n_edges).
    """
    # The adjacency matrix should be sparse, so get the indices of the edges.
    connected_node_indices = tf.where(triangular_adjacency)

    # Match each edge with one of the nodes connected by that edge. We refer
    # to the two nodes connected by each edge as "right" and "left",
    # for convenience.
    edge_indices = tf.range(connected_node_indices.shape[0], dtype=tf.int64)
    edges_with_left_nodes = tf.stack(
        [connected_node_indices[:, 0], edge_indices], axis=1
    )
    edges_with_right_nodes = tf.stack(
        [connected_node_indices[:, 1], edge_indices], axis=1
    )

    # We now have all the points that should go in the sparse binary
    # transformation matrix.
    edge_indicators = tf.ones_like(edge_indices, dtype=tf.float32)
    num_nodes = tf.cast(tf.shape(triangular_adjacency)[0], tf.int64)
    output_shape = tf.stack([num_nodes, num_edges])
    left_sparse = tf.SparseTensor(
        indices=edges_with_left_nodes, values=edge_indicators, dense_shape=output_shape
    )
    left_sparse = tf.sparse.reorder(left_sparse)
    right_sparse = tf.SparseTensor(
        indices=edges_with_right_nodes, values=edge_indicators, dense_shape=output_shape
    )
    right_sparse = tf.sparse.reorder(right_sparse)
    # Combine the matrices for the left and right nodes.
    combined_sparse = tf.sparse.maximum(left_sparse, right_sparse)

    return tf.sparse.to_dense(combined_sparse)


def incidence_matrix(adjacency):
    """
    Creates the corresponding incidence matrices for graphs with particular
    adjacency matrices.

    :param adjacency: The binary adjacency matrices. Should have shape
        ([batch], n_nodes, n_nodes).
    :return: The computed incidence matrices. It will have a shape of
        ([batch], n_nodes, n_edges).
    """
    adjacency = tf.convert_to_tensor(adjacency, dtype=tf.float32)
    added_batch = False
    if tf.size(tf.shape(adjacency)) == 2:
        # Add the extra batch dimension if needed.
        adjacency = tf.expand_dims(adjacency, axis=0)
        added_batch = True

    # Compute the maximum number of edges. We will pad everything in the
    # batch to this dimension.
    adjacency_upper = _triangular_adjacency(adjacency)
    num_edges = tf.math.count_nonzero(adjacency_upper, axis=(1, 2))
    max_num_edges = tf.reduce_max(num_edges)

    # Compute all the transformation matrices.
    make_single_matrix = partial(_incidence_matrix_single, num_edges=max_num_edges)
    transformation_matrices = tf.map_fn(
        make_single_matrix,
        adjacency_upper,
        fn_output_signature=tf.TensorSpec(shape=[None, None], dtype=tf.float32),
    )

    if added_batch:
        # Remove the extra batch dimension before returning.
        transformation_matrices = transformation_matrices[0]
    return transformation_matrices


def line_graph(incidence):
    """
    Creates the line graph adjacency matrices for graphs with particular
    incidence matrices.
    :param incidence: The incidence matrices. Should have shape
        ([batch], n_nodes, n_edges).
    :return: The computed line graph adjacency matrices. It will have a shape
        of ([batch], n_edges, n_edges).
    """
    incidence = tf.convert_to_tensor(incidence, dtype=tf.float32)

    incidence_t = tf.linalg.matrix_transpose(incidence)
    incidence_sq = tf.matmul(incidence_t, incidence)

    num_rows = tf.shape(incidence_sq)[-2]
    identity = tf.eye(num_rows)
    return incidence_sq - identity * 2

def chebyshev_polynomial_tf(X, k):
    """
    TensorFlow implementation of chebyshev_polynomial for SparseTensor input.
    
    :param X: tf.sparse.SparseTensor, input matrix
    :param k: integer, the order up to which compute the polynomials
    :return: a list of k + 1 SparseTensors with one element for each degree of the polynomial
    """
    if not isinstance(X, tf.sparse.SparseTensor):
        raise ValueError("Input must be a TensorFlow SparseTensor")

    T_k = []
    n = tf.shape(X)[0]
    
    # T_0 = I
    T_k.append(tf.sparse.eye(n, dtype=X.dtype))
    
    # T_1 = X
    T_k.append(X)

    def chebyshev_recurrence(T_k_minus_one, T_k_minus_two, X):
        return 2 * tf.sparse.sparse_dense_matmul(X, T_k_minus_one) - T_k_minus_two

    for _ in range(2, k + 1):
        T_k.append(chebyshev_recurrence(T_k[-1], T_k[-2], X))

    return T_k

def chebyshev_polynomial(X, k):
    """
    Calculates Chebyshev polynomials of X, up to order k.
    :param X: rank 2 array or sparse matrix;
    :param k: the order up to which compute the polynomials,
    :return: a list of k + 1 arrays or sparse matrices with one element for each
    degree of the polynomial.
    """
    if isinstance(X, tf.sparse.SparseTensor):
        return chebyshev_polynomial_tf(X, k)
    T_k = list()
    if sp.issparse(X):
        T_k.append(sp.eye(X.shape[0], dtype=X.dtype).tocsr())
    else:
        T_k.append(np.eye(X.shape[0], dtype=X.dtype))
    T_k.append(X)

    def chebyshev_recurrence(T_k_minus_one, T_k_minus_two, X):
        if sp.issparse(X):
            X_ = sp.csr_matrix(X, copy=True)
        else:
            X_ = np.copy(X)
        return 2 * X_.dot(T_k_minus_one) - T_k_minus_two

    for _ in range(2, k + 1):
        T_k.append(chebyshev_recurrence(T_k[-1], T_k[-2], X))

    return T_k


def chebyshev_filter(A, k, symmetric=True):
    r"""
    Computes the Chebyshev filter from the given adjacency matrix, as described
    in [Defferrard et at. (2016)](https://arxiv.org/abs/1606.09375).
    :param A: rank 2 array or sparse matrix;
    :param k: integer, the order of the Chebyshev polynomial;
    :param symmetric: boolean, whether to normalize the matrix as
    \(\D^{-\frac{1}{2}}\A\D^{-\frac{1}{2}}\) or as \(\D^{-1}\A\);
    :return: a list of k + 1 arrays or sparse matrices with one element for each
    degree of the polynomial.
    """
    if isinstance(A, tf.sparse.SparseTensor):
        return chebyshev_filter_tf(A, k, symmetric)
    normalized_adj = normalized_adjacency(A, symmetric)
    if sp.issparse(A):
        I = sp.eye(A.shape[0], dtype=A.dtype)
    else:
        I = np.eye(A.shape[0], dtype=A.dtype)
    L = I - normalized_adj  # Compute Laplacian

    # Rescale Laplacian
    L_scaled = rescale_laplacian(L)

    # Compute Chebyshev polynomial approximation
    T_k = chebyshev_polynomial(L_scaled, k)

    # Sort indices
    if sp.issparse(T_k[0]):
        for i in range(len(T_k)):
            T_k[i].sort_indices()

    return T_k

def chebyshev_filter_tf(A, k, symmetric=True):
    """
    TensorFlow implementation of chebyshev_filter for SparseTensor input.
    
    :param A: tf.sparse.SparseTensor, the input adjacency matrix
    :param k: integer, the order of the Chebyshev polynomial
    :param symmetric: boolean, whether to use symmetric normalization
    :return: a list of k + 1 SparseTensors with one element for each degree of the polynomial
    """
    if not isinstance(A, tf.sparse.SparseTensor):
        raise ValueError("Input must be a TensorFlow SparseTensor")

    normalized_adj = normalized_adjacency_tf(A, symmetric)
    n = tf.shape(A)[0]
    I = tf.sparse.eye(n, dtype=A.dtype)
    L = tf.sparse.add(I, tf.sparse.map_values(tf.negative, normalized_adj))  # Compute Laplacian

    # Rescale Laplacian
    L_scaled = rescale_laplacian_tf(L)

    # Compute Chebyshev polynomial approximation
    T_k = chebyshev_polynomial_tf(L_scaled, k)

    return T_k

def rescale_laplacian_tf(L):
    """
    Rescale the Laplacian eigenvalues to [-1, 1].
    """
    max_eigenval = tf.sparse.reduce_max(L)
    scaled_L = tf.sparse.map_values(lambda x: 2.0 * x / max_eigenval, L)
    return tf.sparse.add(scaled_L, tf.sparse.map_values(tf.negative, tf.sparse.eye(tf.shape(L)[0], dtype=L.dtype)))

def add_self_loops(a, value=1):
    """
    Sets the inner diagonals of `a` to `value`.
    :param a: a np.array or scipy.sparse matrix, the innermost two dimensions
    must be equal.
    :param value: value to set the diagonals to.
    :return: a np.array or scipy.sparse matrix with the same shape as `a`.
    """
    a = a.copy()
    if len(a.shape) < 2:
        raise ValueError("a must have at least rank 2")
    n = a.shape[-1]
    if n != a.shape[-2]:
        raise ValueError(
            "Innermost two dimensions must be equal. Got {}".format(a.shape)
        )
    if sp.issparse(a):
        a = a.tolil()
        a.setdiag(value)
        return a.tocsr()
    else:
        idx = np.arange(n)
        a[..., idx, idx] = value
        return a
