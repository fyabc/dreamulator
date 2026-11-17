"""Endpoint-slope exploration of wider single-receiver neighborhoods.

This is not a reproduction of published D16. Intermediate terrain barriers
are deliberately not repaired; the comparison reports that limitation.
Flat routing reuses an existing D8 graph, with no new depression solver.
"""

from __future__ import annotations

import numpy as np


def offsets(radius: int) -> np.ndarray:
    if radius not in (1, 2, 3):
        raise ValueError("local comparison supports radii 1, 2 and 3")
    return np.array(
        [(r, c) for r in range(-radius, radius + 1) for c in range(-radius, radius + 1) if r or c]
    )


def receivers(
    height: np.ndarray, absorbing: np.ndarray, flat_receiver: np.ndarray, radius: int
) -> np.ndarray:
    """Choose maximum endpoint drop/distance, retaining D8 on zero-slope cells."""
    nr, nc = height.shape
    best = np.zeros(height.shape)
    receiver = np.asarray(flat_receiver).reshape(height.shape).copy()
    ids = np.arange(height.size).reshape(height.shape)
    for dr, dc in offsets(radius):
        source = (slice(max(0, -dr), min(nr, nr - dr)), slice(max(0, -dc), min(nc, nc - dc)))
        target = (slice(max(0, dr), min(nr, nr + dr)), slice(max(0, dc), min(nc, nc + dc)))
        slope = (height[source] - height[target]) / np.hypot(dr, dc)
        better = (slope > best[source]) & ~absorbing[source]
        best[source][better] = slope[better]
        receiver[source][better] = ids[target][better]
    receiver[absorbing] = -1
    return receiver.ravel()


def plane_resolution(radius: int) -> dict:
    off = offsets(radius)
    angles = np.unique(np.round(np.arctan2(-off[:, 0], off[:, 1]) % (2 * np.pi), 12))
    angles.sort()
    gaps = np.diff(np.r_[angles, angles[0] + 2 * np.pi])
    true = np.radians(np.arange(0, 360, 0.01))
    error = np.abs(np.angle(np.exp(1j * (true[:, None] - angles)))).min(axis=1)
    return {
        "radius_px": radius,
        "candidate_cells": len(off),
        "distinct_directions": len(angles),
        "maximum_plane_error_bound_deg": float(np.degrees(gaps.max() / 2)),
        "uniform_plane_mean_error_deg": float(np.degrees(error).mean()),
    }
