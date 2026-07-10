"""Phase 13: gochara transits module.

Verification strategy: the from-Moon/from-lagna house math is pinned with a
sentinel transit chart (any anchor-sign off-by-one fails on the house-1 and
house-12 cases), and Saturn's transit sign is cross-checked against an EXTERNAL
ephemeris-derived value — not this engine's own output — so an ayanamsa or
reference-moment regression cannot pass by self-consistency."""

from __future__ import annotations

import pytest

pytest.importorskip("jhora", reason="PyJHora not installed; run `uv sync`")

from jyotish_agent import names  # noqa: E402
from jyotish_agent.config import CalculationConfig  # noqa: E402
from jyotish_agent.interpretations import iter_fact_atoms, validate_answer  # noqa: E402
from jyotish_agent.pyjhora_facade import BirthProfile, compute_chart  # noqa: E402

_PROFILE = BirthProfile(
    name="Chennai Test",
    date=(1990, 1, 1),
    time=(12, 30, 0),
    latitude=13.0827,
    longitude=80.2707,
    timezone=5.5,
)
_REFERENCE = (2026, 6, 7)


def _compute(modules=("transits",), reference=_REFERENCE):
    return compute_chart(
        _PROFILE, reference_date=reference, config=CalculationConfig(modules=modules)
    )


def _facts(modules=("transits",), reference=_REFERENCE):
    return _compute(modules=modules, reference=reference)["facts"]


def test_module_off_by_default():
    facts = compute_chart(_PROFILE, reference_date=_REFERENCE)["facts"]
    assert "transits" not in facts


def test_shape_anchor_and_natal_moon():
    tr = _facts()["transits"]
    assert set(tr) == {"anchor", "natal_moon_sign", "planets"}
    # Anchor is the documented noon-local snapshot of the reference date.
    assert tr["anchor"] == "2026-06-07T12:00:00"
    assert set(tr["planets"]) == set(names.PLANETS)  # all 9, no 'L' row
    for planet, info in tr["planets"].items():
        assert set(info) == {
            "sign_index", "sign", "degrees", "house_from_moon", "house_from_lagna"
        }, planet
        assert 1 <= info["house_from_moon"] <= 12
        assert 1 <= info["house_from_lagna"] <= 12


def test_natal_moon_sign_matches_natal_d1():
    facts = _facts()
    natal_moon = next(p for p in facts["d1"] if p["planet"] == "Moon")
    assert facts["transits"]["natal_moon_sign"] == natal_moon["sign"]


def test_reference_date_moves_transits_but_not_natal_facts():
    a = _compute(reference=(2026, 6, 7))
    b = _compute(reference=(2025, 1, 15))
    # Transit positions differ (the Sun alone moves ~1 sign/month)...
    assert (
        a["facts"]["transits"]["planets"]["Sun"]["sign"]
        != b["facts"]["transits"]["planets"]["Sun"]["sign"]
    )
    # ...while every natal fact is byte-identical (transits never touch the natal chart).
    for key in ("ascendant", "d1", "d9", "houses", "aspects", "panchanga", "yogas"):
        assert a["facts"][key] == b["facts"][key], key
    assert (
        a["facts"]["transits"]["natal_moon_sign"]
        == b["facts"]["transits"]["natal_moon_sign"]
    )


def test_house_from_moon_math_via_sentinel(monkeypatch):
    # Base cases of the whole-sign gochara count: a planet IN the natal Moon sign is
    # house 1; one sign BEFORE it is house 12. The transit 'L' row must be dropped
    # (its houses would be relative to the transit chart's own lagna — meaningless).
    import jyotish_agent.pyjhora_facade as facade
    from jhora.horoscope.chart import charts as engine_charts

    fake_chart = [
        ["L", (0, 5.0)],
        [0, (4, 10.0)],  # Sun in the natal Moon sign
        [1, (3, 20.0)],  # Moon one sign before it
    ]
    captured = {}

    def fake(jd, place, divisional_chart_factor):
        captured["factor"] = divisional_chart_factor
        return fake_chart

    monkeypatch.setattr(engine_charts, "divisional_chart", fake)
    out = facade._transits(
        0.0, None, natal_moon_sign=4, natal_lagna_sign=0, reference_date=(2026, 6, 7)
    )
    assert captured["factor"] == 1  # transit chart is D1
    assert out["natal_moon_sign"] == "Leo"
    assert out["anchor"] == "2026-06-07T12:00:00"
    assert out["planets"]["Sun"]["house_from_moon"] == 1
    assert out["planets"]["Moon"]["house_from_moon"] == 12
    assert out["planets"]["Sun"]["house_from_lagna"] == 5  # sign 4 from natal lagna 0
    assert set(out["planets"]) == {"Sun", "Moon"}  # no 'L' row emitted


def test_saturn_transit_sign_against_external_reference():
    # EXTERNAL cross-check (not this engine): published ephemerides put tropical
    # Saturn in early-to-mid Aries in June 2026 (it re-entered tropical Aries in
    # Feb 2026, moving ~0.1 deg/day). Subtracting the Lahiri ayanamsa (~24.2 deg in
    # 2026) gives a sidereal longitude of ~340-349 deg, i.e. sidereal PISCES.
    # A wrong ayanamsa, a natal-jd mixup, or a broken noon anchor would move this.
    tr = _facts()["transits"]
    assert tr["planets"]["Saturn"]["sign"] == "Pisces"


def test_sav_points_join_present_iff_both_modules_on():
    # transits alone: no sav_points field at all (absent, not null).
    solo = _facts()["transits"]["planets"]
    assert all("sav_points" not in info for info in solo.values())
    # transits + ashtakavarga: every planet carries the SAV bindus of its sign.
    facts = _facts(modules=("transits", "ashtakavarga"))
    sav = facts["ashtakavarga"]["sav"]
    for planet, info in facts["transits"]["planets"].items():
        assert info["sav_points"] == sav[info["sign"]], planet
        assert isinstance(info["sav_points"], int)


def test_atoms_and_citation_roundtrip():
    facts = _facts(modules=("transits", "ashtakavarga"))
    atoms = iter_fact_atoms(facts)
    saturn = facts["transits"]["planets"]["Saturn"]
    assert atoms["transits.Saturn.sign"] == "Pisces"
    assert atoms["transits.Saturn.house_from_moon"] == str(saturn["house_from_moon"])
    assert atoms["transits.Saturn.house_from_lagna"] == str(saturn["house_from_lagna"])
    assert atoms["transits.Saturn.sav_points"] == str(saturn["sav_points"])
    assert atoms["transits.natal_moon_sign"] == facts["transits"]["natal_moon_sign"]
    # anchor is context (the snapshot convention), not a citable claim.
    assert "transits.anchor" not in atoms

    ok = validate_answer(
        [
            {"path": "transits.Saturn.sign", "value": saturn["sign"]},
            {"path": "transits.Saturn.house_from_moon", "value": saturn["house_from_moon"]},
            {"path": "transits.natal_moon_sign", "value": facts["transits"]["natal_moon_sign"]},
        ],
        facts,
    )
    assert ok == []
    bad = validate_answer([{"path": "transits.Saturn.house_from_moon", "value": 99}], facts)
    assert bad
    invented = validate_answer([{"path": "transits.anchor", "value": "2026-06-07T12:00:00"}], facts)
    assert invented  # anchor is not citable


def test_no_sav_atoms_without_ashtakavarga():
    atoms = iter_fact_atoms(_facts())
    assert not any(path.endswith(".sav_points") for path in atoms)


def test_config_echoes_modules():
    out = _compute(modules=("transits",))
    assert out["calculation_config"]["modules"] == ["transits"]
