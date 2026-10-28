"""Physical profile integrals and frozen-envelope replacement semantics."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from dreamulator.map.orogen_contract import ContactConvergenceHistory, OrogenContract, OrogenSegment
from dreamulator.map.orogen_profile import (
    _AIRY_THICKENING_PER_ELEVATION,
    _REFERENCE_CRUST_KM,
    collision_cap_m,
    collision_crests_m,
)
from dreamulator.map.orogen_source import (
    CollisionProfileField,
    ContactCollisionProfileField,
    FrozenOrogenReplacement,
    OrogenEnvelopeProfileField,
    PaleoProfileField,
    collision_source_from_contract,
    orogen_source_from_native,
    paleo_source_from_history,
)
from dreamulator.map.paleo_orogens import paleo_orogen_field
from dreamulator.map.paleo_sutures import AuthorSuture, lonlat_to_xyz


def profile() -> CollisionProfileField:
    points = lonlat_to_xyz(np.array([[0, -1], [0, 0], [0, 1]]))
    return CollisionProfileField(
        np.array([[points[0], points[1]], [points[1], points[2]]]),
        np.array([30.0, 90.0]),
        6371,
        9.80665,
        650,
        300,
        segment_id="collision",
    )


@pytest.mark.parametrize("retained", [10.0, 1000.0])
def test_profile_cross_section_preserves_airy_budget_below_and_above_cap(retained: float) -> None:
    field = profile()
    area = retained * _REFERENCE_CRUST_KM / _AIRY_THICKENING_PER_ELEVATION
    peak = np.sqrt(area / field.half_inv)
    plateau = max((area - field.cap_km**2 * field.half_inv) / field.cap_km, 0)
    integral = 0.0
    for retro, slope in [(False, field.pro_slope), (True, field.retro_slope)]:
        end = min(peak, field.cap_km) / slope + (plateau if retro else 0)
        d = np.linspace(0, end, 10001)
        z = field.profile(d, np.full_like(d, retained), np.full_like(d, retro, dtype=bool))
        integral += np.trapezoid(z / 1000, d)
    assert integral == pytest.approx(area, rel=2e-7)


def test_replacement_respects_dominant_paleo_and_ocean_coverage() -> None:
    field = profile()
    q = lonlat_to_xyz(np.array([[0.2, 0], [-0.2, 0], [1, 0]]))
    source = FrozenOrogenReplacement(
        field,
        q,
        np.array([True, False, True]),
        np.array([200, 0, 100]),
        np.array([0, 0, 10000]),
        np.array([10000, 0, 0]),
        reference_id="envelope",
    )
    delta, _ = source.evaluate(np.zeros(3), np.array([0.2, -0.2, 1]))
    np.testing.assert_array_equal(delta, 0)


def test_cap_at_or_below_base_has_zero_relief() -> None:
    field = profile()
    zero = CollisionProfileField(
        field.geometry.segments,
        field.axis_field.edge_means,
        6371,
        9.80665,
        collision_cap_m(9.80665),
        300,
        segment_id="zero",
    )
    assert zero.profile(np.array([0.0]), np.array([1000.0]), np.array([True]))[0] == 0


def _native_inputs():
    xyz = lonlat_to_xyz(np.array([[0, -1], [0, 0], [0, 1]]))
    values = np.array([100.0, 200.0, 300.0])
    fields = {
        "xyz": xyz,
        "plate_id": np.array(["pro", "retro", "pro"]),
        "land_crust_mask": np.ones(3, dtype=bool),
        "orogen.segment.collision": values,
        "active_orogen_m": values.copy(),
        "paleo_orogen_m": np.zeros(3),
    }
    history = {
        cell: ContactConvergenceHistory(
            continuous_duration_myr=1.0,
            continuous_convergence_km=30.0,
            cumulative_convergence_km=30.0,
            source_cell_id=cell,
            transfer_chord_km=0.0,
            status="matched",
        )
        for cell in range(3)
    }
    segment = OrogenSegment(
        id="collision",
        kind="collision",
        pro_plate="pro",
        retro_plate="retro",
        cell_ids=[0, 1, 2],
        rate_cm_yr=3.0,
        onset_age_myr=1.0,
        convergence_km=30.0,
        breakoff_my=15.0,
        upper_plate_ratio=1.0,
        cell_history=history,
    )
    contract = OrogenContract([segment], {}, {0: 0.0, 1: 30.0, 2: 90.0}, [])
    geometry = {
        "num_cells": 3,
        "coordinate_frame": "unit sphere, y north",
        "contacts": [
            {"cell_id": cell, "xyz": point.tolist(), "plate_id": fields["plate_id"][cell]}
            for cell, point in enumerate(xyz)
        ],
        "vertices": [{"vertex_id": cell, "xyz": point.tolist()} for cell, point in enumerate(xyz)],
        "interfaces": [
            {
                "segment_id": "collision",
                "vertex_ids": [0, 1],
                "contact_cell_ids": [0],
                "positive_retained_contact_cell_ids": [],
            },
            {
                "segment_id": "collision",
                "vertex_ids": [1, 2],
                "contact_cell_ids": [1, 2],
                "positive_retained_contact_cell_ids": [1, 2],
            },
        ],
    }
    return fields, contract, geometry


def _native_collision(fields, contract, geometry):
    return collision_source_from_contract(
        fields,
        contract,
        geometry,
        segment_id="collision",
        radius_km=6371.0,
        gravity_m_s2=9.80665,
        base_m=650.0,
        reference_id="native-source",
    )


def test_native_collision_retains_valid_zero_arcs_and_axis_budget() -> None:
    fields, contract, geometry = _native_inputs()
    source = _native_collision(fields, contract, geometry)
    profile_meta = source.metadata["profile"]
    expected = 60.0 * 6371.0 * np.pi / 180.0
    assert profile_meta["axis_integral_before_km2"] == pytest.approx(expected, rel=1e-12)
    assert profile_meta["axis_integral_after_km2"] == pytest.approx(expected, rel=1e-12)
    assert isinstance(source.profile_field, CollisionProfileField)
    assert len(source.profile_field.geometry.segments) == 2


def test_known_contact_policy_keeps_unknown_history_out_of_parameter_samples() -> None:
    fields, contract, geometry = _native_inputs()
    contract.segments[0].cell_history[0] = ContactConvergenceHistory(
        continuous_duration_myr=0.0,
        continuous_convergence_km=0.0,
        cumulative_convergence_km=0.0,
        source_cell_id=None,
        transfer_chord_km=None,
        status="unavailable",
    )
    with pytest.raises(ValueError, match="available effective contact history"):
        _native_collision(fields, contract, geometry)
    source = collision_source_from_contract(
        fields,
        contract,
        geometry,
        segment_id="collision",
        radius_km=6371,
        gravity_m_s2=9.80665,
        base_m=650,
        reference_id="known-reference",
        parameter_policy="known_contact_vertices",
    )
    field = source.profile_field
    assert isinstance(field, ContactCollisionProfileField)
    assert len(field.geometry.segments) == 2
    assert len(field.nodes) == 2
    assert field.unavailable_contact_ids == (0,)
    # The two known contacts average to 60. The unavailable zero has geometry
    # but supplies neither a 45/40 km average nor a third parameter node.
    np.testing.assert_array_equal(field.node_values, 60)
    assert field.mean_retained_km == 60
    joint = orogen_source_from_native(
        fields,
        contract,
        geometry,
        [],
        collision_segment_ids=("collision",),
        radius_km=6371,
        gravity_m_s2=9.80665,
        base_m=650,
        reference_id="known-reference",
        collision_parameter_policy="known_contact_vertices",
    )
    query = lonlat_to_xyz(np.array([[0.2, -1], [0.2, 0], [0.2, 1]]))
    np.testing.assert_array_equal(joint.profile_field(query), field(query))


def test_known_contact_policy_rejects_positive_shortening_with_unknown_history() -> None:
    fields, contract, geometry = _native_inputs()
    contract.segments[0].cell_history[1] = replace(
        contract.segments[0].cell_history[1], status="unavailable"
    )
    with pytest.raises(ValueError, match="available positive history"):
        collision_source_from_contract(
            fields,
            contract,
            geometry,
            segment_id="collision",
            radius_km=6371,
            gravity_m_s2=9.80665,
            base_m=650,
            reference_id="invalid-history",
            parameter_policy="known_contact_vertices",
        )


def test_contact_node_extension_matches_nodes_range_and_query_partition() -> None:
    conservative = profile()
    arcs = conservative.geometry.segments.copy()
    values = np.array([[30.0, 60.0], [60.0, 90.0]])
    field = ContactCollisionProfileField(
        arcs,
        arcs,
        values,
        60,
        6371,
        9.80665,
        650,
        300,
        segment_id="known",
    )
    expected_nodes = field.node_values.copy()
    np.testing.assert_array_equal(field.shortening(field.nodes), expected_nodes)
    query = lonlat_to_xyz(np.array([[0, -1], [0.4, -0.5], [0, 0], [0.4, 0.5], [0, 1]]))
    shortening = field.shortening(query)
    assert shortening.min() >= 30 and shortening.max() <= 90
    np.testing.assert_allclose(
        np.concatenate([field.shortening(query[:2]), field.shortening(query[2:])]),
        shortening,
        atol=1e-12,
        rtol=0,
    )
    before = field(query)
    arcs[:] = 0
    values[:] = 1e6
    np.testing.assert_array_equal(field(query), before)
    for retained in [10.0, 1000.0]:
        distance = np.linspace(0, 1200, 1000)
        for retro in [True, False]:
            np.testing.assert_array_equal(
                field.profile(distance, np.full(1000, retained), np.full(1000, retro)),
                conservative.profile(distance, np.full(1000, retained), np.full(1000, retro)),
            )


def test_paleo_profile_keeps_author_inputs_frozen_and_uses_physical_wedge_width() -> None:
    path = np.array([[0.0, -1.0], [0.0, 1.0]])
    suture = AuthorSuture("old", "old", 53.0, path, width_km=1.0)
    broad_marker = AuthorSuture("old", "old", 53.0, path.copy(), width_km=1000.0)
    profile = PaleoProfileField(suture, 2000.0, 6371.0)
    xyz = lonlat_to_xyz(np.array([[0.2, 0], [0.4, 0], [1, 0]]))
    expected = paleo_orogen_field(xyz, [broad_marker], 2000.0, 6371.0)
    path[:] = 80.0
    np.testing.assert_array_equal(profile(xyz), expected)
    np.testing.assert_array_equal(np.concatenate([profile(xyz[:1]), profile(xyz[1:])]), expected)
    assert profile.metadata["collision_age_myr"] == 53.0


class ConstantProfile:
    def __init__(self, relief_m: float) -> None:
        self.relief_m = relief_m

    def __call__(self, xyz: np.ndarray) -> np.ndarray:
        return np.full(xyz.shape[:-1], self.relief_m)

    @property
    def metadata(self):
        return {"test_relief_m": self.relief_m}


@pytest.mark.parametrize("active,paleo,expected", [(800.0, 850.0, -150.0), (1200.0, 1100.0, 200.0)])
def test_joint_envelope_handles_overlapping_sources_and_dominance_changes(
    active: float, paleo: float, expected: float
) -> None:
    xyz = lonlat_to_xyz(np.array([[0.0, 0.0]]))
    field = OrogenEnvelopeProfileField(
        {"active": ConstantProfile(active), "paleo": ConstantProfile(paleo)}
    )
    source = FrozenOrogenReplacement(
        field,
        xyz,
        np.ones(1, bool),
        np.array([1000.0]),
        np.zeros(1),
        np.zeros(1),
        reference_id="ref",
    )
    delta, _ = source.evaluate(np.array([0.0]), np.array([0.0]))
    assert delta[0] == expected
    independent = max(900.0, active) - 1000.0 + max(1000.0, paleo) - 1000.0
    assert independent != expected


def test_joint_native_source_matches_both_single_sources_and_complete_envelope() -> None:
    fields, contract, geometry = _native_inputs()
    sutures = [AuthorSuture("old", "old", 53.0, np.array([[0.1, -1], [0.1, 1]]))]
    active_crest = float(np.median(collision_crests_m(contract, 9.80665, 650.0)))
    fields["land_crust_mask"][1] = False
    fields["orogen.segment.collision"][1] = 0
    fields["active_orogen_m"][1] = 0
    fields["paleo_orogen_m"] = np.where(
        fields["land_crust_mask"],
        paleo_orogen_field(fields["xyz"], sutures, active_crest, 6371.0),
        0,
    )
    fields["orogen.segment.background"] = np.array([700.0, 0.0, 0.0])
    fields["active_orogen_m"] = np.maximum(
        fields["active_orogen_m"], fields["orogen.segment.background"]
    )
    args = dict(radius_km=6371.0, gravity_m_s2=9.80665, base_m=650.0, reference_id="native-source")
    active = _native_collision(fields, contract, geometry)
    paleo = paleo_source_from_history(
        fields,
        sutures,
        suture_id="old",
        active_crest_m=active_crest,
        radius_km=6371.0,
        reference_id="native-source",
    )
    lat, lon = np.array([-1.05, 0.0, 0.95]), np.array([0.25, 0.25, 0.25])
    for collisions, old, single in [(("collision",), (), active), ((), ("old",), paleo)]:
        source = orogen_source_from_native(
            fields,
            contract,
            geometry,
            sutures,
            collision_segment_ids=collisions,
            paleo_suture_ids=old,
            **args,
        )
        np.testing.assert_array_equal(source.evaluate(lat, lon)[0], single.evaluate(lat, lon)[0])
    joint = orogen_source_from_native(
        fields,
        contract,
        geometry,
        sutures,
        collision_segment_ids=("collision",),
        paleo_suture_ids=("old",),
        **args,
    )
    q = lonlat_to_xyz(np.column_stack([lon, lat]))
    _, index = joint.tree.query(q)
    expected = np.maximum.reduce(
        [
            fields["orogen.segment.background"][index],
            np.where(fields["land_crust_mask"][index], active.profile_field(q), 0),
            np.where(fields["land_crust_mask"][index], paleo.profile_field(q), 0),
        ]
    ) - np.maximum(fields["active_orogen_m"][index], fields["paleo_orogen_m"][index])
    np.testing.assert_array_equal(joint.evaluate(lat, lon)[0], expected)
    np.testing.assert_allclose(
        np.concatenate([joint.evaluate(lat[:1], lon[:1])[0], joint.evaluate(lat[1:], lon[1:])[0]]),
        expected,
        rtol=0,
        atol=1e-8,
    )
    assert expected[1] == 0
