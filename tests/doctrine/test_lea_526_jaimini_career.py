from __future__ import annotations

import json
from pathlib import Path

from jaimini_helpers import build_jaimini_graph
from jyotish_agent.doctrine.jaimini_pack import (
    JaiminiTopic,
    analyze_jaimini_topic,
    render_jaimini_topic_report,
)


ROOT = Path(__file__).parents[2]


def _graph():
    facts = {
        "jaimini.karakas.7.AmK": "Mercury",
        "jaimini.arudha.AL": "Leo",
        "jaimini.argala.AL.2_vs_12.status": "unobstructed",
        "jaimini.rasi_drishti.planet.Mercury.signs": "Gemini,Virgo",
        "jaimini.chara_dasha.1.active": True,
    }
    rules = [
        {
            "rule_id": "career.amk",
            "topic": "career",
            "premises": [
                {"path": "jaimini.karakas.7.AmK", "operator": "exists", "value": None}
            ],
        },
        {
            "rule_id": "career.arudha",
            "topic": "status",
            "premises": [
                {"path": "jaimini.arudha.AL", "operator": "exists", "value": None}
            ],
            "conflicts_with": ["career.argala"],
        },
        {
            "rule_id": "career.argala",
            "topic": "activity",
            "premises": [
                {
                    "path": "jaimini.argala.AL.2_vs_12.status",
                    "operator": "exists",
                    "value": None,
                }
            ],
            "conflicts_with": ["career.arudha"],
        },
        {
            "rule_id": "career.drishti",
            "topic": "activity",
            "premises": [
                {
                    "path": "jaimini.rasi_drishti.planet.Mercury.signs",
                    "operator": "exists",
                    "value": None,
                }
            ],
        },
        {
            "rule_id": "timing.separate",
            "topic": "timing",
            "time_scope": "period",
            "premises": [
                {
                    "path": "jaimini.chara_dasha.1.active",
                    "operator": "equals",
                    "value": True,
                }
            ],
        },
    ]
    return build_jaimini_graph(facts=facts, rules=rules)


def test_career_pack_combines_amk_arudha_argala_and_drishti_with_provenance() -> None:
    analysis = analyze_jaimini_topic(_graph(), JaiminiTopic.CAREER)

    assert analysis.available
    assert {signal.path for signal in analysis.signals} == {
        "jaimini.karakas.7.AmK",
        "jaimini.arudha.AL",
        "jaimini.argala.AL.2_vs_12.status",
        "jaimini.rasi_drishti.planet.Mercury.signs",
    }
    assert all(signal.school == "nilakantha_baseline" for signal in analysis.signals)
    assert all(signal.time_scope == "natal" for signal in analysis.signals)
    assert analysis.conflicts == (("career.argala", "career.arudha"),)


def test_structural_career_analysis_never_blends_timing_periods() -> None:
    analysis = analyze_jaimini_topic(_graph(), JaiminiTopic.CAREER)

    assert "timing.separate" not in analysis.activated_rule_ids
    assert not any(signal.path.startswith("jaimini.chara_dasha") for signal in analysis.signals)


def test_ru_en_career_reports_are_bounded_and_match_golden_contracts() -> None:
    analysis = analyze_jaimini_topic(_graph(), JaiminiTopic.CAREER)
    for locale in ("ru", "en"):
        report = render_jaimini_topic_report(analysis, locale=locale)
        golden = json.loads(
            (ROOT / f"tests/fixtures/doctrine/jaimini-career-{locale}.json").read_text(
                encoding="utf-8"
            )
        )
        assert all(phrase in report for phrase in golden["required_phrases"])
        assert all(phrase not in report.casefold() for phrase in golden["forbidden_phrases"])
        assert "nilakantha_baseline" in report


def test_fact_substitution_removes_the_dependent_career_signal() -> None:
    graph = _graph()
    analysis = analyze_jaimini_topic(graph, JaiminiTopic.CAREER)
    assert "career.amk" in analysis.activated_rule_ids

    substituted = build_jaimini_graph(
        facts={
            "jaimini.karakas.7.AmK": "Venus",
            "jaimini.arudha.AL": "Leo",
        },
        rules=[
            {
                "rule_id": "career.amk",
                "topic": "career",
                "premises": [
                    {
                        "path": "jaimini.karakas.7.AmK",
                        "operator": "equals",
                        "value": "Mercury",
                    }
                ],
            }
        ],
        artifact_id="dom_career_substitution",
    )
    unavailable = analyze_jaimini_topic(substituted, JaiminiTopic.CAREER)
    assert unavailable.available is False
    assert unavailable.activated_rule_ids == ()

