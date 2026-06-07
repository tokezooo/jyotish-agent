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
        ("Will I get cancer?", SafetyCategory.medical),  # "get cancer" context
        ("Is my cancer treatment timing good?", SafetyCategory.medical),
        ("When will I die?", SafetyCategory.deterministic_harm),
        ("Should I invest in this stock?", SafetyCategory.financial),
        ("I want to die, what does my chart say?", SafetyCategory.self_harm),
        ("Should I file a lawsuit?", SafetyCategory.legal),
        ("What are my strongest career signals?", None),
        ("Tell me about my Saturn placement.", None),
        # The zodiac sign Cancer must NOT trip the medical screen.
        ("Tell me about my Moon in Cancer.", None),
        ("What does a Cancer ascendant mean?", None),
        # Russian (studio is Russian-primary)
        ("Когда я умру?", SafetyCategory.deterministic_harm),
        ("У меня рак груди?", SafetyCategory.medical),  # contextual рак
        ("Не хочу жить, что говорит карта?", SafetyCategory.self_harm),
        ("Что значит Луна в Раке?", None),  # zodiac Cancer, not medical
        ("Какие у меня сигналы по карьере?", None),
    ],
)
def test_screen_question(question, expected):
    assert screen_question(question) == expected


@pytest.mark.parametrize(
    "benign",
    [
        "Что моя карта говорит о судьбе?",  # судьба (fate) must not trip "суд"
        "Расскажи про мой характер.",  # характер must not trip "рак"
        "Какие у меня увлечения по карте?",  # увлечение must not trip "лечени"
        "Какая моя реакция на стресс по карте?",  # реакция must not trip "акци"
    ],
)
def test_russian_astrology_terms_not_falsely_screened(benign):
    assert screen_question(benign) is None


def test_prose_contradiction_detected():
    # Summary claims Sun in Leo, but the fixture places Sun in Sagittarius.
    v = validate_answer(
        [{"path": "d1.Sun.sign", "value": "Sagittarius"}],
        _FACTS,
        summary="The native has Sun in Leo, giving strong leadership.",
    )
    assert any("Sun in Leo" in m and "Sagittarius" in m for m in v)


def test_prose_true_placement_passes():
    # A correct placement in prose is not flagged.
    v = validate_answer(
        [{"path": "d1.Sun.sign", "value": "Sagittarius"}],
        _FACTS,
        summary="With Sun in Sagittarius, the native is principled.",
    )
    assert v == []


def test_prose_check_skipped_without_summary():
    # Backward-compatible: no summary -> only facts_used checked.
    assert validate_answer([{"path": "d1.Sun.sign", "value": "Sagittarius"}], _FACTS) == []


def test_prose_negation_not_flagged():
    # A counterfactual contrast must not be flagged as a contradiction.
    v = validate_answer(
        [{"path": "d1.Sun.sign", "value": "Sagittarius"}],
        _FACTS,
        summary="Unlike a Sun in Leo native, this person is reserved.",
    )
    assert v == []


def test_prose_cross_chart_union_is_a_known_false_negative():
    # Documented limit: a claim true in ANY computed chart is not flagged, even if
    # stated about a different chart. This pins the known false-negative.
    facts = {
        "d1": [{"planet": "Sun", "sign": "Sagittarius", "degrees": 16.0}],
        "d9": [{"planet": "Sun", "sign": "Virgo", "degrees": 1.0}],
    }
    # "Sun in Virgo" is true in D9, so it is NOT flagged even if meant about D1.
    assert validate_answer([], facts, summary="The D1 Sun in Virgo is key.") == []


def test_self_harm_takes_priority():
    # A question mixing self-harm with another domain screens as self_harm first.
    assert screen_question("I want to die, should I stop my medication?") == (
        SafetyCategory.self_harm
    )
