"""Phase 15: Tajaka varshaphal module (annual solar-return chart).

Verification strategy: the year-selection invariant pravesh(N) <= ref < pravesh(N+1)
is pinned EMPIRICALLY on both sides of a real pravesh boundary. For the Chennai
1990-01-01 fixture the natal Sun sits at Sagittarius ~16.89 deg, so the solar
return falls near Jan 1 each year (probed: years=37 pravesh = 2026-01-01T18:05:20
local, years=38 = 2027-01-02T00:17:25). A noon-anchored reference on 2026-01-01 is
therefore HOURS BEFORE that year's return — the active annual chart must still be
the previous year's (age_year 36, pravesh 2025-01-01T11:56:55). Calendar-year
arithmetic would silently pick the wrong chart there; that is the exact bug the
plan review caught. The munthi formula is pinned against the classical rule
(natal lagna + completed years) at two different ages so an off-by-one cannot
pass."""

from __future__ import annotations

import pytest

pytest.importorskip("jhora", reason="PyJHora not installed; run `uv sync`")

from jyotish_agent import names  # noqa: E402
from jyotish_agent.config import CalculationConfig, ConfigError  # noqa: E402
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

# Empirically probed pravesh moments (local, drik.next_solar_date under LAHIRI).
_PRAVESH_36 = "2025-01-01T11:56:55"  # 35th solar return -> age_year 36
_PRAVESH_37 = "2026-01-01T18:05:20"  # 36th solar return -> age_year 37


def _compute(modules=("varshaphal",), reference=_REFERENCE):
    return compute_chart(
        _PROFILE, reference_date=reference, config=CalculationConfig(modules=modules)
    )


def _facts(modules=("varshaphal",), reference=_REFERENCE):
    return _compute(modules=modules, reference=reference)["facts"]


def test_module_off_by_default():
    facts = compute_chart(_PROFILE, reference_date=_REFERENCE)["facts"]
    assert "varshaphal" not in facts


def test_shape():
    vp = _facts()["varshaphal"]
    assert set(vp) == {"pravesh", "age_year", "lagna", "planets", "munthi"}
    assert set(vp["lagna"]) == {"sign_index", "sign", "degrees"}
    assert set(vp["planets"]) == set(names.PLANETS)  # all 9, no 'L' row
    for planet, info in vp["planets"].items():
        assert set(info) == {"sign_index", "sign", "degrees"}, planet
        assert info["sign"] == names.sign_name(info["sign_index"])
    assert set(vp["munthi"]) == {"sign_index", "sign"}
    # Deviation pin: no year lord (varsheshvara) — the engine's lord_of_the_year is
    # off by one year vs annual_chart and has an index bug; school-dependent rule.
    assert "year_lord" not in vp


def test_active_year_at_fixture_reference():
    # Ref 2026-06-07 is AFTER the 2026-01-01T18:05 return and before the next one
    # (2027-01-02) -> the active annual chart is age_year 37.
    vp = _facts()["varshaphal"]
    assert vp["age_year"] == 37
    assert vp["pravesh"] == _PRAVESH_37


def test_pravesh_boundary_both_sides():
    # THE bug the plan review caught, at the fixture's REAL boundary: a noon
    # reference on the pravesh day itself (2026-01-01, return at 18:05) is before
    # the return, so the PREVIOUS year's chart is still active.
    before = _facts(reference=(2026, 1, 1))["varshaphal"]
    assert before["age_year"] == 36
    assert before["pravesh"] == _PRAVESH_36
    after = _facts(reference=(2026, 1, 2))["varshaphal"]
    assert after["age_year"] == 37
    assert after["pravesh"] == _PRAVESH_37
    assert before["pravesh"] != after["pravesh"]
    # The annual lagna moves too (different moment entirely).
    assert before["lagna"] != after["lagna"]


def test_reference_before_birth_rejected():
    with pytest.raises(ConfigError, match="before birth"):
        _compute(reference=(1989, 6, 1))


def test_deterministic():
    assert _compute() == _compute()


def test_munthi_classical_formula_pin():
    # Natal lagna is Pisces (index 11). Munthi = (natal lagna + completed years)
    # % 12, completed years = age_year - 1. Two different ages so an off-by-one
    # in either term cannot pass.
    natal_lagna = _facts()["ascendant"]
    assert natal_lagna["sign"] == "Pisces"
    vp37 = _facts()["varshaphal"]  # age_year 37 -> (11 + 36) % 12 = 11 Pisces
    assert vp37["age_year"] == 37
    assert vp37["munthi"] == {"sign_index": 11, "sign": "Pisces"}
    vp36 = _facts(reference=(2026, 1, 1))["varshaphal"]  # (11 + 35) % 12 = 10
    assert vp36["age_year"] == 36
    assert vp36["munthi"] == {"sign_index": 10, "sign": "Aquarius"}


def test_annual_sun_at_natal_longitude():
    # Definition of the solar return: the annual chart's Sun must sit at the natal
    # Sun's sidereal position (same sign, same degrees to well under a minute).
    facts = _facts()
    natal_sun = next(p for p in facts["d1"] if p["planet"] == "Sun")
    annual_sun = facts["varshaphal"]["planets"]["Sun"]
    assert annual_sun["sign"] == natal_sun["sign"] == "Sagittarius"
    assert abs(annual_sun["degrees"] - natal_sun["degrees"]) < 0.001


def test_natal_facts_unaffected():
    with_vp = _compute()
    without = compute_chart(_PROFILE, reference_date=_REFERENCE)
    for key in ("ascendant", "d1", "d9", "houses", "aspects", "panchanga", "yogas"):
        assert with_vp["facts"][key] == without["facts"][key], key


def test_atoms_and_citation_roundtrip():
    facts = _facts()
    vp = facts["varshaphal"]
    atoms = iter_fact_atoms(facts)
    assert atoms["varshaphal.pravesh"] == vp["pravesh"]
    assert atoms["varshaphal.lagna.sign"] == vp["lagna"]["sign"]
    assert atoms["varshaphal.munthi.sign"] == vp["munthi"]["sign"]
    for planet in names.PLANETS:
        assert atoms[f"varshaphal.{planet}.sign"] == vp["planets"][planet]["sign"]
    # age_year is context, deliberately NOT citable.
    assert "varshaphal.age_year" not in atoms

    ok = validate_answer(
        [
            {"path": "varshaphal.lagna.sign", "value": vp["lagna"]["sign"]},
            {"path": "varshaphal.munthi.sign", "value": vp["munthi"]["sign"]},
            {"path": "varshaphal.pravesh", "value": vp["pravesh"]},
            {"path": "varshaphal.Sun.sign", "value": vp["planets"]["Sun"]["sign"]},
        ],
        facts,
    )
    assert ok == []
    assert validate_answer([{"path": "varshaphal.age_year", "value": 37}], facts)
    assert validate_answer([{"path": "varshaphal.lagna.sign", "value": "Leo"}], facts)


def test_no_varshaphal_atoms_without_module():
    atoms = iter_fact_atoms(compute_chart(_PROFILE, reference_date=_REFERENCE)["facts"])
    assert not any(path.startswith("varshaphal.") for path in atoms)


def test_config_echoes_modules():
    out = _compute()
    assert out["calculation_config"]["modules"] == ["varshaphal"]


def test_reference_on_birth_date_is_valid_for_afternoon_birth():
    # Birth 12:30 local; ref_jd anchors at noon (< birth moment). The birth DATE is
    # still a valid reference: date-level guard + clamp must yield age_year 1.
    out = compute_chart(
        _PROFILE, reference_date=(1990, 1, 1), config=CalculationConfig(modules=("varshaphal",))
    )
    v = out["facts"]["varshaphal"]
    assert v["age_year"] == 1
    # pravesh of year 1 IS the birth moment.
    assert v["pravesh"].startswith("1990-01-01T12:30")


def test_exact_pravesh_moment_selects_new_year():
    # Half-open [pravesh(n), pravesh(n+1)): ref_jd exactly AT a pravesh belongs to
    # the NEW year. Only reachable at unit level (API refs are noon-anchored).
    import warnings

    from jhora import utils
    from jhora.panchanga import drik

    import jyotish_agent.pyjhora_facade as facade
    from jyotish_agent.config import apply_config

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        apply_config(CalculationConfig())
        place = drik.Place("Chennai", 13.0827, 80.2707, 5.5)
        jd = utils.julian_day_number((1990, 1, 1), (12, 30, 0))
        p37 = drik.next_solar_date(jd, place, years=37)
        natal_lagna = facade._lagna_sign(
            __import__("jhora.horoscope.chart.charts", fromlist=["charts"]).rasi_chart(jd, place)
        )
        out = facade._varshaphal(
            jd, place, p37, natal_lagna,
            birth_date=(1990, 1, 1), reference_date=(2026, 1, 1),
        )
    assert out["age_year"] == 37


def test_varshaphal_degrees_atoms_citable():
    facts = compute_chart(
        _PROFILE, reference_date=_REFERENCE, config=CalculationConfig(modules=("varshaphal",))
    )["facts"]
    atoms = iter_fact_atoms(facts)
    v = facts["varshaphal"]
    assert atoms["varshaphal.lagna.degrees"] == str(v["lagna"]["degrees"])
    assert atoms["varshaphal.Sun.degrees"] == str(v["planets"]["Sun"]["degrees"])
