"""Conservative transfer of an along-axis budget to a continuous spherical field.

Edge means are densities per unit boundary length. Mass-lumped linear interpolation
preserves their arc-length integral. An implicit graph diffusion regularises the
vertex values with zero flux at endpoints and without exchanges between disconnected
sources. This is numerical regularisation, not a model of crustal transport.

The smoothing radius uses the second moment of the existing box average: a box of
half-width R has variance R²/3, while the implicit diffusion resolvent has variance
2t on an infinite straight axis, giving t=R²/6. Finite endpoints and branches change
the response and are retained explicitly in the graph.
"""

from __future__ import annotations

import hashlib

import numpy as np
from scipy.sparse import coo_matrix, diags
from scipy.sparse.linalg import spsolve

from dreamulator.map.terrain_source import SphericalSegmentGeometry


class ConservativeArcField:
    """A nonnegative budget field with a conserved integral along source arcs.

    Missing history must be handled by the caller as a separate source or coverage
    gap. NaN edge means are rejected rather than being interpreted as zero budgets.
    Off-axis extension uses length-weighted inverse-square distances to finite arcs;
    on an arc it takes the linear vertex field exactly. Shared vertices have one
    value, so nearest-arc switches do not create parameter jumps in the corridor.
    """

    def __init__(
        self,
        segments_xyz: np.ndarray,
        edge_means: np.ndarray,
        radius_km: float,
        smoothing_radius_km: float = 0.0,
    ) -> None:
        self.geometry = SphericalSegmentGeometry(segments_xyz)
        values = np.array(edge_means, dtype=np.float64, copy=True)
        if values.shape != (len(self.geometry.segments),):
            raise ValueError("one budget mean is required for each arc")
        if not np.isfinite(values).all() or np.any(values < 0):
            raise ValueError("budget means must be finite and nonnegative; missing is not zero")
        if not np.isfinite(radius_km) or radius_km <= 0:
            raise ValueError("radius_km must be finite and positive")
        if not np.isfinite(smoothing_radius_km) or smoothing_radius_km < 0:
            raise ValueError("smoothing radius must be finite and nonnegative")
        self.radius_km = float(radius_km)
        self.smoothing_radius_km = float(smoothing_radius_km)
        arcs = self.geometry.segments
        normal = np.cross(arcs[:, 0], arcs[:, 1])
        angles = np.arctan2(np.linalg.norm(normal, axis=1), (arcs[:, 0] * arcs[:, 1]).sum(1))
        self.lengths_km = angles * radius_km
        self._angles = angles
        self._normal = normal / np.linalg.norm(normal, axis=1, keepdims=True)
        self._tangent = np.cross(self._normal, arcs[:, 0])
        self.nodes, inverse = np.unique(arcs.reshape(-1, 3), axis=0, return_inverse=True)
        self.edge_nodes = inverse.reshape(-1, 2)
        n = len(self.nodes)
        self.node_measure_km = np.bincount(
            inverse, weights=np.repeat(self.lengths_km / 2, 2), minlength=n
        )
        mass = np.bincount(inverse, weights=np.repeat(self.lengths_km * values / 2, 2), minlength=n)
        self.initial_node_values = mass / self.node_measure_km
        self.edge_means = values
        self.node_values = self.initial_node_values.copy()
        if smoothing_radius_km > 0:
            a, b = self.edge_nodes.T
            conductance = 1 / self.lengths_km
            stiffness = coo_matrix(
                (
                    np.concatenate([conductance, conductance, -conductance, -conductance]),
                    (np.concatenate([a, b, a, b]), np.concatenate([a, b, b, a])),
                ),
                shape=(n, n),
            ).tocsr()
            tau = smoothing_radius_km**2 / 6
            system = diags(self.node_measure_km) + tau * stiffness
            self.node_values = np.asarray(spsolve(system.tocsc(), mass), dtype=np.float64)
        self.integral_before = float(self.lengths_km @ values)
        self.integral_after = float(self.node_measure_km @ self.node_values)
        tolerance = 2e-11 * max(self.integral_before, 1.0)
        if abs(self.integral_after - self.integral_before) > tolerance:
            raise ArithmeticError("along-axis budget transfer failed integral conservation")
        if not np.isfinite(self.node_values).all() or self.node_values.min() < -1e-12:
            raise ArithmeticError("along-axis budget transfer produced invalid vertex values")
        self.endpoints = self.node_values[self.edge_nodes]
        digest = hashlib.sha256()
        for arr in (arcs, values, np.array([radius_km, smoothing_radius_km])):
            digest.update(arr.astype("<f8").tobytes())
        self.sha256 = digest.hexdigest()
        for arr in (
            self.lengths_km,
            self.nodes,
            self.edge_nodes,
            self.node_measure_km,
            self.initial_node_values,
            self.node_values,
            self.edge_means,
            self.endpoints,
            self._angles,
            self._normal,
            self._tangent,
        ):
            arr.setflags(write=False)

    def __call__(self, xyz: np.ndarray) -> np.ndarray:
        """Query the continuous vertex field, in arbitrary-shaped unit-vector batches."""
        points = np.asarray(xyz, dtype=np.float64)
        if points.ndim < 1 or points.shape[-1] != 3 or not np.isfinite(points).all():
            raise ValueError("query points must be finite unit vectors")
        if not np.allclose(np.linalg.norm(points, axis=-1), 1, rtol=0, atol=1e-7):
            raise ValueError("query points must be unit vectors")
        shape = points.shape[:-1]
        points = points.reshape(-1, 3)
        points = points / np.linalg.norm(points, axis=1, keepdims=True)
        out = np.empty(len(points))
        arcs = self.geometry.segments
        for start in range(0, len(points), 1024):
            q = points[start : start + 1024]
            qa, qb = q @ arcs[:, 0].T, q @ arcs[:, 1].T
            normal = q @ self._normal.T
            along = np.arctan2(q @ self._tangent.T, qa)
            on_arc = (along >= 0) & (along <= self._angles)
            distance = np.where(
                on_arc,
                np.arcsin(np.clip(abs(normal), 0, 1)),
                np.arccos(np.clip(np.maximum(qa, qb), -1, 1)),
            )
            fraction = np.where(on_arc, along / self._angles, (qb > qa).astype(float))
            interpolated = self.endpoints[:, 0] * (1 - fraction) + self.endpoints[:, 1] * fraction
            d2 = distance**2
            weights = self.lengths_km * np.maximum(d2.min(axis=1, keepdims=True), 1e-30)
            weights = weights / np.maximum(d2, 1e-30)
            result = np.sum(weights * interpolated, axis=1) / weights.sum(axis=1)
            exact = distance <= 1e-12
            hits = exact.sum(axis=1)
            np.divide(np.sum(exact * interpolated, axis=1), hits, out=result, where=hits > 0)
            out[start : start + len(q)] = result
        return out.reshape(shape)
