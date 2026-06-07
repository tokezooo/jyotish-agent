"""Golden-fixture + determinism tests for the PyJHora facade.

Phase 2 exit criteria: one known birth profile produces a stable fact set, and
repeated runs are byte-identical (no wall-clock timestamps in the output).

Note: golden fixtures are keyed by ephemeris mode. The Moshier baseline
(``golden_chennai_1990_moshier.json``) is committed and is what CI checks. The Swiss
fixture is generated locally (not committed) and the Swiss path is also covered by a
tolerance-based parity test (Swiss vs Moshier). The exact-match test skips when no
fixture exists for the active mode.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("jhora", reason="PyJHora not installed; run `uv sync`")

from jyotish_agent.config import CalculationConfig, ephemeris_mode  # noqa: E402
from jyotish_agent.interpretations import iter_fact_atoms  # noqa: E402
from jyotish_agent.pyjhora_facade import (  # noqa: E402
    BirthProfile,
    _fmt_dt,
    compute_chart,
)

_FIXTURES = Path(__file__).parent / "fixtures"
# Values differ between Swiss and Moshier ephemerides, so the golden fixture is keyed
# by the active mode. CI without .se1 files runs the Moshier baseline.
_GOLDEN = _FIXTURES / f"golden_chennai_1990_{ephemeris_mode()}.json"

_PROFILE = BirthProfile(
    name="Chennai Test",
    date=(1990, 1, 1),
    time=(12, 30, 0),
    latitude=13.0827,
    longitude=80.2707,
    timezone=5.5,
)
_REFERENCE = (2026, 6, 7)


def _compute() -> dict:
    return compute_chart(_PROFILE, reference_date=_REFERENCE)


def test_golden_fixture_matches():
    if not _GOLDEN.exists():
        pytest.skip(f"no golden fixture for {ephemeris_mode()} mode ({_GOLDEN.name})")
    expected = json.loads(_GOLDEN.read_text())
    # Compare serialized form: immune to float-repr drift and dict ordering.
    assert json.dumps(_compute(), sort_keys=True) == json.dumps(expected, sort_keys=True)


def test_swiss_enables_star_based_ayanamsa():
    # TRUE_CITRA crashes under Moshier; with Swiss .se1 files it must compute.
    if ephemeris_mode() != "swiss":
        pytest.skip("Swiss ephemeris not installed (Moshier fallback)")
    out = compute_chart(
        _PROFILE, reference_date=_REFERENCE, config=CalculationConfig(ayanamsa="TRUE_CITRA")
    )
    assert out["calculation_config"]["ayanamsa"] == "TRUE_CITRA"
    assert out["facts"]["ascendant"]["sign"] is not None


def test_swiss_moshier_consistency():
    # Parity check: Swiss output agrees with the Moshier baseline to within a small
    # tolerance (same sign, sub-0.1deg), confirming the fallback was a faithful
    # approximation and the Swiss path is wired correctly.
    if ephemeris_mode() != "swiss":
        pytest.skip("Swiss ephemeris not installed")
    moshier = json.loads((_FIXTURES / "golden_chennai_1990_moshier.json").read_text())
    swiss = _compute()
    m_by_planet = {p["planet"]: p for p in moshier["facts"]["d1"]}
    for p in swiss["facts"]["d1"]:
        mm = m_by_planet[p["planet"]]
        assert p["sign"] == mm["sign"], f"{p['planet']} sign differs"
        # Real Swiss-vs-Moshier drift is sub-0.002deg here; 0.01deg is tight enough to
        # catch a wiring bug (e.g. a planet ~half a degree off) yet pass true drift.
        assert abs(p["degrees"] - mm["degrees"]) < 0.01, f"{p['planet']} degrees drift"


def test_known_values_independent_of_ephemeris():
    # Weekday is derived from the civil calendar date, not the ephemeris, so it must
    # always hold regardless of Moshier vs Swiss. 1990-01-01 was a Monday. This keeps
    # at least one exact-value assertion alive even when the golden test skips.
    out = _compute()
    assert out["facts"]["panchanga"]["weekday"]["name"] == "Monday"
    assert out["facts"]["ascendant"]["sign"] is not None


def test_output_is_byte_stable():
    # No wall-clock timestamps in output, so repeated runs serialize identically.
    a = json.dumps(_compute(), sort_keys=True)
    b = json.dumps(_compute(), sort_keys=True)
    assert a == b


def test_fact_structure_invariants():
    # Structure must hold regardless of ephemeris mode.
    out = _compute()
    facts = out["facts"]
    assert set(out) == {"normalized_input", "calculation_config", "facts", "provenance"}
    assert len(facts["d1"]) == 9  # nine grahas, Lagna surfaced separately
    assert len(facts["d9"]) == 9
    assert facts["ascendant"]["sign"] is not None
    assert out["calculation_config"]["ayanamsa"] == "LAHIRI"
    assert {p["planet"] for p in facts["d1"]} == {
        "Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu",
    }
    assert facts["vimshottari"]["mahadasha"]["lord"] is not None
    for level in ("tithi", "nakshatra", "yoga", "karana", "weekday"):
        assert facts["panchanga"][level]["name"] is not None


def test_reference_date_changes_running_dasha():
    early = compute_chart(_PROFILE, reference_date=(1995, 1, 1))
    late = compute_chart(_PROFILE, reference_date=(2040, 1, 1))
    assert (
        early["facts"]["vimshottari"]["mahadasha"]["lord"]
        != late["facts"]["vimshottari"]["mahadasha"]["lord"]
    )


def test_pre_birth_reference_date_degrades_gracefully():
    # A reference before birth has no running dasha. Must not crash; structure holds.
    out = compute_chart(_PROFILE, reference_date=(1980, 1, 1))
    levels = out["facts"]["vimshottari"]
    assert set(levels) == {"mahadasha", "bhukti", "antara"}  # keys always present


def test_requesting_extra_divisional_chart():
    out = compute_chart(
        _PROFILE, reference_date=_REFERENCE, config=CalculationConfig(charts=("D9", "D10"))
    )
    facts = out["facts"]
    assert "d10" in facts and len(facts["d10"]) == 9
    assert "d1" in facts and "d9" in facts  # D1 always, D9 requested
    assert out["calculation_config"]["charts"] == ["D1", "D9", "D10"]
    # New divisional is citable through the contract.
    assert "d10.Sun.sign" in iter_fact_atoms(facts)


def test_default_charts_unchanged():
    facts = _compute()["facts"]
    assert set(k for k in facts if k.startswith("d")) == {"d1", "d9"}


def test_houses_and_planet_house():
    facts = _compute()["facts"]
    # Pisces lagna: Sun in Sagittarius is the 10th house.
    sun = next(p for p in facts["d1"] if p["planet"] == "Sun")
    assert sun["house"] == 10
    houses = facts["houses"]
    assert len(houses) == 12
    assert houses[0] == {
        "house": 1,
        "sign_index": 11,
        "sign": "Pisces",
        "lord_index": 4,
        "lord": "Jupiter",
    }
    h10 = houses[9]
    assert h10["house"] == 10 and h10["sign"] == "Sagittarius" and h10["lord"] == "Jupiter"
    atoms = iter_fact_atoms(facts)
    assert atoms["d1.Sun.house"] == "10"
    assert atoms["houses.10.lord"] == "Jupiter"
    assert atoms["houses.1.sign"] == "Pisces"
    # Non-D1 charts carry their own (varga-lagna) houses, and they're citable.
    assert any(k.startswith("d9.") and k.endswith(".house") for k in atoms)


def test_graha_drishti():
    facts = _compute()["facts"]
    atoms = iter_fact_atoms(facts)
    # Saturn (Sagittarius, sign 8) special aspects offsets {2,6,9} -> signs
    # Aquarius(10)=Moon, Gemini(2)=Jupiter, Virgo(5)=empty. So Saturn aspects Moon + Jupiter.
    assert atoms.get("aspects.Saturn.Moon") == "true"
    assert atoms.get("aspects.Saturn.Jupiter") == "true"
    # 7th-aspect for a non-special planet: Sun (Sag, 8) aspects sign 2 (Gemini) -> Jupiter.
    assert atoms.get("aspects.Sun.Jupiter") == "true"
    # No self-aspect.
    assert "aspects.Saturn.Saturn" not in atoms
    # One planet aspecting several planets in one sign: Jupiter (Gemini, 2) 7th-aspects
    # Sagittarius (Sun, Saturn) and special-aspects Aquarius (Moon) -> >= 3 targets.
    assert len(facts["aspects"]["Jupiter"]["aspects_planets"]) >= 3
    # aspected_houses is shipped as context; pin Saturn's (10th aspect lands somewhere).
    assert len(facts["aspects"]["Saturn"]["aspected_houses"]) == 3


def test_aspect_offsets_rules():
    from jyotish_agent import names

    assert names.aspect_offsets(0) == frozenset({6})  # Sun: 7th only
    assert names.aspect_offsets(2) == frozenset({3, 6, 7})  # Mars
    assert names.aspect_offsets(4) == frozenset({4, 6, 8})  # Jupiter
    assert names.aspect_offsets(6) == frozenset({2, 6, 9})  # Saturn
    assert names.aspect_offsets(7) == frozenset({6})  # Rahu: 7th only (MVP)


def test_house_base_case_planet_in_lagna_is_first_house():
    from jyotish_agent.pyjhora_facade import _placements

    # Synthetic chart: lagna and a planet both in sign 5 -> house 1; sign 4 -> house 12.
    chart = [["L", (5, 0.0)], [0, (5, 10.0)], [1, (4, 2.0)]]
    placements = {p["planet_index"]: p["house"] for p in _placements(chart)}
    assert placements[0] == 1  # same sign as lagna
    assert placements[1] == 12  # one sign before lagna


def test_fmt_dt_rolls_over_midnight():
    # 23:59:59.6 must roll into the next day, never emit 'T24:00:00'.
    assert _fmt_dt((2026, 1, 1, 23 + 59 / 60 + 59.6 / 3600)) == "2026-01-02T00:00:00"
    assert _fmt_dt((2026, 1, 1, 0)) == "2026-01-01T00:00:00"
    assert _fmt_dt((2026, 12, 31, 23.9999)) == "2027-01-01T00:00:00"
    # Exact half-day.
    assert _fmt_dt((2026, 6, 7, 12.5)) == "2026-06-07T12:30:00"
