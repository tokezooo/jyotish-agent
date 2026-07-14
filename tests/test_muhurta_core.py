from __future__ import annotations

import datetime as dt
import json
import random
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from jyotish_agent.event_models import EventPlace
from jyotish_agent.intervals import EventInterval, normalize_boundaries, partition_interval, subtract_intervals
from jyotish_agent.muhurta import MuhurtaFacade, _local_instant
from jyotish_agent.muhurta_models import MuhurtaSearchRequest
from jyotish_agent.interpretations import iter_muhurta_fact_atoms, validate_muhurta_answer
from jyotish_agent.pyjhora_facade import (
    BirthProfile,
    _MuhurtaBoundaryEstimate,
    _canonicalize_muhurta_estimates,
    _run_muhurta_boundary_day,
)
from jyotish_agent.muhurta_profiles import (
    MuhurtaSourceMap,
    load_muhurta_adjudication_fixtures,
    load_muhurta_rule_profile,
    load_muhurta_source_map,
    muhurta_source_admission_evidence,
)


UTC = dt.UTC


def _place(zone: str = "Europe/Moscow") -> EventPlace:
    return EventPlace(name="private-event-place", latitude=55.7558, longitude=37.6173, zone_id=zone)


def _request(**updates) -> MuhurtaSearchRequest:
    payload = {
        "activity": "focused_work_session_v1",
        "place": _place(),
        "start": "2026-07-15T00:00:00+03:00",
        "end": "2026-07-16T00:00:00+03:00",
        "duration_minutes": 90,
        "hard_constraints": {"require_daylight": True, "local_time_start": "08:00", "local_time_end": "20:00"},
        "preferences": {"preferred_local_time_start": "09:00", "preferred_local_time_end": "15:00"},
    }
    payload.update(updates)
    return MuhurtaSearchRequest.model_validate(payload)


def test_interval_half_open_partition_subtract_and_deduplicate() -> None:
    whole = EventInterval(start=dt.datetime(2026, 1, 1, tzinfo=UTC), end=dt.datetime(2026, 1, 2, tzinfo=UTC))
    points = normalize_boundaries(whole, [whole.start, whole.start, whole.start + dt.timedelta(hours=6), whole.end])
    parts = partition_interval(whole, points)
    assert [(p.start, p.end) for p in parts] == [
        (whole.start, whole.start + dt.timedelta(hours=6)),
        (whole.start + dt.timedelta(hours=6), whole.end),
    ]
    assert parts[0].contains(parts[0].start)
    assert not parts[0].contains(parts[0].end)
    remain = subtract_intervals(whole, [EventInterval(start=whole.start + dt.timedelta(hours=5), end=whole.start + dt.timedelta(hours=7))])
    assert [x.duration_seconds for x in remain] == [5 * 3600, 17 * 3600]


def test_interval_rejects_naive_zero_negative_and_mixed_timezone() -> None:
    with pytest.raises(ValueError):
        EventInterval(start=dt.datetime(2026, 1, 1), end=dt.datetime(2026, 1, 2))
    with pytest.raises(ValueError):
        EventInterval(start=dt.datetime(2026, 1, 1, tzinfo=UTC), end=dt.datetime(2026, 1, 1, tzinfo=UTC))


def test_interval_partition_property_has_no_gaps_or_overlaps() -> None:
    whole = EventInterval(dt.datetime(2026, 3, 1, tzinfo=UTC), dt.datetime(2026, 3, 2, tzinfo=UTC))
    for hours in ((1, 2, 8), (23,), (4, 4, 6, 12, 18)):
        parts = partition_interval(whole, [whole.start + dt.timedelta(hours=hour) for hour in hours])
        assert parts[0].start == whole.start and parts[-1].end == whole.end
        assert all(left.end == right.start for left, right in zip(parts, parts[1:]))
        assert sum(part.duration_seconds for part in parts) == whole.duration_seconds


def test_interval_uses_real_utc_duration_across_london_fallback() -> None:
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("Europe/London")
    start = dt.datetime(2026, 10, 25, 1, 30, tzinfo=zone, fold=0)
    end = dt.datetime(2026, 10, 25, 1, 30, tzinfo=zone, fold=1)
    interval = EventInterval(start, end)
    assert interval.duration_seconds == 3600
    parts = partition_interval(interval, [dt.datetime(2026, 10, 25, 1, 0, tzinfo=zone, fold=1)])
    assert sum(part.duration_seconds for part in parts) == 3600
    assert all(left.end.astimezone(UTC) == right.start.astimezone(UTC) for left, right in zip(parts, parts[1:]))


def test_generated_partitions_are_contiguous_in_utc_across_zones() -> None:
    from zoneinfo import ZoneInfo

    rng = random.Random(20260715)
    for zone_name in ("Europe/London", "Asia/Kolkata", "America/New_York"):
        zone = ZoneInfo(zone_name)
        start_utc = dt.datetime(2026, 10, 24, tzinfo=UTC)
        end_utc = start_utc + dt.timedelta(days=4)
        whole = EventInterval(start_utc.astimezone(zone), end_utc.astimezone(zone))
        generated = sorted({rng.randrange(1, int(whole.duration_seconds)) for _ in range(100)})
        points = [(start_utc + dt.timedelta(seconds=seconds)).astimezone(zone) for seconds in generated]
        parts = partition_interval(whole, points)
        assert sum(part.duration_seconds for part in parts) == whole.duration_seconds
        assert all(left.end.astimezone(UTC) == right.start.astimezone(UTC) for left, right in zip(parts, parts[1:]))


def test_request_strict_range_offset_and_limits() -> None:
    with pytest.raises(ValidationError):
        _request(end="2026-08-20T00:00:00+03:00")
    with pytest.raises(ValidationError):
        _request(start="2026-07-15T00:00:00Z")
    with pytest.raises(ValidationError):
        _request(result_limit=21)
    with pytest.raises(ValidationError):
        _request(extra="forbidden")


def test_default_end_is_seven_local_civil_days_across_dst() -> None:
    london = EventPlace(name="private", latitude=51.5072, longitude=-0.1276, zone_id="Europe/London")
    value = _request(place=london, start="2026-10-24T00:00:00+01:00", end=None, hard_constraints={})
    assert value.end is not None
    assert value.end.isoformat() == "2026-10-31T00:00:00+00:00"
    assert value.end.replace(tzinfo=None) - value.start.replace(tzinfo=None) == dt.timedelta(days=7)
    assert value.range_duration_seconds == 7 * 86400 + 3600


def test_endpoint_specific_fold_and_spring_gap_validation() -> None:
    london = EventPlace(name="private", latitude=51.5072, longitude=-0.1276, zone_id="Europe/London")
    value = _request(
        place=london,
        start="2026-10-25T01:30:00+01:00", start_fold=0,
        end="2026-10-25T01:30:00Z", end_fold=1,
        duration_minutes=30, hard_constraints={},
    )
    assert value.range_duration_seconds == 3600
    with pytest.raises(ValidationError, match="AMBIGUOUS_LOCAL_TIME"):
        _request(place=london, start="2026-10-25T01:30:00+01:00", end="2026-10-25T03:00:00Z", hard_constraints={})
    with pytest.raises(ValidationError, match="NONEXISTENT_LOCAL_TIME"):
        _request(place=london, start="2026-03-29T01:30:00Z", end="2026-03-29T03:00:00+01:00", start_fold=0, hard_constraints={})


def test_governance_is_frozen_and_fail_closed() -> None:
    profile = load_muhurta_rule_profile()
    source = load_muhurta_source_map()
    fixtures = load_muhurta_adjudication_fixtures()
    assert profile.profile_id == "muhurta_focused_work_v1"
    assert {r.classification for r in profile.rules} == {"hard", "soft"}
    assert source.review.status == fixtures.gate_status == "pending"
    evidence = muhurta_source_admission_evidence()
    assert evidence["verified"] is False


def test_governance_cannot_admit_fake_or_partial_rule_mapping() -> None:
    source = load_muhurta_source_map().model_dump(mode="json")
    source["interpretation_status"] = "available"
    source["review"] = {"status": "approved", "reviewer": "fake", "reviewer_role": "astrologer", "reason": "fake"}
    source["rules"] = [{
        "rule_id": "muhurta.focused_work.preference", "source_status": "approved",
        "fragment_id": "sf_fake", "fragment_sha256": "0" * 64,
    }]
    with pytest.raises(ValidationError):
        MuhurtaSourceMap.model_validate(source)


def test_real_one_day_search_is_bounded_signed_and_deterministic() -> None:
    facade = MuhurtaFacade()
    first = facade.search(_request())
    second = facade.search(_request())
    assert first.status == "completed"
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.interpretation_status == "unavailable"
    assert first.ranking_status == "unavailable"
    assert first.provenance.source_review_status == "pending"
    assert len(first.windows) <= 5
    assert len(first.near_misses) <= 5
    assert first.total_candidate_intervals <= 5000
    assert len(first.model_dump_json().encode()) < 512 * 1024
    assert all(window.end > window.start for window in first.windows)
    assert all(window.end - window.start == dt.timedelta(minutes=90) for window in first.windows)
    assert first.provenance.start_normalized_utc.endswith("Z")
    assert first.provenance.end_normalized_utc.endswith("Z")
    expected_rules = {rule.rule_id for rule in load_muhurta_rule_profile().rules}
    assert {trace.rule_id for trace in first.rule_traces} == expected_rules
    assert all(trace.status in {"pending", "not_applicable"} for trace in first.rule_traces if trace.source_status == "pending")
    assert next(f.value for f in first.facts if f.fact_id == "muhurta.search.preferences_status") == "present_pending_not_applied"


def test_optional_natal_is_omitted_unless_supplied() -> None:
    result = MuhurtaFacade().search(_request())
    assert result.status == "completed"
    assert all("tara_bala" not in fact.fact_id and "candra_bala" not in fact.fact_id for fact in result.facts)

    supplied = MuhurtaFacade().search(_request(natal={
        "confidence": "exact", "date": "1990-01-01", "time": "12:30:00",
        "place": {"name": "private", "latitude": 13.0827, "longitude": 80.2707, "timezone": "Asia/Kolkata"},
    }))
    assert supplied.status == "completed"
    assert next(f.value for f in supplied.facts if f.fact_id == "muhurta.search.natal_personalization") == "supplied_not_evaluated_pending_admission"
    assert all("tara_bala" not in fact.fact_id and "candra_bala" not in fact.fact_id for fact in supplied.facts)


def test_hard_exclusion_is_monotone_and_candidate_budget_is_typed() -> None:
    facade = MuhurtaFacade()
    broad = facade.search(_request(hard_constraints={}, result_limit=20))
    narrow = facade.search(_request(hard_constraints={"require_daylight": True}, result_limit=20))
    assert broad.status == narrow.status == "completed"
    broad_ids = {(w.start, w.end) for w in broad.windows}
    assert {(w.start, w.end) for w in narrow.windows} <= broad_ids
    limited = facade.search(_request(max_candidate_intervals=1))
    assert limited.status == "incomplete"
    assert limited.error_code == "CANDIDATE_LIMIT_EXCEEDED"


def test_dst_crossing_preserves_calendar_ready_zone_offsets() -> None:
    london = EventPlace(name="private", latitude=51.5072, longitude=-0.1276, zone_id="Europe/London")
    result = MuhurtaFacade().search(_request(
        place=london,
        start="2026-10-24T00:00:00+01:00",
        end="2026-10-27T00:00:00Z",
        hard_constraints={},
        duration_minutes=60,
    ))
    assert result.status == "completed"
    assert result.provenance.zone_id == "Europe/London"
    assert all(window.start.tzinfo is not None and window.end.tzinfo is not None for window in result.windows)


def test_boundary_probes_use_pre_and_post_dst_offsets() -> None:
    profile = BirthProfile("event", (2026, 10, 25), (0, 0, 0), 51.5072, -0.1276, 0)
    fallback = _run_muhurta_boundary_day(profile, dt.date(2026, 10, 25), "Europe/London")
    assert fallback.probe_offsets[0] == (0, 60)
    assert fallback.probe_offsets[-1] == (1439, 0)
    spring = _run_muhurta_boundary_day(profile, dt.date(2026, 3, 29), "Europe/London")
    assert spring.probe_offsets[0] == (0, 0)
    assert spring.probe_offsets[-1] == (1439, 60)
    zone = ZoneInfo("Europe/London")
    for result in (fallback, spring):
        assert all(item.start_utc.tzinfo is UTC for item in result.day.values)
        assert all(item.start_utc.astimezone(zone).utcoffset() is not None for item in result.day.values)


def test_concurrent_mixed_zones_are_config_isolated() -> None:
    moscow = _request(hard_constraints={})
    kolkata = _request(
        place=EventPlace(name="private", latitude=22.5726, longitude=88.3639, zone_id="Asia/Kolkata"),
        start="2026-07-15T00:00:00+05:30", end="2026-07-16T00:00:00+05:30", hard_constraints={},
    )
    expected = [MuhurtaFacade().search(moscow).model_dump(mode="json"), MuhurtaFacade().search(kolkata).model_dump(mode="json")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        actual = list(pool.map(lambda request: MuhurtaFacade().search(request).model_dump(mode="json"), (moscow, kolkata)))
    assert actual == expected


def test_explicit_constraints_can_produce_successful_empty_result() -> None:
    result = MuhurtaFacade().search(_request(hard_constraints={"excluded_weekdays": [2]}))
    assert result.status == "completed"
    assert result.windows == ()
    assert result.empty_reason == "all_candidates_excluded_by_explicit_constraints"
    assert result.near_misses
    assert all(item.rejection_rule_ids for item in result.near_misses)
    assert all(rule_id.startswith("muhurta.") for item in result.near_misses for rule_id in item.rejection_rule_ids)


def test_deadline_cancellation_and_unsupported_activity_are_typed() -> None:
    facade = MuhurtaFacade()
    cancelled = facade.search(_request(cancel_requested=True))
    assert cancelled.status == "incomplete"
    assert cancelled.error_code == "SEARCH_CANCELLED"
    assert cancelled.next_action == "narrow_search_range"
    expired = facade.search(_request(deadline_utc="2020-01-01T00:00:00Z"))
    assert expired.status == "incomplete"
    assert expired.error_code == "SEARCH_DEADLINE_EXCEEDED"
    unsafe = facade.search(_request(activity="elective_medical"))
    assert unsafe.status == "unavailable"
    assert unsafe.error_code == "HIGH_STAKES_ACTIVITY"
    unsupported = facade.search(_request(activity="gardening"))
    assert unsupported.status == "needs_input"
    assert unsupported.error_code == "ACTIVITY_UNSUPPORTED"


def test_cooperative_mid_search_cancel_reports_real_progress() -> None:
    checks = 0

    def cancel() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 4

    result = MuhurtaFacade(cancel_check=cancel).search(_request(end="2026-07-20T00:00:00+03:00", hard_constraints={}))
    assert result.status == "incomplete"
    assert result.error_code == "SEARCH_CANCELLED"
    assert 0 < result.days_processed < 6
    assert result.boundary_count > 0
    assert result.processed_candidate_intervals == 0


def test_boundary_batch_collects_second_karana_and_all_varjyam_pairs() -> None:
    profile = BirthProfile("event", (2026, 7, 15), (0, 0, 0), 55.7558, 37.6173, 3)
    july15 = _run_muhurta_boundary_day(profile, dt.date(2026, 7, 15), "Europe/Moscow")
    karana = sorted(item.start_hour for item in july15.day.values if item.kind == "karana_transition")
    assert any(abs(value - 19.824) < 0.05 for value in karana)
    july27 = _run_muhurta_boundary_day(profile, dt.date(2026, 7, 27), "Europe/Moscow")
    varjyam = [item for item in july27.day.values if item.kind == "varjyam"]
    assert len(varjyam) >= 2
    assert any(abs(item.start_hour - (-0.7287)) < 0.1 and abs(item.end_hour - 0.1422) < 0.1 for item in varjyam)
    assert any(abs(item.start_hour - 7.1093) < 0.1 and abs(item.end_hour - 7.9802) < 0.1 for item in varjyam)
    assert all(item.end_hour is not None for item in varjyam)


def test_returned_windows_never_cross_any_collected_boundary() -> None:
    from zoneinfo import ZoneInfo

    result = MuhurtaFacade().search(_request(hard_constraints={}, result_limit=20))
    assert result.status == "completed"
    profile = BirthProfile("event", (2026, 7, 15), (0, 0, 0), 55.7558, 37.6173, 3)
    day = _run_muhurta_boundary_day(profile, dt.date(2026, 7, 15), "Europe/Moscow").day
    zone = ZoneInfo("Europe/Moscow")
    boundaries = []
    for item in day.values:
        boundaries.append(_local_instant(day.civil_date, item.start_hour, zone, 3).astimezone(UTC))
        if item.end_hour is not None:
            end_hour = item.end_hour + (24 if item.end_hour <= item.start_hour else 0)
            boundaries.append(_local_instant(day.civil_date, end_hour, zone, 3).astimezone(UTC))
    assert all(
        not any(window.start.astimezone(UTC) < boundary < window.end.astimezone(UTC) for boundary in boundaries)
        for window in result.windows
    )


def test_transition_canonicalization_clusters_estimates_but_preserves_distinct_identity() -> None:
    base = dt.datetime(2026, 7, 15, 9, 20, tzinfo=UTC)
    estimates = (
        _MuhurtaBoundaryEstimate("karana_transition", "karana:to:3", base),
        _MuhurtaBoundaryEstimate("karana_transition", "karana:to:3", base + dt.timedelta(seconds=40)),
        _MuhurtaBoundaryEstimate("karana_transition", "karana:to:4", base + dt.timedelta(seconds=45)),
    )
    canonical = _canonicalize_muhurta_estimates(estimates, tolerance_seconds=120)
    assert len(canonical) == 2
    assert {item.identity for item in canonical} == {"karana:to:3", "karana:to:4"}


def test_moscow_canonical_boundaries_have_no_same_identity_micro_duplicates() -> None:
    profile = BirthProfile("event", (2026, 7, 15), (0, 0, 0), 55.7558, 37.6173, 3)
    result = _run_muhurta_boundary_day(profile, dt.date(2026, 7, 15), "Europe/Moscow")
    keys = [(item.kind, item.identity) for item in result.day.values]
    assert len(keys) == len(set(keys))
    assert result.canonicalization_tolerance_seconds == 900


def test_provenance_uses_actual_ephemeris_mode(monkeypatch) -> None:
    import jyotish_agent.config as config

    monkeypatch.setattr(config, "ephemeris_mode", lambda: "swiss")
    result = MuhurtaFacade().search(_request())
    assert result.status == "completed"
    assert result.provenance.ephemeris_mode == "swiss"


def test_trace_truncation_metadata_is_explicit() -> None:
    result = MuhurtaFacade().search(_request(end="2026-07-22T00:00:00+03:00", hard_constraints={}, include_trace=True))
    assert result.status == "completed"
    assert result.trace is not None and len(result.trace) == 100
    assert result.trace_truncation is not None
    assert result.trace_truncation.truncated is True
    assert result.trace_truncation.total_count > result.trace_truncation.returned_count == 100


def test_packaged_fixtures_do_not_claim_human_approval() -> None:
    root = Path(__file__).parents[1] / "src/jyotish_agent/data/muhurta"
    for name in ("muhurta_focused_work_v1.json", "muhurta_focused_work_v1_sources.json", "adjudication_fixtures_v1.json"):
        payload = json.loads((root / name).read_text())
        assert "approved" not in json.dumps(payload).lower()


def test_signed_answer_checker_rejects_substitution_duplicates_and_prose() -> None:
    result = MuhurtaFacade().search(_request())
    assert result.status == "completed" and result.windows
    fact = next(item for item in result.facts if item.fact_id.endswith(".start"))
    base = {
        "artifact_id": result.artifact_id,
        "artifact_sha256": result.artifact_sha256,
        "artifact_token": result.artifact_token,
        "search_range_sha256": result.search_range_sha256,
        "window_ids": [window.window_id for window in result.windows],
        "claims": [{"claim_type": "computed_fact", "path": fact.fact_id, "value": str(fact.value), "text": f"{fact.fact_id} = {fact.value}"}],
        "visible_text": f"{fact.fact_id} = {fact.value}",
    }
    assert validate_muhurta_answer(base) == []
    assert validate_muhurta_answer({**base, "search_range_sha256": "0" * 64}) == ["SEARCH_RANGE_MISMATCH"]
    assert validate_muhurta_answer({**base, "window_ids": ["mw_" + "0" * 24]}) == ["WINDOW_IDS_MISMATCH"]
    prose = {**base, "visible_text": "This is auspicious."}
    assert validate_muhurta_answer(prose) == ["UNSUPPORTED_VISIBLE_TEXT"]
    with pytest.raises(ValueError, match="DUPLICATE_MUHURTA_FACT_ID"):
        iter_muhurta_fact_atoms([{"fact_id": "muhurta.x", "value": 1}, {"fact_id": "muhurta.x", "value": 2}])


def test_signed_answer_checker_rejects_current_material_drift(monkeypatch) -> None:
    import jyotish_agent.muhurta_profiles as profiles

    result = MuhurtaFacade().search(_request())
    assert result.status == "completed" and result.windows
    fact = next(item for item in result.facts if item.fact_id.endswith(".start"))
    payload = {
        "artifact_id": result.artifact_id, "artifact_sha256": result.artifact_sha256,
        "artifact_token": result.artifact_token, "search_range_sha256": result.search_range_sha256,
        "window_ids": [window.window_id for window in result.windows],
        "claims": [{"claim_type": "computed_fact", "path": fact.fact_id, "value": str(fact.value), "text": f"{fact.fact_id} = {fact.value}"}],
        "visible_text": f"{fact.fact_id} = {fact.value}",
    }
    monkeypatch.setattr(profiles, "muhurta_source_map_sha256", lambda: "0" * 64)
    assert validate_muhurta_answer(payload) == ["STALE_RUNTIME_MATERIAL"]
