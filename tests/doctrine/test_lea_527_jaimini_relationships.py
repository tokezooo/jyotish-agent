from __future__ import annotations

from jaimini_helpers import build_jaimini_graph
from jyotish_agent.doctrine.jaimini_pack import (
    JaiminiTopic,
    JaiminiTopicSignalClass,
    analyze_jaimini_topic,
    render_jaimini_topic_report,
)


FACTS = {
    "jaimini.karakas.7.DK": "Venus",
    "jaimini.arudha.UL": "Libra",
    "jaimini.relationships.7.edge.D1.DK_to_UL.forward_distance": 4,
    "jaimini.argala.UL.2_vs_12.status": "partial",
    "jaimini.rasi_drishti.planet.Venus.signs": "Taurus,Libra",
}


def _rules(*, conflicts: bool = True) -> list[dict[str, object]]:
    ul_rule: dict[str, object] = {
        "rule_id": "relationships.ul",
        "topic": "relationships",
        "premises": [
            {"path": "jaimini.arudha.UL", "operator": "exists", "value": None}
        ],
    }
    argala_rule: dict[str, object] = {
        "rule_id": "relationships.argala",
        "topic": "family",
        "premises": [
            {
                "path": "jaimini.argala.UL.2_vs_12.status",
                "operator": "exists",
                "value": None,
            }
        ],
    }
    if conflicts:
        ul_rule["conflicts_with"] = ["relationships.argala"]
        argala_rule["conflicts_with"] = ["relationships.ul"]
    return [
        {
            "rule_id": "relationships.dk",
            "topic": "relationships",
            "premises": [
                {"path": "jaimini.karakas.7.DK", "operator": "exists", "value": None}
            ],
        },
        ul_rule,
        {
            "rule_id": "relationships.pada",
            "topic": "legacy",
            "premises": [
                {
                    "path": "jaimini.relationships.7.edge.D1.DK_to_UL.forward_distance",
                    "operator": "exists",
                    "value": None,
                }
            ],
        },
        argala_rule,
        {
            "rule_id": "relationships.drishti",
            "topic": "family",
            "premises": [
                {
                    "path": "jaimini.rasi_drishti.planet.Venus.signs",
                    "operator": "exists",
                    "value": None,
                }
            ],
        },
    ]


def test_relationship_pack_covers_dk_ul_pada_argala_and_drishti() -> None:
    graph = build_jaimini_graph(facts=FACTS, rules=_rules(conflicts=False))
    analysis = analyze_jaimini_topic(graph, JaiminiTopic.RELATIONSHIPS)

    assert analysis.available
    assert {signal.path for signal in analysis.signals} == set(FACTS)
    assert all(
        signal.signal_class == JaiminiTopicSignalClass.SUPPORTING
        for signal in analysis.signals
    )
    assert analysis.conflicts == ()


def test_conflicting_relationship_evidence_remains_explicit() -> None:
    graph = build_jaimini_graph(facts=FACTS, rules=_rules(conflicts=True))
    analysis = analyze_jaimini_topic(graph, JaiminiTopic.RELATIONSHIPS)

    assert analysis.conflicts == (("relationships.argala", "relationships.ul"),)
    assert {
        signal.rule_id
        for signal in analysis.signals
        if signal.signal_class == JaiminiTopicSignalClass.CONFLICTING
    } == {"relationships.argala", "relationships.ul"}


def test_missing_relationship_rules_fail_closed() -> None:
    graph = build_jaimini_graph(
        facts={"jaimini.karakas.7.AK": "Sun"},
        rules=[
            {
                "rule_id": "self.only",
                "topic": "self",
                "premises": [
                    {
                        "path": "jaimini.karakas.7.AK",
                        "operator": "exists",
                        "value": None,
                    }
                ],
            }
        ],
    )
    analysis = analyze_jaimini_topic(graph, JaiminiTopic.RELATIONSHIPS)
    assert analysis.available is False
    assert analysis.unavailable_reasons == ("NO_ADMITTED_TOPIC_RULES",)


def test_approximate_time_keeps_only_stable_dk_and_suppresses_geometry() -> None:
    graph = build_jaimini_graph(facts=FACTS, rules=_rules(conflicts=False))
    analysis = analyze_jaimini_topic(
        graph,
        JaiminiTopic.RELATIONSHIPS,
        birth_time_confidence="approximate",
    )

    assert {signal.path for signal in analysis.signals} == {"jaimini.karakas.7.DK"}
    assert set(analysis.suppressed_fact_paths) == set(FACTS) - {
        "jaimini.karakas.7.DK"
    }


def test_relationship_report_is_symbolic_and_blocks_high_stakes_categories() -> None:
    graph = build_jaimini_graph(facts=FACTS, rules=_rules(conflicts=True))
    analysis = analyze_jaimini_topic(graph, JaiminiTopic.RELATIONSHIPS)
    for locale in ("ru", "en"):
        report = render_jaimini_topic_report(analysis, locale=locale).casefold()
        assert "experimental_full" in report
        assert "nilakantha_baseline" in report
        assert not any(
            forbidden in report
            for forbidden in (
                "fertility prediction",
                "guaranteed marriage",
                "death timing",
                "прогноз фертильности",
                "гарантированный брак",
                "срок смерти",
            )
        )
    assert set(analysis.prohibited_topics) >= {
        "fertility",
        "guaranteed_marriage",
        "longevity",
        "death",
    }

