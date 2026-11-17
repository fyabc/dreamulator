"""Transport reference tracers through explicitly selected native topologies.

This helper uses the optional pyGPlates validation dependency. It keeps a
confirmed owner while that owner still contains the point. Networks have the
native priority over plates. An overlap without a confirmed owner remains
unresolved, rather than selecting whichever polygon a previous point visited.

Reconstruction and point containment are delegated to pyGPlates. This module
does not implement a topology solver or delete points as physical subduction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def topology_key(topology: Any) -> tuple[str, str]:
    """Identify a native topology by its category, plate ID and feature ID."""
    # Keep the helper importable without the optional validation dependency.
    import pygplates  # type: ignore[import-untyped]

    category = "network" if isinstance(topology, pygplates.ResolvedTopologicalNetwork) else "plate"
    feature = topology.get_feature()
    return (
        f"{category}_{feature.get_reconstruction_plate_id()}",
        feature.get_feature_id().get_string(),
    )


@dataclass(frozen=True)
class Selection:
    """Retain all containing topologies and explain the selected owner."""

    owner: str | None
    topology: Any | None
    candidates: tuple[tuple[str, str], ...]
    reason: str


@dataclass(frozen=True)
class TransportStep:
    """A native displacement and two explicit topology selections."""

    point: Any | None
    before: Selection
    after: Selection | None


class SelectedTopologyTransport:
    """Use immutable topology lists; never carry search order between points."""

    def __init__(self, model: Any) -> None:
        self.model = model
        self._topologies: dict[float, tuple[Any, ...]] = {}

    def topologies(self, time_ma: float) -> tuple[Any, ...]:
        if time_ma not in self._topologies:
            snapshot = self.model.topological_snapshot(time_ma)
            self._topologies[time_ma] = tuple(
                sorted(snapshot.get_resolved_topologies(), key=topology_key)
            )
        return self._topologies[time_ma]

    def select(self, point: Any, time_ma: float, confirmed_owner: str | None = None) -> Selection:
        candidates = [
            topology
            for topology in self.topologies(time_ma)
            if not topology.get_point_location(point).not_located_in_resolved_topology()
        ]
        keys = tuple(topology_key(topology) for topology in candidates)
        networks = [
            topology for topology in candidates if topology_key(topology)[0].startswith("network_")
        ]
        eligible = networks or candidates
        if not eligible:
            return Selection(None, None, keys, "topology_gap")
        owners = {topology_key(topology)[0] for topology in eligible}
        preferred = [
            topology for topology in eligible if topology_key(topology)[0] == confirmed_owner
        ]
        if preferred:
            # Distinct network features can deform differently even when their
            # plate IDs match; rigid polygons with one ID share a stage rotation.
            if networks and len(preferred) != 1:
                return Selection(None, None, keys, "ambiguous_network")
            reason = "confirmed_owner_in_overlap" if len(owners) > 1 else "confirmed_owner"
            return Selection(confirmed_owner, preferred[0], keys, reason)
        if len(owners) != 1 or (networks and len(eligible) != 1):
            return Selection(None, None, keys, "unconfirmed_overlap")
        topology = eligible[0]
        return Selection(topology_key(topology)[0], topology, keys, "unique_owner")

    def step(
        self,
        point: Any,
        from_time_ma: float,
        to_time_ma: float,
        confirmed_owner: str | None = None,
    ) -> TransportStep:
        if from_time_ma == to_time_ma:
            raise ValueError("Transport requires two distinct reconstruction times.")
        before = self.select(point, from_time_ma, confirmed_owner)
        if before.topology is None:
            return TransportStep(None, before, None)
        moved = before.topology.reconstruct_point(point, to_time_ma)
        if moved is None:
            raise RuntimeError(
                "The selected native topology did not reconstruct its contained point."
            )
        after = self.select(moved, to_time_ma, before.owner)
        return TransportStep(moved, before, after)
