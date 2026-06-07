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

from jyotish_agent.config import ephemeris_mode  # noqa: E402
from jyotish_agent.pyjhora_facade import BirthProfile, compute_chart  # noqa: E402

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
    assert _compute() == expected


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
