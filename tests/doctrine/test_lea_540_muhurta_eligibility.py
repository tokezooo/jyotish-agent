from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from jyotish_agent.doctrine.muhurta_pack import (
    MuhurtaActivityProfile,
    MuhurtaEligibilityInput,
    MuhurtaRuleInterval,
    evaluate_muhurta_eligibility,
)


MOSCOW = ZoneInfo("Europe/Moscow")
LONDON = ZoneInfo("Europe/London")


def _candidate(**overrides) -> MuhurtaEligibilityInput:
    payload = {
        "profile": MuhurtaActivityProfile.FOCUSED_WORK,
        "start": dt.datetime(2026, 7, 15, 10, 0, tzinfo=MOSCOW),
        "end": dt.datetime(2026, 7, 15, 11, 0, tzinfo=MOSCOW),
        "zone_id": "Europe/Moscow",
        "panchanga_status": "allowed",
        "dosa_status": "clear",
        "weekday_status": "allowed",
        "daylight_status": "inside",
        "lagna_status": "available",
        "require_daylight": True,
        "require_lagna": True,
        "source_rule_intervals": (),
        "source_admitted": True,
    }
    payload.update(overrides)
    return MuhurtaEligibilityInput.model_validate(payload)


def test_hard_rules_and_soft_preferences_are_distinct_and_traced() -> None:
    result = evaluate_muhurta_eligibility(_candidate())
    assert result.status == "eligible"
    assert result.hard_failures == ()
    assert result.soft_signals == ("daylight_preferred",)
    assert {trace.classification for trace in result.rule_traces} == {"hard", "soft"}
    assert all(trace.source_locator for trace in result.rule_traces)


@pytest.mark.parametrize(
    ("field", "value", "rule_id"),
    [
        ("panchanga_status", "prohibited", "muhurta.eligibility.panchanga"),
        ("dosa_status", "active", "muhurta.eligibility.dosa"),
        ("weekday_status", "prohibited", "muhurta.eligibility.weekday"),
        ("daylight_status", "outside", "muhurta.eligibility.daylight"),
        ("lagna_status", "unavailable", "muhurta.eligibility.lagna"),
    ],
)
def test_each_hard_gate_can_exclude_a_candidate(field, value, rule_id) -> None:
    result = evaluate_muhurta_eligibility(_candidate(**{field: value}))
    assert result.status == "ineligible"
    assert rule_id in result.hard_failures


def test_source_interval_overlap_is_half_open_and_conflicts_favor_hard_exclusion() -> None:
    touching = MuhurtaRuleInterval(
        rule_id="muhurta.interval.touching",
        classification="hard",
        start=dt.datetime(2026, 7, 15, 9, 0, tzinfo=MOSCOW),
        end=dt.datetime(2026, 7, 15, 10, 0, tzinfo=MOSCOW),
        source_locator="Kalaprakasika p. 176",
    )
    overlapping_hard = MuhurtaRuleInterval(
        rule_id="muhurta.interval.prohibited",
        classification="hard",
        start=dt.datetime(2026, 7, 15, 10, 30, tzinfo=MOSCOW),
        end=dt.datetime(2026, 7, 15, 12, 0, tzinfo=MOSCOW),
        source_locator="Kalaprakasika p. 176",
    )
    overlapping_soft = MuhurtaRuleInterval(
        rule_id="muhurta.interval.preferred",
        classification="soft",
        start=dt.datetime(2026, 7, 15, 10, 15, tzinfo=MOSCOW),
        end=dt.datetime(2026, 7, 15, 10, 45, tzinfo=MOSCOW),
        source_locator="Kalaprakasika p. 176",
    )
    result = evaluate_muhurta_eligibility(
        _candidate(source_rule_intervals=(touching, overlapping_hard, overlapping_soft))
    )
    assert result.status == "ineligible"
    assert "muhurta.interval.touching" not in result.hard_failures
    assert "muhurta.interval.prohibited" in result.hard_failures
    assert "muhurta.interval.preferred" in result.soft_signals


def test_dst_fold_is_compared_by_utc_instant() -> None:
    candidate = _candidate(
        start=dt.datetime(2026, 10, 25, 1, 15, tzinfo=LONDON, fold=1),
        end=dt.datetime(2026, 10, 25, 1, 45, tzinfo=LONDON, fold=1),
        zone_id="Europe/London",
        source_rule_intervals=(
            MuhurtaRuleInterval(
                rule_id="muhurta.interval.dst",
                classification="hard",
                start=dt.datetime(2026, 10, 25, 1, 0, tzinfo=LONDON, fold=0),
                end=dt.datetime(2026, 10, 25, 1, 50, tzinfo=LONDON, fold=0),
                source_locator="fixture",
            ),
        ),
    )
    result = evaluate_muhurta_eligibility(candidate)
    assert "muhurta.interval.dst" not in result.hard_failures


def test_missing_source_admission_returns_unavailable_without_partial_enforcement() -> None:
    result = evaluate_muhurta_eligibility(
        _candidate(source_admitted=False, dosa_status="active")
    )
    assert result.status == "unavailable"
    assert result.hard_failures == ()
    assert result.rule_traces == ()
    assert result.reason_code == "SOURCE_RULES_NOT_ADMITTED"


def test_no_window_is_explicit_when_all_worked_candidates_fail() -> None:
    worked = [
        evaluate_muhurta_eligibility(_candidate(dosa_status="active")),
        evaluate_muhurta_eligibility(_candidate(weekday_status="prohibited")),
    ]
    assert not any(item.status == "eligible" for item in worked)
    assert {failure for item in worked for failure in item.hard_failures} == {
        "muhurta.eligibility.dosa",
        "muhurta.eligibility.weekday",
    }
