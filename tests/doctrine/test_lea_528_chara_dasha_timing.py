from __future__ import annotations

import datetime as dt

import pytest

from jaimini_helpers import build_jaimini_graph
from jyotish_agent.doctrine.jaimini_pack import (
    JaiminiTimingFailure,
    JaiminiTopic,
    analyze_jaimini_topic,
    link_chara_dasha_timing,
    render_jaimini_timing_report,
)


def _graph(*, end: str = "2027-01-01T00:00:00+00:00"):
    facts = {
        "jaimini.karakas.7.AmK": "Mercury",
        "jaimini.chara_dasha.1.sign": "Gemini",
        "jaimini.chara_dasha.1.start": "2026-01-01T00:00:00+00:00",
        "jaimini.chara_dasha.1.end": end,
        "jaimini.chara_dasha.1.active": True,
    }
    rules = [
        {
            "rule_id": "career.natal_gate",
            "topic": "career",
            "premises": [
                {"path": "jaimini.karakas.7.AmK", "operator": "exists", "value": None}
            ],
        },
        {
            "rule_id": "timing.chara.active",
            "topic": "timing",
            "time_scope": "period",
            "modality": "timing_window",
            "confidence_ceiling": 0.55,
            "premises": [
                {
                    "path": "jaimini.chara_dasha.1.active",
                    "operator": "equals",
                    "value": True,
                },
                {
                    "path": "jaimini.chara_dasha.1.sign",
                    "operator": "exists",
                    "value": None,
                },
                {
                    "path": "jaimini.chara_dasha.1.start",
                    "operator": "exists",
                    "value": None,
                },
                {
                    "path": "jaimini.chara_dasha.1.end",
                    "operator": "exists",
                    "value": None,
                },
            ],
        },
    ]
    return build_jaimini_graph(facts=facts, rules=rules)


def test_chara_dasha_requires_an_available_natal_topic_and_preserves_lineage() -> None:
    graph = _graph()
    natal = analyze_jaimini_topic(graph, JaiminiTopic.CAREER)
    timing = link_chara_dasha_timing(graph, natal)

    assert timing.available
    assert len(timing.windows) == 1
    window = timing.windows[0]
    assert window.sign == "Gemini"
    assert window.start == dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    assert window.end == dt.datetime(2027, 1, 1, tzinfo=dt.UTC)
    assert window.boundary_stability == "stable"
    assert window.rule_ids == ("timing.chara.active",)
    assert len(window.source_commitments) == 1
    assert all(len(commitment) == 64 for commitment in window.source_commitments)
    assert set(window.fact_paths) == {
        "jaimini.chara_dasha.1.active",
        "jaimini.chara_dasha.1.sign",
        "jaimini.chara_dasha.1.start",
        "jaimini.chara_dasha.1.end",
    }


def test_approximate_birth_time_marks_period_boundaries_unstable() -> None:
    graph = _graph()
    natal = analyze_jaimini_topic(graph, JaiminiTopic.CAREER)
    timing = link_chara_dasha_timing(graph, natal, birth_time_confidence="approximate")

    assert timing.windows[0].boundary_stability == "unstable"
    assert "BIRTH_TIME_APPROXIMATE" in timing.limitations


def test_missing_natal_gate_and_substituted_graph_fail_closed() -> None:
    graph = _graph()
    unavailable_natal = analyze_jaimini_topic(graph, JaiminiTopic.RELATIONSHIPS)
    timing = link_chara_dasha_timing(graph, unavailable_natal)
    assert timing.available is False
    assert timing.windows == ()
    assert timing.limitations == ("NATAL_TOPIC_UNAVAILABLE",)

    other = _graph(end="2028-01-01T00:00:00+00:00")
    valid_natal = analyze_jaimini_topic(graph, JaiminiTopic.CAREER)
    with pytest.raises(JaiminiTimingFailure) as substituted:
        link_chara_dasha_timing(other, valid_natal)
    assert substituted.value.code == "NATAL_GRAPH_SUBSTITUTED"


def test_invalid_or_point_date_periods_are_rejected() -> None:
    graph = _graph(end="2025-01-01T00:00:00+00:00")
    natal = analyze_jaimini_topic(graph, JaiminiTopic.CAREER)
    with pytest.raises(JaiminiTimingFailure) as invalid:
        link_chara_dasha_timing(graph, natal)
    assert invalid.value.code == "TIMING_WINDOW_INVALID"


def test_timing_report_is_bounded_and_never_promises_an_event_date() -> None:
    graph = _graph()
    natal = analyze_jaimini_topic(graph, JaiminiTopic.CAREER)
    timing = link_chara_dasha_timing(graph, natal)

    for locale in ("ru", "en"):
        report = render_jaimini_timing_report(timing, locale=locale)
        assert "2026-01-01" in report
        assert "2027-01-01" in report
        assert "Gemini" in report
        assert "guaranteed" not in report.casefold()
        assert "гарантирован" not in report.casefold()
        assert "source:" not in report
        assert len(report) < 4_000
