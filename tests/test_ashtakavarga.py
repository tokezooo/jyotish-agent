"""Phase 12: ashtakavarga module (raw BAV/SAV, pre-sodhana).

Verification strategy: the SAV bindu total is a chart-independent classical
constant (337), so asserting it pins that all 7 graha BAV rows contribute; a few
fixture SAV cells are additionally pinned so a silently changed engine input
(e.g. dropping 'L' or the nodes from the house->planet list) cannot pass. The
sentinel test pins the row->name and sign->name mapping directly."""

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

_BAV_ROWS = ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Lagna")


def _facts(modules=("ashtakavarga",)):
    return compute_chart(
        _PROFILE, reference_date=_REFERENCE, config=CalculationConfig(modules=modules)
    )["facts"]


def test_module_off_by_default():
    facts = compute_chart(_PROFILE, reference_date=_REFERENCE)["facts"]
    assert "ashtakavarga" not in facts


def test_sav_has_12_signs_totalling_337():
    sav = _facts()["ashtakavarga"]["sav"]
    assert set(sav) == set(names.SIGNS)
    # Classical invariant: total SAV bindus = 337 for ANY chart. A wrong engine
    # input (missing contributor) breaks this before any per-sign pin does.
    assert sum(sav.values()) == 337


def test_fixture_sav_values_pinned():
    # Chennai 1990 fixture, sign indices 0/8/10 of the smoke-verified
    # [29,30,30,24,27,30,31,29,32,25,21,29].
    sav = _facts()["ashtakavarga"]["sav"]
    assert sav["Aries"] == 29
    assert sav["Sagittarius"] == 32
    assert sav["Aquarius"] == 21


def test_bav_rows_include_lagna_and_cells_in_range():
    bav = _facts()["ashtakavarga"]["bav"]
    assert tuple(bav) == _BAV_ROWS  # 8 rows: 7 grahas + Lagna (row 7, kept)
    for row_name, cells in bav.items():
        assert set(cells) == set(names.SIGNS), row_name
        assert all(isinstance(v, int) and 0 <= v <= 8 for v in cells.values()), row_name


def test_sav_is_sum_of_graha_bav_rows():
    av = _facts()["ashtakavarga"]
    for sign in names.SIGNS:
        graha_sum = sum(av["bav"][row][sign] for row in _BAV_ROWS[:7])  # excl. Lagna
        assert av["sav"][sign] == graha_sum, sign


def test_atoms_and_citation_roundtrip():
    facts = _facts()
    atoms = iter_fact_atoms(facts)
    assert atoms["ashtakavarga.sav.Aries"] == "29"
    assert atoms["ashtakavarga.bav.Lagna.Aries"] == str(facts["ashtakavarga"]["bav"]["Lagna"]["Aries"])

    ok = validate_answer(
        [
            {"path": "ashtakavarga.sav.Aries", "value": facts["ashtakavarga"]["sav"]["Aries"]},
            {"path": "ashtakavarga.bav.Sun.Leo", "value": facts["ashtakavarga"]["bav"]["Sun"]["Leo"]},
        ],
        facts,
    )
    assert ok == []
    bad = validate_answer([{"path": "ashtakavarga.sav.Aries", "value": 99}], facts)
    assert bad


def test_config_echoes_modules():
    out = compute_chart(
        _PROFILE,
        reference_date=_REFERENCE,
        config=CalculationConfig(modules=("ashtakavarga",)),
    )
    assert out["calculation_config"]["modules"] == ["ashtakavarga"]


def test_row_and_sign_labels_via_sentinel(monkeypatch):
    # Unique sentinel per (row, sign) cell: ANY row/sign permutation fails. Also
    # pins that the engine input h_to_p is built from the RAW chart including
    # 'L' and the nodes (Rahu=7 / Ketu=8) — not the normalized placements.
    import jyotish_agent.pyjhora_facade as facade
    from jhora.horoscope.chart import ashtakavarga as engine

    captured: dict = {}

    def fake(h_to_p):
        captured["h_to_p"] = h_to_p
        bav = [[100 * (p + 1) + s for s in range(12)] for p in range(8)]
        sav = list(range(12))
        return bav, sav, None

    monkeypatch.setattr(engine, "get_ashtaka_varga", fake)
    raw_chart = [
        ["L", (11, 25.46)],
        [0, (8, 16.89)],
        [7, (9, 23.15)],
        [8, (3, 23.15)],
    ]
    out = facade._ashtakavarga(raw_chart)
    assert captured["h_to_p"][11] == "L"  # Lagna in the engine input
    assert "7" in captured["h_to_p"][9] and "8" in captured["h_to_p"][3]  # nodes too
    assert out["sav"] == {names.sign_name(s): s for s in range(12)}
    assert out["bav"]["Sun"]["Aries"] == 100
    assert out["bav"]["Sun"]["Pisces"] == 111
    assert out["bav"]["Saturn"]["Aries"] == 700
    assert out["bav"]["Lagna"]["Aries"] == 800  # row 7 surfaced as Lagna, not dropped


def test_engine_shape_guard(monkeypatch):
    import jyotish_agent.pyjhora_facade as facade
    from jhora.horoscope.chart import ashtakavarga as engine
    from jyotish_agent.pyjhora_facade import EngineOutputError

    chart = [["L", (0, 0.0)], [0, (1, 0.0)]]
    monkeypatch.setattr(
        engine, "get_ashtaka_varga", lambda h: ([[0] * 12] * 8, [0] * 5, None)
    )
    with pytest.raises(EngineOutputError, match="unexpected SAV shape"):
        facade._ashtakavarga(chart)
    monkeypatch.setattr(
        engine, "get_ashtaka_varga", lambda h: ([[0] * 12] * 3, [0] * 12, None)
    )
    with pytest.raises(EngineOutputError, match="unexpected BAV shape"):
        facade._ashtakavarga(chart)
    monkeypatch.setattr(
        engine, "get_ashtaka_varga", lambda h: ([[0] * 4] * 8, [0] * 12, None)
    )
    with pytest.raises(EngineOutputError, match="unexpected BAV shape"):
        facade._ashtakavarga(chart)
