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
    # Distinct in-range sentinels per (row, sign) cell: any row/sign permutation
    # fails while satisfying the strict facade invariants (BAV cells 0..8, SAV
    # total 337). Cell value = (p + s) % 9 gives 8 distinct row-patterns; SAV is a
    # fixed 12-vector summing to 337 with all-distinct leading entries. Also pins
    # that the engine input h_to_p is built from the RAW chart including 'L' and
    # the nodes (Rahu=7 / Ketu=8) — not the normalized placements.
    import jyotish_agent.pyjhora_facade as facade
    from jhora.horoscope.chart import ashtakavarga as engine

    captured: dict = {}
    sav_sentinel = [40, 39, 38, 37, 36, 35, 34, 33, 25, 10, 5, 5]
    assert sum(sav_sentinel) == 337

    def fake(h_to_p):
        captured["h_to_p"] = h_to_p
        bav = [[(p + s) % 9 for s in range(12)] for p in range(8)]
        return bav, list(sav_sentinel), None

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
    assert out["sav"] == {names.sign_name(s): sav_sentinel[s] for s in range(12)}
    assert out["bav"]["Sun"]["Aries"] == 0  # (0+0)%9
    assert out["bav"]["Sun"]["Pisces"] == 2  # (0+11)%9
    assert out["bav"]["Saturn"]["Aries"] == 6  # row 6
    assert out["bav"]["Lagna"]["Aries"] == 7  # row 7 surfaced as Lagna, not dropped


def test_strict_bindu_validation(monkeypatch):
    # Malformed engine values must never become cited facts.
    import jyotish_agent.pyjhora_facade as facade
    from jyotish_agent.pyjhora_facade import EngineOutputError
    from jhora.horoscope.chart import ashtakavarga as engine

    def make(bav_cell, sav_total_ok=True):
        bav = [[bav_cell] * 12 for _ in range(8)]
        sav = [28] * 11 + [29] if sav_total_ok else [1] * 12
        return lambda h: (bav, sav, None)

    raw = [["L", (0, 1.0)], [0, (1, 1.0)], [7, (2, 1.0)], [8, (3, 1.0)]]
    monkeypatch.setattr(engine, "get_ashtaka_varga", make(3.5))
    with pytest.raises(EngineOutputError, match="non-integral"):
        facade._ashtakavarga(raw)
    monkeypatch.setattr(engine, "get_ashtaka_varga", make(9))
    with pytest.raises(EngineOutputError, match="outside 0..8"):
        facade._ashtakavarga(raw)
    monkeypatch.setattr(engine, "get_ashtaka_varga", make(1, sav_total_ok=False))
    with pytest.raises(EngineOutputError, match="!= 337"):
        facade._ashtakavarga(raw)


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


def test_ketu_removal_leaves_tables_unchanged_rahu_required():
    # Engine reads Rahu (idx 7) before overriding row 7 with Lagna; Ketu (idx 8) is
    # unused by ashtakavarga. Pin both facts against the REAL engine so a future
    # engine change that starts using the nodes is caught.
    import warnings

    from jhora import utils
    from jhora.horoscope.chart import ashtakavarga, charts
    from jhora.panchanga import drik

    from jyotish_agent.config import apply_config, CalculationConfig

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        apply_config(CalculationConfig())
        place = drik.Place("Chennai", 13.0827, 80.2707, 5.5)
        jd = utils.julian_day_number((1990, 1, 1), (12, 30, 0))
        chart = charts.rasi_chart(jd, place)
        full = ashtakavarga.get_ashtaka_varga(
            utils.get_house_planet_list_from_planet_positions(chart)
        )
        no_ketu = ashtakavarga.get_ashtaka_varga(
            utils.get_house_planet_list_from_planet_positions(
                [row for row in chart if row[0] != 8]
            )
        )
    assert full[0] == no_ketu[0] and full[1] == no_ketu[1]  # BAV+SAV identical
    # Rahu removal raises (engine indexes planet 7 before the Lagna override).
    import pytest as _pytest

    with _pytest.raises(Exception):
        ashtakavarga.get_ashtaka_varga(
            utils.get_house_planet_list_from_planet_positions(
                [row for row in chart if row[0] != 7]
            )
        )
