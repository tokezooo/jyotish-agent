"""Golden-fixture + determinism tests for the PyJHora facade.

Phase 2 exit criteria: one known birth profile produces a stable fact set, and
repeated runs are byte-identical (no wall-clock timestamps in the output).

Note: the golden values are computed under the Moshier fallback (no .se1 files).
If Swiss ephemeris files are installed, placements shift slightly, so the exact
comparison is skipped and only the structural/determinism invariants run.
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

_GOLDEN = Path(__file__).parent / "fixtures" / "golden_chennai_1990.json"

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
    if ephemeris_mode() != "moshier":
        pytest.skip("golden values are Moshier-fallback specific; .se1 present")
    expected = json.loads(_GOLDEN.read_text())
    # Compare serialized form: immune to float-repr drift and dict ordering.
    assert json.dumps(_compute(), sort_keys=True) == json.dumps(expected, sort_keys=True)


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
