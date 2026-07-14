"""Boundary-driven, calculation-only Muhūrta search for a low-risk work wedge."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Callable
from zoneinfo import ZoneInfo

from . import ENGINE_VERSION
from .config import CalculationConfig, ConfigError
from .error_registry import error_record
from .intervals import EventInterval, partition_interval
from .muhurta_models import (
    MuhurtaCompletedResult,
    MuhurtaFact,
    MuhurtaIncompleteResult,
    MuhurtaNearMiss,
    MuhurtaNeedsInputResult,
    MuhurtaProvenance,
    MuhurtaResult,
    MuhurtaRuleTrace,
    MuhurtaSearchRequest,
    MuhurtaTruncation,
    MuhurtaUnavailableResult,
    MuhurtaWindow,
)
from .muhurta_profiles import (
    MuhurtaGovernanceError,
    load_muhurta_rule_profile,
    load_muhurta_source_map,
    muhurta_rule_profile_sha256,
    muhurta_source_admission_evidence,
    muhurta_source_map_sha256,
)
from .pyjhora_facade import (
    BirthProfile,
    CivilDateUnavailableError,
    EngineOutputError,
    _EngineConfigSnapshot,
    _civil_day_utc_bounds,
    _offset_segment_starts,
    _run_muhurta_boundary_day,
    _valid_local_candidates,
)
from .signing import cache_domain_artifact

_SUPPORTED = {"general", "focused_work_session_v1"}
_HIGH_STAKES = {
    "marriage", "wedding", "contract", "elective_medical", "medical", "surgery",
    "investment", "financial", "legal_filing", "pregnancy", "harm",
}


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _error_fields(code: str, request_id: str, stage: str) -> dict:
    record = error_record(code, run_id=None, request_id=request_id, mode="muhurta", stage=stage)
    return {key: record[key] for key in ("error_code", "request_id", "mode", "stage", "retryable", "problem", "cause", "fix", "next_action")}


def _request_material(request: MuhurtaSearchRequest) -> dict:
    """Hash precise private range/place material without surfacing it."""
    return request.model_dump(mode="json", exclude={"deadline_utc", "cancel_requested", "include_trace"})


def _local_instant(civil_date: dt.date, hour: float, zone: ZoneInfo, preferred_offset_hours: float) -> dt.datetime:
    naive = dt.datetime.combine(civil_date, dt.time()) + dt.timedelta(seconds=round(hour * 3600))
    target_noon_offset = dt.datetime.combine(naive.date(), dt.time(12), tzinfo=zone).utcoffset()
    if naive.date() != civil_date and target_noon_offset is not None:
        preferred_offset_hours = target_noon_offset.total_seconds() / 3600
    candidates = [naive.replace(tzinfo=zone, fold=fold) for fold in (0, 1)]
    roundtrip = [
        value for value in candidates
        if value.astimezone(dt.UTC).astimezone(zone).replace(tzinfo=None) == naive
    ]
    by_utc = {value.astimezone(dt.UTC): value for value in roundtrip}
    if len(by_utc) == 1:
        return next(iter(by_utc.values()))
    valid = [
        value for value in by_utc.values()
        if value.utcoffset() is not None
        and value.utcoffset().total_seconds() / 3600 == preferred_offset_hours
    ]
    if not valid:
        raise ValueError("astronomical boundary cannot be bound to the day's resolved IANA offset")
    return valid[0]


def _add_utc(value: dt.datetime, delta: dt.timedelta, zone: ZoneInfo) -> dt.datetime:
    return (value.astimezone(dt.UTC) + delta).astimezone(zone)


def _local_constraint_boundaries(civil_date: dt.date, wall_time: dt.time, zone: ZoneInfo) -> tuple[dt.datetime, ...]:
    """Project a local wall-clock bound onto every physical occurrence in a civil day."""
    naive = dt.datetime.combine(civil_date, wall_time)
    day_start, day_end = _civil_day_utc_bounds(civil_date, zone)
    candidates = tuple(
        instant.astimezone(zone) for instant in _valid_local_candidates(naive, zone)
        if day_start <= instant < day_end
    )
    if candidates:
        return candidates
    # For a bound inside a spring-forward gap, the offset transition is the
    # physical boundary at which local times after the requested wall time begin.
    for transition in _offset_segment_starts(day_start, day_end, zone)[1:]:
        before = (transition - dt.timedelta(microseconds=1)).astimezone(zone).replace(tzinfo=None)
        after = transition.astimezone(zone).replace(tzinfo=None)
        if before < naive < after:
            return (transition.astimezone(zone),)
    return ()


def _utc_min(left: dt.datetime, right: dt.datetime) -> dt.datetime:
    return left if left.astimezone(dt.UTC) <= right.astimezone(dt.UTC) else right


def _config_material(config: CalculationConfig | _EngineConfigSnapshot) -> dict:
    if isinstance(config, CalculationConfig):
        return {
            "ayanamsa": config.ayanamsa.upper(), "rahu_ketu": config.rahu_ketu,
            "node_aspects": config.node_aspects, "charts": tuple(config.resolved_charts()),
            "modules": tuple(sorted(config.resolved_modules())),
        }
    return {
        "ayanamsa": config.ayanamsa, "rahu_ketu": config.rahu_ketu,
        "node_aspects": config.node_aspects, "charts": config.charts,
        "modules": config.modules,
    }


def muhurta_config_sha256() -> str:
    return _sha(_config_material(CalculationConfig(charts=("D1",))))


def _deadline_expired(request: MuhurtaSearchRequest, now: Callable[[], dt.datetime]) -> bool:
    return request.deadline_utc is not None and now().astimezone(dt.UTC) >= request.deadline_utc


class MuhurtaFacade:
    def __init__(self, *, clock: Callable[[], dt.datetime] | None = None, cancel_check: Callable[[], bool] | None = None):
        self._clock = clock or (lambda: dt.datetime.now(dt.UTC))
        self._cancel_check = cancel_check or (lambda: False)

    def search(self, request: MuhurtaSearchRequest) -> MuhurtaResult:
        range_hash = _sha(_request_material(request))
        request_id = "muh_" + range_hash[:24]
        if request.activity in _HIGH_STAKES:
            return MuhurtaUnavailableResult(status="unavailable", **_error_fields("HIGH_STAKES_ACTIVITY", request_id, "activity_routing"))
        if request.activity not in _SUPPORTED:
            return MuhurtaNeedsInputResult(status="needs_input", **_error_fields("ACTIVITY_UNSUPPORTED", request_id, "activity_routing"))
        def incomplete(code: str, stage: str, *, days: int = 0, boundaries: int = 0, candidates: int = 0) -> MuhurtaIncompleteResult:
            return MuhurtaIncompleteResult(
                status="incomplete", days_processed=days, boundary_count=boundaries,
                processed_candidate_intervals=candidates,
                **_error_fields(code, request_id, stage),
            )

        if request.cancel_requested or self._cancel_check():
            return incomplete("SEARCH_CANCELLED", "boundary_collection")
        if _deadline_expired(request, self._clock):
            return incomplete("SEARCH_DEADLINE_EXCEEDED", "boundary_collection")
        try:
            rule_profile = load_muhurta_rule_profile()
            source_map = load_muhurta_source_map()
            source_evidence = muhurta_source_admission_evidence()
        except MuhurtaGovernanceError:
            return MuhurtaUnavailableResult(status="unavailable", **_error_fields("GOVERNANCE_INTEGRITY_ERROR", request_id, "governance"))

        zone = ZoneInfo(request.place.zone_id)
        start_resolution, end_resolution = request.resolved_start(), request.resolved_end()
        local_start = start_resolution.utc_instant.astimezone(zone)
        days: list[dt.date] = []
        day = local_start.date()
        final_day = (end_resolution.utc_instant - dt.timedelta(microseconds=1)).astimezone(zone).date()
        while day <= final_day:
            days.append(day)
            day += dt.timedelta(days=1)
        engine_profile = BirthProfile(
            name="event-search", date=(days[0].year, days[0].month, days[0].day), time=(0, 0, 0),
            latitude=request.place.latitude, longitude=request.place.longitude,
            timezone=local_start.utcoffset().total_seconds() / 3600,  # type: ignore[union-attr]
        )
        primitives = []
        boundary_progress = 0
        engine_config = CalculationConfig(charts=("D1",))
        applied_snapshot: _EngineConfigSnapshot | None = None
        actual_ephemeris: str | None = None
        for civil_day in days:
            if request.cancel_requested or self._cancel_check():
                return incomplete("SEARCH_CANCELLED", "boundary_collection", days=len(primitives), boundaries=boundary_progress)
            if _deadline_expired(request, self._clock):
                return incomplete("SEARCH_DEADLINE_EXCEEDED", "boundary_collection", days=len(primitives), boundaries=boundary_progress)
            try:
                result = _run_muhurta_boundary_day(
                    engine_profile, civil_day, request.place.zone_id, engine_config,
                    rule_profile.transition_canonicalization.tolerance_seconds,
                )
            except CivilDateUnavailableError:
                return MuhurtaNeedsInputResult(
                    status="needs_input",
                    **_error_fields("CIVIL_DATE_UNAVAILABLE", request_id, "boundary_collection"),
                )
            except (ConfigError, EngineOutputError, ArithmeticError, ValueError):
                return incomplete("ENGINE_CROSSCHECK_FAILED", "boundary_collection", days=len(primitives), boundaries=boundary_progress)
            if applied_snapshot is not None and (result.config != applied_snapshot or result.ephemeris_mode != actual_ephemeris):
                return incomplete("ENGINE_CROSSCHECK_FAILED", "boundary_collection", days=len(primitives), boundaries=boundary_progress)
            applied_snapshot, actual_ephemeris = result.config, result.ephemeris_mode
            primitives.append(result.day)
            boundary_progress += len(result.day.values)
        if request.cancel_requested or self._cancel_check():
            return incomplete("SEARCH_CANCELLED", "partition", days=len(primitives), boundaries=boundary_progress)
        if _deadline_expired(request, self._clock):
            return incomplete("SEARCH_DEADLINE_EXCEEDED", "partition", days=len(primitives), boundaries=boundary_progress)

        bounds = EventInterval(request.start, request.end)
        boundaries: list[dt.datetime] = [request.start, request.end]
        kind_counts: dict[str, int] = {}
        for day_values in primitives:
            for value in day_values.values:
                if value.start_utc is None:
                    return incomplete("ENGINE_CROSSCHECK_FAILED", "boundary_normalization", days=len(primitives), boundaries=boundary_progress)
                start = value.start_utc.astimezone(zone)
                boundaries.append(start)
                kind_counts[value.kind] = kind_counts.get(value.kind, 0) + 1
                if value.end_hour is not None:
                    if value.end_utc is None:
                        return incomplete("ENGINE_CROSSCHECK_FAILED", "boundary_normalization", days=len(primitives), boundaries=boundary_progress)
                    end = value.end_utc.astimezone(zone)
                    boundaries.append(end)
        constraints = request.hard_constraints
        if constraints.local_time_start is not None:
            assert constraints.local_time_end is not None
            for civil_day in days:
                boundaries.extend(_local_constraint_boundaries(civil_day, constraints.local_time_start, zone))
                boundaries.extend(_local_constraint_boundaries(civil_day, constraints.local_time_end, zone))
        atoms = partition_interval(bounds, boundaries)
        if len(atoms) > request.max_candidate_intervals:
            return incomplete("CANDIDATE_LIMIT_EXCEEDED", "partition", days=len(primitives), boundaries=boundary_progress)

        # Sunrise is a point primitive; pair each day's sunrise and sunset explicitly.
        daylight = tuple(
            EventInterval(
                next(v.start_utc for v in day_values.values if v.kind == "sunrise").astimezone(zone),  # type: ignore[union-attr]
                next(v.start_utc for v in day_values.values if v.kind == "sunset").astimezone(zone),  # type: ignore[union-attr]
            )
            for day_values in primitives
            if any(v.kind == "sunrise" for v in day_values.values) and any(v.kind == "sunset" for v in day_values.values)
        )

        duration = dt.timedelta(minutes=request.duration_minutes)
        accepted: list[MuhurtaWindow] = []
        rejected: list[MuhurtaNearMiss] = []
        candidate_traces: list[MuhurtaRuleTrace] = []
        pending_doctrine = MuhurtaRuleTrace(
            rule_id="muhurta.general.doctrinal_eligibility", classification="hard",
            status="pending", source_status="pending", outputs=("source_admission_required",),
        )
        preference_present = bool(
            request.preferences.prefer_daylight
            or request.preferences.preferred_local_time_start is not None
        )
        pending_preference = MuhurtaRuleTrace(
            rule_id="muhurta.focused_work.preference", classification="soft",
            status="pending" if preference_present else "not_applicable", source_status="pending",
            outputs=(("present_but_not_applied",) if preference_present else ("no_preference_supplied",)),
        )
        for index, atom in enumerate(atoms):
            if index % 32 == 0 and (request.cancel_requested or self._cancel_check()):
                return incomplete("SEARCH_CANCELLED", "evaluation", days=len(primitives), boundaries=boundary_progress, candidates=index)
            if index % 32 == 0 and _deadline_expired(request, self._clock):
                return incomplete("SEARCH_DEADLINE_EXCEEDED", "evaluation", days=len(primitives), boundaries=boundary_progress, candidates=index)
            full_end = _add_utc(atom.start, duration, zone)
            proposed_end = _utc_min(full_end, atom.end)
            rejection_rule_ids: list[str] = []
            duration_pass = atom.duration_seconds >= duration.total_seconds()
            if not duration_pass:
                rejection_rule_ids.append("muhurta.boundary.event_duration")
            local = atom.start.astimezone(zone)
            end_local = full_end.astimezone(zone)
            explicit_outputs: list[str] = []
            if local.weekday() in constraints.excluded_weekdays:
                explicit_outputs.append("excluded_weekday")
            if constraints.local_time_start is not None and (
                local.date() != end_local.date()
                or local.timetz().replace(tzinfo=None) < constraints.local_time_start
                or end_local.timetz().replace(tzinfo=None) > constraints.local_time_end
            ):
                explicit_outputs.append("outside_explicit_local_hours")
            if constraints.require_daylight and not any(
                period.start.astimezone(dt.UTC) <= atom.start.astimezone(dt.UTC)
                and full_end.astimezone(dt.UTC) <= period.end.astimezone(dt.UTC)
                for period in daylight
            ):
                explicit_outputs.append("outside_daylight")
            if explicit_outputs:
                rejection_rule_ids.append("muhurta.constraints.explicit")
            candidate_id = "mc_" + _sha({"range": range_hash, "start": atom.start.isoformat(), "end": proposed_end.isoformat()})[:24]
            explicit_trace = MuhurtaRuleTrace(
                rule_id="muhurta.constraints.explicit", classification="hard",
                status="fail" if explicit_outputs else "pass", source_status="not_required",
                inputs=(candidate_id,), outputs=tuple(explicit_outputs or ("eligible_by_explicit_constraints",)),
            )
            duration_trace = MuhurtaRuleTrace(
                rule_id="muhurta.boundary.event_duration", classification="hard",
                status="pass" if duration_pass else "fail", source_status="not_required",
                inputs=(candidate_id, str(request.duration_minutes)),
                outputs=(("fits_atomic_interval",) if duration_pass else ("crosses_astronomical_boundary",)),
            )
            candidate_traces.extend((explicit_trace, duration_trace))
            if rejection_rule_ids:
                rejected.append(MuhurtaNearMiss(
                    candidate_id=candidate_id, start=atom.start, end=proposed_end,
                    rejection_rule_ids=tuple(sorted(rejection_rule_ids)),
                ))
                continue
            end = full_end
            window_id = "mw_" + _sha({"range": range_hash, "start": atom.start.isoformat(), "end": end.isoformat()})[:24]
            accepted.append(MuhurtaWindow(
                window_id=window_id, start=atom.start, end=end,
                eligibility_tier="calculation_only_source_pending",
                tradeoffs=("Astronomical boundaries are computed; doctrinal eligibility and ranking are unavailable pending source review.",),
                rule_traces=(explicit_trace, duration_trace, pending_doctrine, pending_preference),
            ))

        # Stable key is frozen: chronological start, end, then opaque ID. No soft
        # score is applied while the governed pack is pending.
        accepted.sort(key=lambda item: (item.start.astimezone(dt.UTC), item.end.astimezone(dt.UTC), item.window_id))
        rejected.sort(key=lambda item: (len(item.rejection_rule_ids), item.start.astimezone(dt.UTC), item.candidate_id))
        returned, near = tuple(accepted[:request.result_limit]), tuple(rejected[:request.near_miss_limit])
        profile_rule_traces = (
            MuhurtaRuleTrace(
                rule_id="muhurta.constraints.explicit", classification="hard",
                status="pass" if accepted else "fail", source_status="not_required",
                outputs=("evaluated_for_every_candidate",),
            ),
            MuhurtaRuleTrace(
                rule_id="muhurta.boundary.event_duration", classification="hard",
                status="pass" if accepted else "fail", source_status="not_required",
                outputs=("half_open_atomic_boundary_enforced",),
            ),
            pending_doctrine,
            pending_preference,
        )
        facts = [
            MuhurtaFact(fact_id="muhurta.search.atomic_interval_count", value=len(atoms)),
            MuhurtaFact(fact_id="muhurta.search.duration_minutes", value=request.duration_minutes),
            MuhurtaFact(fact_id="muhurta.search.source_gate", value="pending"),
            MuhurtaFact(fact_id="muhurta.search.natal_personalization", value="supplied_not_evaluated_pending_admission" if request.natal else "omitted"),
            MuhurtaFact(fact_id="muhurta.search.preferences_status", value="present_pending_not_applied" if preference_present else "omitted"),
            MuhurtaFact(fact_id="muhurta.search.transition_canonicalization_version", value=rule_profile.transition_canonicalization.version),
            MuhurtaFact(fact_id="muhurta.search.transition_cluster_tolerance_seconds", value=rule_profile.transition_canonicalization.tolerance_seconds),
        ]
        for kind, count in sorted(kind_counts.items()):
            safe_kind = kind.replace("-", "_")
            facts.append(MuhurtaFact(fact_id=f"muhurta.boundaries.{safe_kind}.count", value=count))
        for window in returned:
            facts.extend((
                MuhurtaFact(fact_id=f"muhurta.windows.{window.window_id}.start", value=window.start.isoformat()),
                MuhurtaFact(fact_id=f"muhurta.windows.{window.window_id}.end", value=window.end.isoformat()),
            ))
        facts.sort(key=lambda item: item.fact_id)

        assert applied_snapshot is not None and actual_ephemeris is not None
        config_sha256 = _sha(_config_material(applied_snapshot))
        if config_sha256 != muhurta_config_sha256():
            return incomplete("ENGINE_CROSSCHECK_FAILED", "provenance", days=len(primitives), boundaries=boundary_progress, candidates=len(atoms))
        provenance = MuhurtaProvenance(
            zone_id=request.place.zone_id, tzdb_fingerprint=start_resolution.tzdb_fingerprint,
            start_normalized_utc=start_resolution.utc_instant.isoformat(timespec="seconds").replace("+00:00", "Z"),
            end_normalized_utc=end_resolution.utc_instant.isoformat(timespec="seconds").replace("+00:00", "Z"),
            start_resolved_offset_minutes=start_resolution.offset_minutes,
            end_resolved_offset_minutes=end_resolution.offset_minutes,
            start_fold=start_resolution.fold, end_fold=end_resolution.fold,
            ephemeris_mode=actual_ephemeris, engine_version=ENGINE_VERSION, config_sha256=config_sha256,
            rule_profile_sha256=muhurta_rule_profile_sha256(), source_map_sha256=muhurta_source_map_sha256(),
            source_admission_sha256=str(source_evidence["sha256"]), source_review_status=source_map.review.status,
            boundary_collector="pyjhora_daily_transition_batch_v1",
        )
        artifact = cache_domain_artifact({
            "mode": "muhurta", "activity": request.activity, "search_range_sha256": range_hash,
            "config_sha256": config_sha256, "ephemeris_mode": actual_ephemeris,
            "rule_profile_sha256": muhurta_rule_profile_sha256(),
            "source_map_sha256": muhurta_source_map_sha256(), "source_admission_sha256": source_evidence["sha256"],
            "window_ids": [window.window_id for window in returned],
            "facts": [fact.model_dump(mode="json") for fact in facts],
            "profile_rule_traces": [trace.model_dump(mode="json") for trace in profile_rule_traces],
            "candidate_rule_traces": [trace.model_dump(mode="json") for trace in candidate_traces],
            "truncation": {"windows": [len(accepted), len(returned)], "near_misses": [len(rejected), len(near)]},
            "provenance": provenance.model_dump(mode="json"),
        })
        only_too_short = bool(rejected) and all(
            item.rejection_rule_ids == ("muhurta.boundary.event_duration",) for item in rejected
        )
        return MuhurtaCompletedResult(
            status="completed", request_id=request_id, activity=request.activity,
            anchor_summary=f"event search: {request.start.isoformat()} to {request.end.isoformat()}; {request.place.zone_id}",
            search_range_sha256=range_hash, facts=tuple(facts), windows=returned, near_misses=near,
            empty_reason=("no_atomic_interval_fits_duration" if not accepted and only_too_short else "all_candidates_excluded_by_explicit_constraints" if not accepted and rejected else None),
            total_candidate_intervals=len(atoms), processed_candidate_intervals=len(atoms),
            window_truncation=MuhurtaTruncation(truncated=len(returned) < len(accepted), total_count=len(accepted), returned_count=len(returned)),
            near_miss_truncation=MuhurtaTruncation(truncated=len(near) < len(rejected), total_count=len(rejected), returned_count=len(near)),
            rule_traces=profile_rule_traces,
            limitations=(
                "Doctrinal eligibility, soft ranking, and interpretation are unavailable until a source pack and qualified human review are admitted.",
                "Varjyam, amrita, durmuhurta and weekday periods are returned only as calculated boundaries; they are not applied as doctrine.",
                "Optional natal input, when supplied, is bound but explicitly not evaluated; tara-bala and candra-bala remain unavailable pending governed rule admission.",
                "Preferences are recorded only as present/omitted and are not scored while the soft-rule source gate is pending.",
                "Requested planetary-change boundaries are not accepted because no independently verified request primitive is exposed.",
                "No calendar, persistence, ResearchRun, REST, or external side effect is performed.",
            ),
            provenance=provenance, artifact_id=artifact["artifact_id"], artifact_sha256=artifact["artifact_sha256"], artifact_token=artifact["artifact_token"],
            trace=tuple(candidate_traces[:100]) if request.include_trace else None,
            trace_truncation=MuhurtaTruncation(
                truncated=len(candidate_traces[:100]) < len(candidate_traces),
                total_count=len(candidate_traces), returned_count=len(candidate_traces[:100]),
            ) if request.include_trace else None,
        )
