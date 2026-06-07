"""Fact-citation contract + safety screening tests.

These are the Phase 5 exit criteria: an answer that cites a fact absent from the
computed facts MUST fail validation, and unsafe questions MUST be screened.
Uses the static golden fixture facts (no engine needed)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jyotish_agent.interpretations import (
    SafetyCategory,
    iter_fact_atoms,
    redirect_message,
    screen_question,
    validate_answer,
)

# Contract logic is ephemeris-independent; the Moshier baseline fixture is always
# present (committed) and sufficient for citation-path tests.
_FACTS = json.loads(
    (Path(__file__).parent / "fixtures" / "golden_chennai_1990_moshier.json").read_text()
)["facts"]


def test_atoms_include_meaningful_leaves_not_indices():
    atoms = iter_fact_atoms(_FACTS)
    assert atoms["ascendant.sign"] == "Pisces"
    assert atoms["d1.Sun.sign"] == "Sagittarius"
    assert atoms["d9.Sun.sign"] == "Virgo"
    assert atoms["panchanga.nakshatra"] == "Shatabhisha"
    assert atoms["panchanga.nakshatra.pada"] == "1"
    assert atoms["panchanga.karana"] == "Bava"
    assert atoms["vimshottari.mahadasha.lord"] == "Saturn"
    assert atoms["vimshottari.antara.lord"] == "Rahu"
    assert atoms["vimshottari.bhukti.start"] == "2023-11-24T13:35:10"
    # Raw indices are not citation targets.
    assert "panchanga.nakshatra.index" not in atoms


def test_empty_facts_used_and_empty_facts():
    # validate_answer itself is permissive on empty list (the API model enforces
    # min_length=1); empty facts makes every citation a violation.
    assert validate_answer([], _FACTS) == []
    assert validate_answer([{"path": "ascendant.sign", "value": "Pisces"}], {}) != []


def test_path_matching_is_case_sensitive():
    # Lowercase planet slips are rejected (documents intent; the skill fixes casing).
    assert validate_answer([{"path": "d1.sun.sign", "value": "Sagittarius"}], _FACTS) != []


def test_non_finite_degree_citation_never_matches():
    assert validate_answer([{"path": "d1.Sun.degrees", "value": "nan"}], _FACTS) != []
    assert validate_answer([{"path": "d1.Sun.degrees", "value": "inf"}], _FACTS) != []


def test_redirect_message_for_every_category():
    for cat in SafetyCategory:
        assert redirect_message(cat)


def test_answer_citing_real_facts_is_valid():
    facts_used = [
        {"path": "d1.Sun.sign", "value": "Sagittarius"},
        {"path": "vimshottari.mahadasha.lord", "value": "Saturn"},
        {"path": "ascendant.sign", "value": "Pisces"},
    ]
    assert validate_answer(facts_used, _FACTS) == []


def test_answer_citing_invented_placement_fails():
    # The whole product in one test: claiming Sun in Leo when it's Sagittarius.
    violations = validate_answer([{"path": "d1.Sun.sign", "value": "Leo"}], _FACTS)
    assert len(violations) == 1
    assert "Sagittarius" in violations[0]


def test_answer_citing_unknown_path_fails():
    violations = validate_answer([{"path": "d1.Pluto.sign", "value": "Aries"}], _FACTS)
    assert len(violations) == 1
    assert "not in the computed facts" in violations[0]


def test_degrees_float_tolerance():
    exact = iter_fact_atoms(_FACTS)["d1.Sun.degrees"]  # e.g. "16.886946"
    # A citation rounded to 4 dp must still validate.
    rounded = round(float(exact), 4)
    assert validate_answer([{"path": "d1.Sun.degrees", "value": rounded}], _FACTS) == []
    # A genuinely wrong degree fails.
    assert validate_answer([{"path": "d1.Sun.degrees", "value": 99.0}], _FACTS)


def test_multiple_violations_reported():
    violations = validate_answer(
        [
            {"path": "d1.Sun.sign", "value": "Leo"},
            {"path": "panchanga.nakshatra", "value": "Revati"},
            {"path": "d1.Moon.sign", "value": "Aquarius"},  # this one is correct
        ],
        _FACTS,
    )
    assert len(violations) == 2


@pytest.mark.parametrize(
    "question,expected",
    [
        ("Will I get cancer?", SafetyCategory.medical),
        ("When will I die?", SafetyCategory.deterministic_harm),
        ("Should I invest in this stock?", SafetyCategory.financial),
        ("I want to die, what does my chart say?", SafetyCategory.self_harm),
        ("Should I file a lawsuit?", SafetyCategory.legal),
        ("What are my strongest career signals?", None),
        ("Tell me about my Saturn placement.", None),
    ],
)
def test_screen_question(question, expected):
    assert screen_question(question) == expected


def test_self_harm_takes_priority():
    # A question mixing self-harm with another domain screens as self_harm first.
    assert screen_question("I want to die, should I stop my medication?") == (
        SafetyCategory.self_harm
    )
