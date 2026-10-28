"""Continuous spherical reconstruction of fixed coarse samples and their contours.

Point values are linearly interpolated on faces of their spherical convex hull.
This reconstructs a continuous surface from coarse inputs; it does not infer finer
geological observations or impose conservation of cell averages.
"""

from __future__ import annotations

import hashlib

import numpy as np
from scipy.spatial import ConvexHull, cKDTree

from dreamulator.map.terrain_source import SphericalProjection, SphericalSegmentGeometry


class SphericalPointTerrainField:
    """Fixed point values queried through positive spherical barycentric weights.

    ``stable_weights`` computes the same ray/face intersection in local edge
    coordinates, for tightly spaced control curves. The established global
    inverse path remains the default for previously frozen source fields.
    """

    def __init__(
        self, xyz: np.ndarray, values: np.ndarray, *, stable_weights: bool = False
    ) -> None:
        points = np.array(xyz, dtype=np.float64, copy=True)
        data = np.array(values, dtype=np.float64, copy=True)
        if points.ndim != 2 or points.shape[1] != 3 or len(points) < 4:
            raise ValueError("at least four spherical source points are required")
        if not np.isfinite(points).all() or not np.allclose(
            np.linalg.norm(points, axis=1), 1, rtol=0, atol=1e-7
        ):
            raise ValueError("source points must be finite unit vectors")
        if data.ndim not in (1, 2) or data.shape[0] != len(points) or not np.isfinite(data).all():
            raise ValueError("source values must be finite and match the points")
        points /= np.linalg.norm(points, axis=1, keepdims=True)
        hull = ConvexHull(points)
        if np.any(hull.equations[:, -1] >= 0):
            raise ValueError("source points must enclose the centre of the sphere")
        self.points, self.values = points, data
        self.faces = hull.simplices.copy()
        vertices = points[self.faces]
        self._inverse = (
            np.empty((0, 3, 3)) if stable_weights else np.linalg.inv(vertices.transpose(0, 2, 1))
        )
        self._stable_weights = stable_weights
        self._neighbours = hull.neighbors.copy() if stable_weights else np.empty((0, 3), dtype=int)
        self._origin = self._normal = self._dual0 = self._dual1 = np.empty((0, 3))
        if stable_weights:
            self._origin = vertices[:, 0].copy()
            edge0 = vertices[:, 1] - vertices[:, 0]
            edge1 = vertices[:, 2] - vertices[:, 0]
            normal = np.cross(edge0, edge1)
            norm2 = (normal * normal).sum(axis=1)
            self._normal = normal / np.sqrt(norm2)[:, None]
            self._normal *= np.where(np.sum(self._normal * self._origin, axis=1) >= 0, 1.0, -1.0)[
                :, None
            ]
            self._dual0 = np.cross(edge1, normal) / norm2[:, None]
            self._dual1 = np.cross(normal, edge0) / norm2[:, None]
        centres = vertices.mean(axis=1)
        centres /= np.linalg.norm(centres, axis=1, keepdims=True)
        self._tree = cKDTree(centres)
        digest = hashlib.sha256()
        for arr in (points, data):
            digest.update(str(arr.shape).encode())
            digest.update(arr.astype("<f8").tobytes())
        if stable_weights:
            digest.update(b"local-face-weights-v1")
        self.sha256 = digest.hexdigest()
        for arr in (
            self.points,
            self.values,
            self.faces,
            self._inverse,
            self._origin,
            self._normal,
            self._dual0,
            self._dual1,
            self._neighbours,
        ):
            arr.setflags(write=False)

    def __call__(self, xyz: np.ndarray) -> np.ndarray:
        vertices, weights = self.basis(xyz)
        shape = weights.shape[:-1]
        z = self.values[vertices.reshape(-1, 3)]
        result: np.ndarray = np.einsum("ni,ni...->n...", weights.reshape(-1, 3), z)
        return result.reshape((*shape, *self.values.shape[1:]))

    def basis(self, xyz: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Return source vertex indices and positive weights for the same spherical query.

        Consumers can reconstruct nonlinear constraint responses with infinite
        inactive bounds, while sharing the established source triangulation.
        """
        points = np.asarray(xyz, dtype=np.float64)
        if points.ndim < 1 or points.shape[-1] != 3 or not np.isfinite(points).all():
            raise ValueError("query points must be finite unit vectors")
        if not np.allclose(np.linalg.norm(points, axis=-1), 1, rtol=0, atol=1e-7):
            raise ValueError("query points must be unit vectors")
        shape = points.shape[:-1]
        points = points.reshape(-1, 3)
        points = points / np.linalg.norm(points, axis=1, keepdims=True)
        result_vertices = np.empty((len(points), 3), dtype=np.int64)
        result_weights = np.empty((len(points), 3), dtype=np.float64)
        for start in range(0, len(points), 4096):
            q = points[start : start + 4096]
            unresolved = np.arange(len(q))

            def resolve(
                candidates: np.ndarray, query: np.ndarray, base: int
            ) -> tuple[np.ndarray, np.ndarray]:
                nonlocal unresolved
                if self._stable_weights:
                    q = query[unresolved, None, :]
                    offset = q - self._origin[candidates]
                    normal = self._normal[candidates]
                    denominator = np.sum(normal * q, axis=-1)
                    correction = np.divide(
                        -np.sum(normal * offset, axis=-1),
                        denominator,
                        out=np.zeros_like(denominator),
                        where=denominator != 0,
                    )
                    offset = offset + correction[..., None] * q
                    u = np.sum(offset * self._dual0[candidates], axis=-1)
                    v = np.sum(offset * self._dual1[candidates], axis=-1)
                    weights = np.stack([1 - u - v, u, v], axis=-1)
                    # Hull normals face outward; opposite hemispheres must
                    # not be admitted by the ray/face intersection.
                    sums = denominator
                else:
                    weights = np.einsum(
                        "nkij,nj->nki", self._inverse[candidates], query[unresolved]
                    )
                    sums = weights.sum(axis=2)
                    weights = np.divide(
                        weights,
                        sums[..., None],
                        out=np.full_like(weights, -1),
                        where=sums[..., None] > 0,
                    )
                valid = (weights >= -1e-10).all(axis=2) & (sums > 0)
                found = valid.any(axis=1)
                rows = np.flatnonzero(found)
                chosen = valid[found].argmax(axis=1)
                ids = candidates[rows, chosen]
                w = np.maximum(weights[rows, chosen], 0)
                w /= w.sum(axis=1, keepdims=True)
                result_vertices[base + unresolved[found]] = self.faces[ids]
                result_weights[base + unresolved[found]] = w
                unresolved = unresolved[~found]
                return weights, found

            for count in (8,) if self._stable_weights else (8, 32, 128):
                count = min(count, len(self.faces))
                if not len(unresolved):
                    break
                candidates = self._tree.query(q[unresolved], k=count)[1]
                resolve(candidates, q, start)
            if self._stable_weights and len(unresolved):
                # Dense contour vertices create narrow neighbouring faces
                # whose centroids can crowd out the containing triangle. Walk
                # across violated face edges before the exhaustive fallback.
                candidates = self._tree.query(q[unresolved], k=1)[1]
                for _ in range(512):
                    weights, found = resolve(candidates[:, None], q, start)
                    if not len(unresolved):
                        break
                    edge = weights[:, 0].argmin(axis=1)
                    candidates = self._neighbours[candidates, edge][~found]
            # Large, irregular triangles can evade the centroid shortlist. The
            # exact fallback scans bounded face batches instead of allocating a
            # query-by-entire-globe matrix.
            if len(unresolved):
                for offset in range(0, len(self.faces), 128):
                    ids = np.arange(offset, min(offset + 128, len(self.faces)))
                    resolve(np.broadcast_to(ids, (len(unresolved), len(ids))), q, start)
                    if not len(unresolved):
                        break
            if len(unresolved):
                raise ValueError("spherical source coverage failed")
        return result_vertices.reshape((*shape, 3)), result_weights.reshape((*shape, 3))

    def contour_segments(self, level: float = 0.0, channel: int = 0) -> np.ndarray:
        """Extract exact great-circle segments of the reconstructed level contour."""
        if not np.isfinite(level):
            raise ValueError("contour level must be finite")
        values = self.values if self.values.ndim == 1 else self.values[:, channel]
        edges = self.faces[:, [[0, 1], [1, 2], [2, 0]]].reshape(-1, 2)
        unique, inverse = np.unique(np.sort(edges, axis=1), axis=0, return_inverse=True)
        a, b = unique.T
        va, vb = values[a] - level, values[b] - level
        crossing = (va < 0) != (vb < 0)
        intersections = np.zeros((len(unique), 3))
        t = va[crossing] / (va[crossing] - vb[crossing])
        intersections[crossing] = (
            self.points[a[crossing]] * (1 - t[:, None]) + self.points[b[crossing]] * t[:, None]
        )
        intersections[crossing] /= np.linalg.norm(intersections[crossing], axis=1, keepdims=True)
        face_edges = inverse.reshape(-1, 3)
        cross = crossing[face_edges]
        complete = cross.sum(axis=1) == 2
        ids = face_edges[complete][cross[complete]].reshape(-1, 2)
        segments = intersections[ids]
        return np.asarray(
            segments[np.linalg.norm(segments[:, 0] - segments[:, 1], axis=1) > 1e-12],
            dtype=np.float64,
        )

    def contour_paths(self, level: float = 0.0, channel: int = 0) -> list[np.ndarray]:
        """Keep contour connectivity; stop at junctions instead of choosing a branch.

        Closed loops repeat their first node. Paths are oriented with higher
        values on the geographic left in the geological y-north convention.
        This geometry reads the frozen field and leaves query numerics intact.
        """
        segments = self.contour_segments(level, channel)
        if not len(segments):
            return []
        nodes, inverse = np.unique(segments.reshape(-1, 3), axis=0, return_inverse=True)
        edges = inverse.reshape(-1, 2)
        incident: list[list[int]] = [[] for _ in nodes]
        for i, (a, b) in enumerate(edges):
            incident[a].append(i)
            incident[b].append(i)
        visited = np.zeros(len(edges), dtype=bool)
        paths = []

        def trace(node: int, edge: int) -> None:
            ids = [node]
            while not visited[edge]:
                visited[edge] = True
                a, b = edges[edge]
                node = int(b if a == node else a)
                ids.append(node)
                if len(incident[node]) != 2:
                    break
                available = [e for e in incident[node] if not visited[e]]
                if not available:
                    break
                edge = available[0]
            paths.append(nodes[ids])

        for i, neighbours in enumerate(incident):
            if len(neighbours) != 2:
                for edge in neighbours:
                    if not visited[edge]:
                        trace(i, edge)
        for i, (a, _) in enumerate(edges):
            if not visited[i]:
                trace(int(a), i)
        probe_left, probe_right = [], []
        for path in paths:
            a, b = path[:2]
            mid = a + b
            mid /= np.linalg.norm(mid)
            normal = -np.cross(a, b)
            length = np.linalg.norm(normal)
            normal /= length
            step = min(1e-6, float(length) * 0.01)
            probe_left.append(np.cos(step) * mid + np.sin(step) * normal)
            probe_right.append(np.cos(step) * mid - np.sin(step) * normal)
        left, right = self(np.array(probe_left)), self(np.array(probe_right))
        if self.values.ndim == 2:
            left, right = left[:, channel], right[:, channel]
        return [path if left[i] >= right[i] else path[::-1].copy() for i, path in enumerate(paths)]


class SphericalCoastGeometry:
    """Exact distances to finite spherical arcs with a triangle-inequality search."""

    def __init__(self, segments_xyz: np.ndarray, radius_km: float) -> None:
        if not np.isfinite(radius_km) or radius_km <= 0:
            raise ValueError("radius_km must be finite and positive")
        self.geometry = SphericalSegmentGeometry(segments_xyz)
        self.radius_km = float(radius_km)
        arcs = self.geometry.segments
        normal = np.cross(arcs[:, 0], arcs[:, 1])
        self._angles = np.arctan2(np.linalg.norm(normal, axis=1), (arcs[:, 0] * arcs[:, 1]).sum(1))
        self._normal = normal / np.linalg.norm(normal, axis=1, keepdims=True)
        self._tangent = np.cross(self._normal, arcs[:, 0])
        centres = arcs.mean(axis=1)
        centres /= np.linalg.norm(centres, axis=1, keepdims=True)
        self._tree = cKDTree(centres)
        self._half_max = float(self._angles.max() / 2)

    def _pair_distances(self, q: np.ndarray, indices: np.ndarray) -> np.ndarray:
        arcs = self.geometry.segments[indices]
        qa = np.sum(q * arcs[:, 0], axis=1)
        qb = np.sum(q * arcs[:, 1], axis=1)
        normal = np.sum(q * self._normal[indices], axis=1)
        along = np.arctan2(np.sum(q * self._tangent[indices], axis=1), qa)
        on_arc = (along >= 0) & (along <= self._angles[indices])
        return np.asarray(
            np.where(
                on_arc,
                np.arcsin(np.clip(abs(normal), 0, 1)),
                np.arccos(np.clip(np.maximum(qa, qb), -1, 1)),
            ),
            dtype=np.float64,
        )

    def distance_km(self, xyz: np.ndarray, maximum_km: float | None = None) -> np.ndarray:
        """Return infinity beyond an optional physical search distance."""
        points = np.asarray(xyz, dtype=np.float64)
        if points.ndim < 1 or points.shape[-1] != 3 or not np.isfinite(points).all():
            raise ValueError("query points must be finite unit vectors")
        if not np.allclose(np.linalg.norm(points, axis=-1), 1, rtol=0, atol=1e-7):
            raise ValueError("query points must be unit vectors")
        if maximum_km is not None and (not np.isfinite(maximum_km) or maximum_km < 0):
            raise ValueError("maximum distance must be finite and nonnegative")
        shape = points.shape[:-1]
        points = points.reshape(-1, 3)
        points = points / np.linalg.norm(points, axis=1, keepdims=True)
        out = np.empty(len(points))
        limit = np.pi if maximum_km is None else maximum_km / self.radius_km
        for start in range(0, len(points), 4096):
            q = points[start : start + 4096]
            initial = self._tree.query(q)[1]
            best = self._pair_distances(q, initial)
            angles = np.minimum(np.minimum(best, limit) + self._half_max + 1e-10, np.pi)
            neighbours = self._tree.query_ball_point(q, 2 * np.sin(angles / 2))
            lengths = np.array([len(ids) for ids in neighbours])
            if lengths.sum():
                rows = np.repeat(np.arange(len(q)), lengths)
                ids = np.concatenate(neighbours).astype(np.int64)
                distance = self._pair_distances(q[rows], ids)
                np.minimum.at(best, rows, distance)
            out[start : start + len(q)] = np.where(best <= limit, best * self.radius_km, np.inf)
        return out.reshape(shape)

    def project(self, xyz: np.ndarray, maximum_km: float | None = None) -> SphericalProjection:
        """Project to finite arcs, preserving source segment order for exact ties.

        Beyond ``maximum_km``, the index is -1, distance is infinity, fraction
        is unavailable and side is zero. The established distance-only path
        remains independent for frozen source replays.
        """
        points = np.asarray(xyz, dtype=np.float64)
        if points.ndim < 1 or points.shape[-1] != 3 or not np.isfinite(points).all():
            raise ValueError("query points must be finite unit vectors")
        if not np.allclose(np.linalg.norm(points, axis=-1), 1, rtol=0, atol=1e-7):
            raise ValueError("query points must be unit vectors")
        if maximum_km is not None and (not np.isfinite(maximum_km) or maximum_km < 0):
            raise ValueError("maximum distance must be finite and nonnegative")
        shape = points.shape[:-1]
        points = points.reshape(-1, 3)
        points = points / np.linalg.norm(points, axis=1, keepdims=True)
        index = np.full(len(points), -1, dtype=np.int64)
        distance = np.full(len(points), np.inf)
        fraction = np.full(len(points), np.nan)
        side = np.zeros(len(points))
        limit = np.pi if maximum_km is None else maximum_km / self.radius_km
        for start in range(0, len(points), 4096):
            q = points[start : start + 4096]
            initial = self._tree.query(q)[1]
            best = self._pair_distances(q, initial)
            angles = np.minimum(np.minimum(best, limit) + self._half_max + 1e-10, np.pi)
            neighbours = self._tree.query_ball_point(q, 2 * np.sin(angles / 2))
            lengths = np.array([len(ids) for ids in neighbours])
            chosen = initial.copy()
            if lengths.sum():
                rows = np.repeat(np.arange(len(q)), lengths)
                ids = np.concatenate(neighbours).astype(np.int64)
                d = self._pair_distances(q[rows], ids)
                np.minimum.at(best, rows, d)
                matched = d == best[rows]
                chosen.fill(len(self._angles))
                np.minimum.at(chosen, rows[matched], ids[matched])
            valid = best <= limit
            rows = np.flatnonzero(valid)
            selected = chosen[valid]
            qa = np.sum(q[valid] * self.geometry.segments[selected, 0], axis=1)
            qb = np.sum(q[valid] * self.geometry.segments[selected, 1], axis=1)
            along = np.arctan2(np.sum(q[valid] * self._tangent[selected], axis=1), qa)
            on_arc = (along >= 0) & (along <= self._angles[selected])
            index[start + rows] = selected
            distance[start + rows] = best[valid]
            fraction[start + rows] = np.where(
                on_arc, along / self._angles[selected], (qb > qa).astype(float)
            )
            side[start + rows] = np.sign(np.sum(q[valid] * self._normal[selected], axis=1))
        return SphericalProjection(*(v.reshape(shape) for v in (index, fraction, distance, side)))
