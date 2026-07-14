from __future__ import annotations

from jyotish_agent.doctrine.jaimini_pack import (
    JaiminiTopic,
    JaiminiTopicSignalClass,
    analyze_jaimini_topic,
)

from jaimini_helpers import build_jaimini_graph


FACTS = {
    "jaimini.karakas.7.AK": "Mercury",
    "jaimini.karakamsa.sign": "Gemini",
    "jaimini.svamsa.sign": "Virgo",
    "jaimini.arudha.AL": "Leo",
    "jaimini.special_lagnas.hora_lagna.sign": "Taurus",
}


def _rules() -> list[dict[str, object]]:
    return [
        {
            "rule_id": "self.ak",
            "topic": "self",
            "premises": [
                {"path": "jaimini.karakas.7.AK", "operator": "exists", "value": None}
            ],
        },
        {
            "rule_id": "self.karakamsa",
            "topic": "dharma",
            "premises": [
                {"path": "jaimini.karakamsa.sign", "operator": "exists", "value": None}
            ],
        },
        {
            "rule_id": "self.svamsa",
            "topic": "education",
            "premises": [
                {"path": "jaimini.svamsa.sign", "operator": "exists", "value": None}
            ],
        },
        {
            "rule_id": "self.arudha",
            "topic": "capability",
            "premises": [
                {"path": "jaimini.arudha.AL", "operator": "exists", "value": None}
            ],
            "conflicts_with": ["self.special_lagna"],
        },
        {
            "rule_id": "self.special_lagna",
            "topic": "capability",
            "premises": [
                {
                    "path": "jaimini.special_lagnas.hora_lagna.sign",
                    "operator": "exists",
                    "value": None,
                }
            ],
            "conflicts_with": ["self.arudha"],
        },
    ]


def test_self_pack_uses_only_graph_bound_ak_karakamsa_svamsa_and_lagnas() -> None:
    graph = build_jaimini_graph(facts=FACTS, rules=_rules())
    analysis = analyze_jaimini_topic(graph, JaiminiTopic.SELF)

    assert analysis.available is True
    assert {signal.path for signal in analysis.signals} == set(FACTS)
    assert {signal.signal_class for signal in analysis.signals} >= {
        JaiminiTopicSignalClass.SUPPORTING,
        JaiminiTopicSignalClass.CONFLICTING,
    }
    assert set(analysis.activated_rule_ids) == {
        "self.ak",
        "self.karakamsa",
        "self.svamsa",
        "self.arudha",
        "self.special_lagna",
    }
    assert analysis.school_ids == ("nilakantha_baseline",)


def test_approximate_time_suppresses_time_sensitive_self_signals() -> None:
    graph = build_jaimini_graph(facts=FACTS, rules=_rules())
    analysis = analyze_jaimini_topic(
        graph, JaiminiTopic.SELF, birth_time_confidence="approximate"
    )

    assert {signal.path for signal in analysis.signals} == {"jaimini.karakas.7.AK"}
    assert set(analysis.suppressed_fact_paths) == set(FACTS) - {"jaimini.karakas.7.AK"}
    assert "BIRTH_TIME_APPROXIMATE" in analysis.unavailable_reasons


def test_absent_compiled_topic_rules_fail_closed_as_unavailable() -> None:
    graph = build_jaimini_graph(
        facts={"jaimini.karakas.7.AK": "Mercury"},
        rules=[
            {
                "rule_id": "career.only",
                "topic": "career",
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
    analysis = analyze_jaimini_topic(graph, JaiminiTopic.SELF)

    assert analysis.available is False
    assert analysis.signals == ()
    assert analysis.unavailable_reasons == ("NO_ADMITTED_TOPIC_RULES",)


def test_prohibited_topics_never_enter_the_self_pack() -> None:
    graph = build_jaimini_graph(facts=FACTS, rules=_rules())
    analysis = analyze_jaimini_topic(graph, JaiminiTopic.SELF)

    assert set(analysis.prohibited_topics) >= {
        "medical",
        "longevity",
        "death",
        "fertility",
        "guaranteed_marriage",
    }
    assert not set(analysis.prohibited_topics) & {
        signal.topic for signal in analysis.signals
    }


def test_fact_substitution_changes_graph_and_signal_identity() -> None:
    first_graph = build_jaimini_graph(facts=FACTS, rules=_rules())
    second_graph = build_jaimini_graph(
        facts={**FACTS, "jaimini.karakas.7.AK": "Venus"},
        rules=_rules(),
        artifact_id="dom_jaimini_topic_substitution",
    )
    first = analyze_jaimini_topic(first_graph, JaiminiTopic.SELF)
    second = analyze_jaimini_topic(second_graph, JaiminiTopic.SELF)

    assert first.graph_sha256 != second.graph_sha256
    first_ak = next(signal for signal in first.signals if signal.path.endswith(".AK"))
    second_ak = next(signal for signal in second.signals if signal.path.endswith(".AK"))
    assert first_ak.value == "Mercury"
    assert second_ak.value == "Venus"
