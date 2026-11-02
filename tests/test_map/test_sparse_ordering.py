"""Nested-dissection elimination order for operators on the spherical mesh."""

from __future__ import annotations

import numpy as np
import pytest
from scipy import sparse
from scipy.sparse.linalg import splu

from dreamulator.map.sparse_ordering import nested_dissection_order


def _sphere(n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fibonacci points on the unit sphere and their k-nearest-neighbour edges."""
    from scipy.spatial import cKDTree

    k = np.arange(n) + 0.5
    lat = np.arcsin(1.0 - 2.0 * k / n)
    lon = np.pi * (1.0 + 5.0**0.5) * k
    xyz = np.column_stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)])
    _, nearest = cKDTree(xyz).query(xyz, k=7)
    src = np.repeat(np.arange(n), 6)
    dst = nearest[:, 1:].ravel()
    return xyz, src, dst


def _operator(n: int, src: np.ndarray, dst: np.ndarray) -> sparse.csc_matrix:
    """A diagonally weighted graph Laplacian, symmetric in pattern like the budget."""
    rows = np.concatenate([src, dst, np.arange(n)])
    cols = np.concatenate([dst, src, np.arange(n)])
    vals = np.concatenate([-np.ones(2 * src.size), np.zeros(n)])
    a = sparse.coo_matrix((vals, (rows, cols)), shape=(n, n)).tocsr()
    a.sum_duplicates()
    degree = -np.asarray(a.sum(axis=1)).ravel()
    return (a + sparse.diags(degree + 0.05)).tocsc()


class TestNestedDissectionOrder:
    def test_is_a_permutation_and_deterministic(self) -> None:
        xyz, src, dst = _sphere(3000)
        first = nested_dissection_order(xyz, src, dst)
        second = nested_dissection_order(xyz, src, dst)
        assert np.array_equal(np.sort(first), np.arange(3000))
        np.testing.assert_array_equal(first, second)

    def test_solution_matches_minimum_degree_to_round_off(self) -> None:
        """Reordering moves rounding only; the answer is the same linear solve."""
        xyz, src, dst = _sphere(3000)
        a = _operator(3000, src, dst)
        rhs = np.random.default_rng(3).normal(size=3000)
        reference = splu(a, permc_spec="MMD_AT_PLUS_A", options={"SymmetricMode": True}).solve(rhs)
        order = nested_dissection_order(xyz, src, dst)
        lu = splu(a[order][:, order].tocsc(), permc_spec="NATURAL", options={"SymmetricMode": True})
        solution = np.empty(3000)
        solution[order] = lu.solve(rhs[order])
        np.testing.assert_allclose(solution, reference, rtol=1e-10, atol=1e-12)

    def test_reduces_fill_against_a_scrambled_order(self) -> None:
        """The point of the order: far less fill than an arbitrary numbering."""
        xyz, src, dst = _sphere(3000)
        a = _operator(3000, src, dst)
        scrambled = np.random.default_rng(5).permutation(3000)
        order = nested_dissection_order(xyz, src, dst)

        def fill(perm: np.ndarray) -> int:
            lu = splu(
                a[perm][:, perm].tocsc(), permc_spec="NATURAL", options={"SymmetricMode": True}
            )
            return int(lu.L.nnz + lu.U.nnz)

        assert fill(order) < 0.25 * fill(scrambled)

    def test_tiny_graph_is_one_leaf(self) -> None:
        xyz, src, dst = _sphere(20)
        np.testing.assert_array_equal(nested_dissection_order(xyz, src, dst), np.arange(20))

    def test_invalid_inputs_raise(self) -> None:
        xyz, src, dst = _sphere(50)
        with pytest.raises(ValueError, match="shape"):
            nested_dissection_order(xyz[:, :2], src, dst)
        with pytest.raises(ValueError, match="leaf_cells"):
            nested_dissection_order(xyz, src, dst, leaf_cells=0)
        with pytest.raises(ValueError, match="same shape"):
            nested_dissection_order(xyz, src, dst[:-1])
