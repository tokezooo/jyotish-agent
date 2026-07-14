from __future__ import annotations

from jyotish_agent.doctrine.prashna_pack import prashna_aspect_profile
from jyotish_agent.prashna import calculate_prashna_aspect_geometry
from jyotish_agent.prashna_models import PrashnaAspectGeometryInput


ANCHOR = "a" * 64


def _admitted_tajika():
    return prashna_aspect_profile("tajika_nilakanthi_overlay").model_copy(
        update={
            "source_admitted": True,
            "source_refs": ("test-fixture:tajika:hand-checked",),
        }
    )


def _input(**updates: object) -> PrashnaAspectGeometryInput:
    payload = {
        "anchor_sha256": ANCHOR,
        "body_a": "lagna_lord",
        "body_b": "primary_house_lord",
        "longitude_a": 10.0,
        "longitude_b": 68.0,
        "speed_a": 0.5,
        "speed_b": 1.0,
        "aspect_degrees": 60.0,
    }
    payload.update(updates)
    return PrashnaAspectGeometryInput.model_validate(payload)


def test_hand_checked_applying_exact_and_separating_states() -> None:
    profile = _admitted_tajika()
    applying = calculate_prashna_aspect_geometry(_input(), profile)
    exact = calculate_prashna_aspect_geometry(_input(longitude_b=70.0), profile)
    separating = calculate_prashna_aspect_geometry(_input(longitude_b=72.0), profile)
    assert applying.state == "applying"
    assert applying.orb_degrees == 2.0
    assert exact.state == "exact"
    assert exact.orb_degrees == 0.0
    assert separating.state == "separating"


def test_wraparound_retrograde_and_body_swap_are_invariant() -> None:
    profile = _admitted_tajika()
    value = _input(
        longitude_a=359.0,
        longitude_b=61.0,
        speed_a=-0.2,
        speed_b=-0.8,
    )
    original = calculate_prashna_aspect_geometry(value, profile)
    swapped = calculate_prashna_aspect_geometry(
        value.model_copy(
            update={
                "body_a": value.body_b,
                "body_b": value.body_a,
                "longitude_a": value.longitude_b,
                "longitude_b": value.longitude_a,
                "speed_a": value.speed_b,
                "speed_b": value.speed_a,
            }
        ),
        profile,
    )
    assert original.state == "applying"
    assert original.orb_degrees == 2.0
    assert swapped.state == original.state
    assert swapped.orb_degrees == original.orb_degrees


def test_station_and_orb_boundary_return_unavailable_with_lower_confidence() -> None:
    profile = _admitted_tajika()
    station = calculate_prashna_aspect_geometry(
        _input(speed_a=0.5001, speed_b=0.5), profile
    )
    boundary = calculate_prashna_aspect_geometry(_input(longitude_b=76.0), profile)
    assert station.state == "unavailable"
    assert station.reason_code == "RELATIVE_MOTION_UNCERTAIN"
    assert boundary.state == "unavailable"
    assert boundary.reason_code == "ORB_BOUNDARY_AMBIGUOUS"
    assert station.confidence < 0.5


def test_baseline_and_tajika_profiles_are_explicit_and_disallowed_aspects_prohibit() -> (
    None
):
    baseline = prashna_aspect_profile("prasna_marga_baseline")
    tajika = prashna_aspect_profile("tajika_nilakanthi_overlay")
    assert baseline.profile_kind == "baseline"
    assert tajika.profile_kind == "overlay"
    assert tajika.base_profile_id == baseline.profile_id
    assert 60.0 not in baseline.allowed_aspects
    assert 60.0 in tajika.allowed_aspects

    result = calculate_prashna_aspect_geometry(
        _input(aspect_degrees=60.0),
        baseline.model_copy(
            update={"source_admitted": True, "source_refs": ("fixture",)}
        ),
    )
    assert result.state == "prohibited"
    assert result.reason_code == "ASPECT_NOT_IN_PROFILE"


def test_unadmitted_tajika_source_fails_closed() -> None:
    result = calculate_prashna_aspect_geometry(
        _input(), prashna_aspect_profile("tajika_nilakanthi_overlay")
    )
    assert result.state == "unavailable"
    assert result.reason_code == "SOURCE_ADMISSION_MISSING"
    assert result.source_refs == ()


def test_anchor_replay_rotation_and_dst_labels_cannot_change_numeric_geometry() -> None:
    profile = _admitted_tajika()
    base = calculate_prashna_aspect_geometry(_input(), profile)
    rotated = calculate_prashna_aspect_geometry(
        _input(longitude_a=110.0, longitude_b=168.0), profile
    )
    replay = calculate_prashna_aspect_geometry(_input(), profile)
    assert base == replay
    assert rotated.state == base.state
    assert rotated.orb_degrees == base.orb_degrees
    assert base.anchor_sha256 == ANCHOR
    assert base.timing_unit == "doctrine_controlled"
