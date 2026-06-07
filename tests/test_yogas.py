"""Tests for the narrow geometric yoga detectors.

Synthetic charts give exact control over the geometry so each yoga's definition is
verified directly; the golden fixture is used as a real-data negative."""

from __future__ import annotations

import json
from pathlib import Path

from jyotish_agent.yogas import detect_yogas

_FACTS = json.loads(
    (Path(__file__).parent / "fixtures" / "golden_chennai_1990_moshier.json").read_text()
)["facts"]


def _p(planet: str, sign: int) -> dict:
    return {"planet": planet, "sign_index": sign, "sign": "X", "degrees": 0.0, "house": 1}


def test_gajakesari_present_when_jupiter_in_kendra_from_moon():
    # Moon in Aries(0); Jupiter in Cancer(3) = 4th from Moon (a kendra).
    y = detect_yogas([_p("Moon", 0), _p("Jupiter", 3)])
    assert y["Gajakesari"]["present"] is True
    assert y["Gajakesari"]["basis"]["jupiter_house_from_moon"] == 4


def test_gajakesari_absent_when_not_kendra():
    # Moon Aries(0), Jupiter Gemini(2) = 3rd from Moon (not a kendra).
    y = detect_yogas([_p("Moon", 0), _p("Jupiter", 2)])
    assert y["Gajakesari"]["present"] is False


def test_chandra_mangala_present_on_conjunction():
    y = detect_yogas([_p("Moon", 5), _p("Mars", 5)])
    assert y["Chandra-Mangala"]["present"] is True
    y2 = detect_yogas([_p("Moon", 5), _p("Mars", 6)])
    assert y2["Chandra-Mangala"]["present"] is False


def test_budha_aditya_present_on_conjunction():
    y = detect_yogas([_p("Sun", 8), _p("Mercury", 8)])
    assert y["Budha-Aditya"]["present"] is True
    y2 = detect_yogas([_p("Sun", 8), _p("Mercury", 9)])
    assert y2["Budha-Aditya"]["present"] is False


def test_missing_planets_yield_no_entry():
    y = detect_yogas([_p("Sun", 0)])  # no Moon/Jupiter/Mars/Mercury
    assert "Gajakesari" not in y and "Chandra-Mangala" not in y


def test_each_yoga_states_its_definition():
    y = detect_yogas([_p("Moon", 0), _p("Jupiter", 3), _p("Mars", 0), _p("Sun", 8), _p("Mercury", 8)])
    for name in ("Gajakesari", "Chandra-Mangala", "Budha-Aditya"):
        assert y[name]["definition"]  # non-empty, reproducible convention


def test_golden_fixture_real_chart_negatives():
    # Chennai 1990 fixture: none of the three are present (Moon/Jup not kendra, no
    # Moon-Mars or Sun-Mercury conjunction). Documents real-data behavior.
    y = detect_yogas(_FACTS["d1"])
    assert y["Gajakesari"]["present"] is False
    assert y["Chandra-Mangala"]["present"] is False
    assert y["Budha-Aditya"]["present"] is False
