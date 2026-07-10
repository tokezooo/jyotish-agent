"""Phase 11: shadbala module + opt-in config.modules infrastructure.

Label-verification strategy: the naisargika (natural) bala is a fixed classical
constant per planet (Sun 60 ... Saturn 8.57 virupas), so asserting those values pins
the component-row order of PyJHora's shad_bala output — a swapped kaala/dig row
cannot pass while naisargika still lands on its constants."""

from __future__ import annotations

import pytest

pytest.importorskip("jhora", reason="PyJHora not installed; run `uv sync`")

from jyotish_agent.config import CalculationConfig, ConfigError  # noqa: E402
from jyotish_agent.interpretations import iter_fact_atoms  # noqa: E402
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

_NAISARGIKA = {  # classical constants, virupas
    "Sun": 60.0,
    "Moon": 51.43,
    "Mars": 17.14,
    "Mercury": 25.71,
    "Jupiter": 34.29,
    "Venus": 42.86,
    "Saturn": 8.57,
}


def _facts(modules=("shadbala",)):
    return compute_chart(
        _PROFILE, reference_date=_REFERENCE, config=CalculationConfig(modules=modules)
    )["facts"]


def test_module_off_by_default():
    facts = compute_chart(_PROFILE, reference_date=_REFERENCE)["facts"]
    assert "shadbala" not in facts


def test_unknown_module_rejected():
    with pytest.raises(ConfigError, match="unknown modules"):
        compute_chart(
            _PROFILE, reference_date=_REFERENCE, config=CalculationConfig(modules=("nope",))
        )


def test_known_but_unimplemented_module_rejected():
    # Silent 200-with-nothing would make the agent loop on missing facts (same
    # pathology as the facts_token echo bug). Must be a hard error until implemented.
    with pytest.raises(ConfigError, match="not implemented yet"):
        compute_chart(
            _PROFILE, reference_date=_REFERENCE, config=CalculationConfig(modules=("transits",))
        )


def test_seven_grahas_no_nodes():
    sb = _facts()["shadbala"]
    assert set(sb) == {"Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"}


def test_naisargika_constants_pin_component_labels():
    sb = _facts()["shadbala"]
    for planet, expected in _NAISARGIKA.items():
        assert abs(sb[planet]["components"]["naisargika"] - expected) < 0.02, planet


def test_component_sum_matches_rupas():
    sb = _facts()["shadbala"]
    for planet, info in sb.items():
        virupa_sum = sum(info["components"].values())
        assert abs(virupa_sum / 60 - info["rupas"]) < 0.05, planet


def test_negative_drik_is_allowed():
    # Engine formula (dkp-dkm)/4 can be negative; this fixture has negative drik for
    # Moon/Jupiter under both ephemerides today. If an ephemeris bump flips it, only
    # this pin needs revisiting — the sum test above is independent.
    sb = _facts()["shadbala"]
    assert any(info["components"]["drik"] < 0 for info in sb.values())


def test_atoms_and_citation_roundtrip():
    facts = _facts()
    atoms = iter_fact_atoms(facts)
    assert atoms["shadbala.Sun.components.naisargika"] == "60.0"
    assert float(atoms["shadbala.Jupiter.rupas"]) > 0
    from jyotish_agent.interpretations import validate_answer

    ok = validate_answer(
        [{"path": "shadbala.Sun.rupas", "value": facts["shadbala"]["Sun"]["rupas"]}],
        facts,
    )
    assert ok == []
    bad = validate_answer([{"path": "shadbala.Sun.rupas", "value": 99.9}], facts)
    assert bad


def test_config_echoes_modules():
    out = compute_chart(
        _PROFILE, reference_date=_REFERENCE, config=CalculationConfig(modules=("shadbala",))
    )
    assert out["calculation_config"]["modules"] == ["shadbala"]


def test_component_labels_via_sentinel_rows(monkeypatch):
    # Unique sentinel per row: ANY row/label permutation fails, not just naisargika.
    import jyotish_agent.pyjhora_facade as facade
    from jhora.horoscope.chart import strength

    sentinel = [[float(100 * (i + 1) + p) for p in range(7)] for i in range(9)]
    monkeypatch.setattr(strength, "shad_bala", lambda jd, place: sentinel)
    out = facade._shadbala(0.0, None)
    sun = out["Sun"]
    expected = dict(zip(
        ("sthana", "kaala", "dig", "cheshta", "naisargika", "drik"),
        (100.0, 200.0, 300.0, 400.0, 500.0, 600.0),
    ))
    assert sun["components"] == expected
    assert sun["rupas"] == 800.0 and sun["strength_ratio"] == 900.0


def test_engine_shape_guard(monkeypatch):
    import jyotish_agent.pyjhora_facade as facade
    from jyotish_agent.pyjhora_facade import EngineOutputError
    from jhora.horoscope.chart import strength

    monkeypatch.setattr(strength, "shad_bala", lambda jd, place: [[1.0] * 7] * 3)
    with pytest.raises(EngineOutputError, match="unexpected shape"):
        facade._shadbala(0.0, None)
    monkeypatch.setattr(strength, "shad_bala", lambda jd, place: [[float("nan")] * 7] * 9)
    with pytest.raises(EngineOutputError, match="non-finite"):
        facade._shadbala(0.0, None)
