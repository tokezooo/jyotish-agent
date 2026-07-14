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
from .pyjhora_facade import BirthProfile, EngineOutputError, _run_muhurta_boundary_batch
from .signing import cache_domain_artifact
from .timezone_resolution import resolve_iana

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


def _local_instant(civil_date: dt.date, hour: float, zone: ZoneInfo) -> dt.datetime:
    naive = dt.datetime.combine(civil_date, dt.time()) + dt.timedelta(seconds=round(hour * 3600))
    local = naive.replace(tzinfo=zone)
    return local.astimezone(dt.UTC).astimezone(zone)


def _deadline_expired(request: MuhurtaSearchRequest, now: Callable[[], dt.datetime]) -> bool:
    return request.deadline_utc is not None and now().astimezone(dt.UTC) >= request.deadline_utc


class MuhurtaFacade:
    def __init__(self, *, clock: Callable[[], dt.datetime] | None = None):
        self._clock = clock or (lambda: dt.datetime.now(dt.UTC))

    def search(self, request: MuhurtaSearchRequest) -> MuhurtaResult:
        range_hash = _sha(_request_material(request))
        request_id = "muh_" + range_hash[:24]
        if request.activity in _HIGH_STAKES:
            return MuhurtaUnavailableResult(status="unavailable", **_error_fields("HIGH_STAKES_ACTIVITY", request_id, "activity_routing"))
        if request.activity not in _SUPPORTED:
            return MuhurtaNeedsInputResult(status="needs_input", **_error_fields("ACTIVITY_UNSUPPORTED", request_id, "activity_routing"))
        if request.cancel_requested:
            return MuhurtaIncompleteResult(status="incomplete", **_error_fields("SEARCH_CANCELLED", request_id, "boundary_collection"))
        if _deadline_expired(request, self._clock):
            return MuhurtaIncompleteResult(status="incomplete", **_error_fields("SEARCH_DEADLINE_EXCEEDED", request_id, "boundary_collection"))
        try:
            load_muhurta_rule_profile()
            source_map = load_muhurta_source_map()
            source_evidence = muhurta_source_admission_evidence()
        except MuhurtaGovernanceError:
            return MuhurtaUnavailableResult(status="unavailable", **_error_fields("GOVERNANCE_INTEGRITY_ERROR", request_id, "governance"))

        zone = ZoneInfo(request.place.zone_id)
        local_start, local_end = request.start.astimezone(zone), request.end.astimezone(zone)
        days: list[dt.date] = []
        day = local_start.date()
        while day <= local_end.date():
            days.append(day)
            day += dt.timedelta(days=1)
        engine_profile = BirthProfile(
            name="event-search", date=(days[0].year, days[0].month, days[0].day), time=(0, 0, 0),
            latitude=request.place.latitude, longitude=request.place.longitude,
            timezone=local_start.utcoffset().total_seconds() / 3600,  # type: ignore[union-attr]
        )
        try:
            dated_offsets = tuple(
                (
                    civil_day,
                    dt.datetime.combine(civil_day, dt.time(12), tzinfo=zone).utcoffset().total_seconds() / 3600,  # type: ignore[union-attr]
                )
                for civil_day in days
            )
            primitives = _run_muhurta_boundary_batch(engine_profile, dated_offsets, CalculationConfig(charts=("D1",)))
        except (ConfigError, EngineOutputError, ArithmeticError, ValueError):
            return MuhurtaIncompleteResult(status="incomplete", **_error_fields("ENGINE_CROSSCHECK_FAILED", request_id, "boundary_collection"))
        if _deadline_expired(request, self._clock):
            return MuhurtaIncompleteResult(status="incomplete", **_error_fields("SEARCH_DEADLINE_EXCEEDED", request_id, "boundary_collection"))

        bounds = EventInterval(request.start, request.end)
        boundaries: list[dt.datetime] = [request.start, request.end]
        kind_counts: dict[str, int] = {}
        for day_values in primitives:
            for value in day_values.values:
                start = _local_instant(day_values.civil_date, value.start_hour, zone)
                boundaries.append(start)
                kind_counts[value.kind] = kind_counts.get(value.kind, 0) + 1
                if value.end_hour is not None:
                    end_hour = value.end_hour + (24 if value.end_hour <= value.start_hour else 0)
                    end = _local_instant(day_values.civil_date, end_hour, zone)
                    boundaries.append(end)
        atoms = partition_interval(bounds, boundaries)
        if len(atoms) > request.max_candidate_intervals:
            return MuhurtaIncompleteResult(status="incomplete", **_error_fields("CANDIDATE_LIMIT_EXCEEDED", request_id, "partition"))

        # Sunrise is a point primitive; pair each day's sunrise and sunset explicitly.
        daylight = tuple(
            EventInterval(
                _local_instant(day_values.civil_date, next(v.start_hour for v in day_values.values if v.kind == "sunrise"), zone),
                _local_instant(day_values.civil_date, next(v.start_hour for v in day_values.values if v.kind == "sunset"), zone),
            )
            for day_values in primitives
            if any(v.kind == "sunrise" for v in day_values.values) and any(v.kind == "sunset" for v in day_values.values)
        )

        duration = dt.timedelta(minutes=request.duration_minutes)
        accepted: list[MuhurtaWindow] = []
        rejected: list[MuhurtaNearMiss] = []
        all_traces: list[MuhurtaRuleTrace] = []
        for atom in atoms:
            proposed_end = min(atom.start + duration, atom.end)
            reasons: list[str] = []
            if atom.end - atom.start < duration:
                reasons.append("crosses_astronomical_boundary")
            local = atom.start.astimezone(zone)
            end_local = (atom.start + duration).astimezone(zone)
            constraints = request.hard_constraints
            if local.weekday() in constraints.excluded_weekdays:
                reasons.append("excluded_weekday")
            if constraints.local_time_start is not None and (
                local.date() != end_local.date()
                or local.timetz().replace(tzinfo=None) < constraints.local_time_start
                or end_local.timetz().replace(tzinfo=None) > constraints.local_time_end
            ):
                reasons.append("outside_explicit_local_hours")
            if constraints.require_daylight and not any(period.start <= atom.start and atom.start + duration <= period.end for period in daylight):
                reasons.append("outside_daylight")
            candidate_id = "mc_" + _sha({"range": range_hash, "start": atom.start.isoformat(), "end": proposed_end.isoformat()})[:24]
            trace = MuhurtaRuleTrace(
                rule_id="muhurta.constraints.explicit", classification="hard",
                status="fail" if reasons else "pass", source_status="not_required",
                inputs=(atom.start.isoformat(),), outputs=tuple(reasons or ("eligible_by_explicit_constraints",)),
            )
            all_traces.append(trace)
            if reasons:
                rejected.append(MuhurtaNearMiss(candidate_id=candidate_id, start=atom.start, end=proposed_end, rejection_reasons=tuple(reasons)))
                continue
            end = atom.start + duration
            window_id = "mw_" + _sha({"range": range_hash, "start": atom.start.isoformat(), "end": end.isoformat()})[:24]
            accepted.append(MuhurtaWindow(
                window_id=window_id, start=atom.start, end=end,
                eligibility_tier="calculation_only_source_pending",
                tradeoffs=("Astronomical boundaries are computed; doctrinal eligibility and ranking are unavailable pending source review.",),
                rule_traces=(trace,),
            ))

        # Stable key is frozen: chronological start, end, then opaque ID. No soft
        # score is applied while the governed pack is pending.
        accepted.sort(key=lambda item: (item.start.astimezone(dt.UTC), item.end.astimezone(dt.UTC), item.window_id))
        rejected.sort(key=lambda item: (len(item.rejection_reasons), item.start.astimezone(dt.UTC), item.candidate_id))
        returned, near = tuple(accepted[:request.result_limit]), tuple(rejected[:request.near_miss_limit])
        facts = [
            MuhurtaFact(fact_id="muhurta.search.atomic_interval_count", value=len(atoms)),
            MuhurtaFact(fact_id="muhurta.search.duration_minutes", value=request.duration_minutes),
            MuhurtaFact(fact_id="muhurta.search.source_gate", value="pending"),
            MuhurtaFact(fact_id="muhurta.search.natal_personalization", value="supplied_calculation_only" if request.natal else "omitted"),
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

        resolved = resolve_iana(local_start.replace(tzinfo=None), mode="iana", zone_id=request.place.zone_id, fold=request.place.fold, asserted_offset_hours=None, longitude=request.place.longitude)
        provenance = MuhurtaProvenance(
            zone_id=request.place.zone_id, tzdb_fingerprint=resolved.tzdb_fingerprint,
            ephemeris_mode="moshier", engine_version=ENGINE_VERSION,
            rule_profile_sha256=muhurta_rule_profile_sha256(), source_map_sha256=muhurta_source_map_sha256(),
            source_admission_sha256=str(source_evidence["sha256"]), source_review_status=source_map.review.status,
            boundary_collector="pyjhora_daily_transition_batch_v1",
        )
        artifact = cache_domain_artifact({
            "mode": "muhurta", "activity": request.activity, "search_range_sha256": range_hash,
            "config_sha256": _sha({"ayanamsa": "LAHIRI", "charts": ["D1"]}),
            "rule_profile_sha256": muhurta_rule_profile_sha256(),
            "source_map_sha256": muhurta_source_map_sha256(), "source_admission_sha256": source_evidence["sha256"],
            "window_ids": [window.window_id for window in returned],
            "facts": [fact.model_dump(mode="json") for fact in facts],
            "rule_traces": [trace.model_dump(mode="json") for trace in all_traces],
            "truncation": {"windows": [len(accepted), len(returned)], "near_misses": [len(rejected), len(near)]},
            "provenance": provenance.model_dump(mode="json"),
        })
        only_too_short = bool(rejected) and all(
            item.rejection_reasons == ("crosses_astronomical_boundary",) for item in rejected
        )
        return MuhurtaCompletedResult(
            status="completed", request_id=request_id, activity=request.activity,
            anchor_summary=f"event search: {request.start.isoformat()} to {request.end.isoformat()}; {request.place.zone_id}",
            search_range_sha256=range_hash, facts=tuple(facts), windows=returned, near_misses=near,
            empty_reason=("no_atomic_interval_fits_duration" if not accepted and only_too_short else "all_candidates_excluded_by_explicit_constraints" if not accepted and rejected else None),
            total_candidate_intervals=len(atoms), processed_candidate_intervals=len(atoms),
            window_truncation=MuhurtaTruncation(truncated=len(returned) < len(accepted), total_count=len(accepted), returned_count=len(returned)),
            near_miss_truncation=MuhurtaTruncation(truncated=len(near) < len(rejected), total_count=len(rejected), returned_count=len(near)),
            limitations=(
                "Doctrinal eligibility, soft ranking, and interpretation are unavailable until a source pack and qualified human review are admitted.",
                "Varjyam, amrita, durmuhurta and weekday periods are returned only as calculated boundaries; they are not applied as doctrine.",
                "Optional natal input is bound to the request but tara-bala and candra-bala remain unavailable pending governed rule admission.",
                "Requested planetary-change boundaries are not accepted because no independently verified request primitive is exposed.",
                "No calendar, persistence, ResearchRun, REST, or external side effect is performed.",
            ),
            provenance=provenance, artifact_id=artifact["artifact_id"], artifact_sha256=artifact["artifact_sha256"], artifact_token=artifact["artifact_token"],
            trace=tuple(all_traces) if request.include_trace else None,
        )
