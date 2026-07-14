"""Private experimental orchestration for the source-bound Muhūrta surface."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal
from zoneinfo import ZoneInfo

from ..config import CalculationConfig
from ..muhurta import MuhurtaFacade
from ..muhurta_models import MuhurtaSearchRequest
from ..pyjhora_facade import BirthProfile, _run_muhurta_boundary_day
from .muhurta_pack import (
    MuhurtaActivityProfile,
    MuhurtaEligibilityInput,
    MuhurtaRankingCandidate,
    MuhurtaRenderedReport,
    MuhurtaRuleInterval,
    evaluate_muhurta_eligibility,
    load_muhurta_admitted_rule_pack,
    load_muhurta_ranking_profile,
    rank_muhurta_candidates,
    render_muhurta_report,
    route_muhurta_activity,
)


@dataclass(frozen=True)
class MuhurtaFullExecution:
    status: Literal["completed", "no_window", "unavailable", "needs_input", "incomplete"]
    profile: MuhurtaActivityProfile | None
    report: MuhurtaRenderedReport | None
    reason_code: str | None = None


def _base_request(value: MuhurtaSearchRequest) -> MuhurtaSearchRequest:
    payload = value.model_dump(
        mode="json",
        exclude={"mode", "locale", "include_evidence", "range_duration_seconds"},
    )
    payload["activity"] = "focused_work_session_v1"
    payload["result_limit"] = 20
    payload["near_miss_limit"] = 20
    payload["include_trace"] = False
    return MuhurtaSearchRequest.model_validate(payload)


def _day_primitives(
    request: MuhurtaSearchRequest, civil_date: dt.date
):
    zone = ZoneInfo(request.place.zone_id)
    local = request.start.astimezone(zone)
    profile = BirthProfile(
        name="private-muhurta-experiment",
        date=(civil_date.year, civil_date.month, civil_date.day),
        time=(0, 0, 0),
        latitude=request.place.latitude,
        longitude=request.place.longitude,
        timezone=local.utcoffset().total_seconds() / 3600,  # type: ignore[union-attr]
    )
    return _run_muhurta_boundary_day(
        profile,
        civil_date,
        request.place.zone_id,
        CalculationConfig(charts=("D1",)),
    ).day.values


def _inside_daylight(start: dt.datetime, end: dt.datetime, values) -> bool:
    sunrise = next((item.start_utc for item in values if item.kind == "sunrise"), None)
    sunset = next((item.start_utc for item in values if item.kind == "sunset"), None)
    return bool(
        sunrise is not None
        and sunset is not None
        and sunrise <= start.astimezone(dt.UTC)
        and end.astimezone(dt.UTC) <= sunset
    )


def _preference_score(
    request: MuhurtaSearchRequest,
    start: dt.datetime,
    end: dt.datetime,
    daylight: bool,
) -> int:
    score = int(request.preferences.prefer_daylight and daylight)
    preferred_start = request.preferences.preferred_local_time_start
    preferred_end = request.preferences.preferred_local_time_end
    if preferred_start is not None and preferred_end is not None:
        local_start = start.astimezone(ZoneInfo(request.place.zone_id))
        local_end = end.astimezone(ZoneInfo(request.place.zone_id))
        if (
            local_start.date() == local_end.date()
            and preferred_start <= local_start.timetz().replace(tzinfo=None)
            and local_end.timetz().replace(tzinfo=None) <= preferred_end
        ):
            score += 1
    return min(score, 2)


def execute_muhurta_full(
    value: MuhurtaSearchRequest,
    *,
    locale: Literal["ru", "en"],
    mode: Literal["quick", "full", "deep", "inspection"],
) -> MuhurtaFullExecution:
    """Run the immutable private baseline; never select the missing modern overlay."""

    route = route_muhurta_activity(value.activity, locale=locale)
    if route.status == "unsupported_high_stakes":
        return MuhurtaFullExecution(
            status="unavailable",
            profile=None,
            report=None,
            reason_code="HIGH_STAKES_ACTIVITY",
        )
    if route.status != "supported" or route.profile is None:
        return MuhurtaFullExecution(
            status="needs_input",
            profile=None,
            report=None,
            reason_code=route.reason_code,
        )

    request = _base_request(value)
    base = MuhurtaFacade().search(request)
    if base.status != "completed":
        return MuhurtaFullExecution(
            status="incomplete" if base.status == "incomplete" else "needs_input",
            profile=route.profile,
            report=None,
            reason_code=getattr(base, "error_code", "BASE_SEARCH_UNAVAILABLE"),
        )

    rule_pack = load_muhurta_admitted_rule_pack()
    rule_by_kind = {
        rule.boundary_kind: rule
        for rule in rule_pack.rules
        if route.profile in rule.applicable_profiles
    }
    primitive_cache: dict[dt.date, tuple] = {}

    def primitives(candidate_start: dt.datetime) -> tuple:
        civil_date = candidate_start.astimezone(
            ZoneInfo(request.place.zone_id)
        ).date()
        if civil_date not in primitive_cache:
            primitive_cache[civil_date] = tuple(_day_primitives(request, civil_date))
        return primitive_cache[civil_date]

    candidates: list[MuhurtaRankingCandidate] = []
    for window in base.windows:
        values = primitives(window.start)
        source_intervals = tuple(
            MuhurtaRuleInterval(
                rule_id=rule_by_kind[item.kind].rule_id,
                classification=rule_by_kind[item.kind].classification,
                start=item.start_utc,
                end=item.end_utc,
                source_locator=(
                    "Kalaprakasika, PDF p. 208 / printed p. 176"
                ),
            )
            for item in values
            if item.kind in rule_by_kind and item.end_utc is not None
        )
        daylight = _inside_daylight(window.start, window.end, values)
        eligibility = evaluate_muhurta_eligibility(
            MuhurtaEligibilityInput(
                profile=route.profile,
                start=window.start,
                end=window.end,
                zone_id=request.place.zone_id,
                panchanga_status="allowed",
                dosa_status="clear",
                weekday_status="allowed",
                daylight_status="inside" if daylight else "outside",
                lagna_status="available",
                require_daylight=False,
                require_lagna=False,
                source_rule_intervals=source_intervals,
                source_admitted=True,
            )
        )
        candidates.append(
            MuhurtaRankingCandidate(
                candidate_id=window.window_id,
                start=window.start,
                end=window.end,
                eligibility_status=eligibility.status,
                hard_failure_ids=eligibility.hard_failures,
                doctrinal_soft_score=0,
                natal_soft_adjustment=0,
                user_preference_score=_preference_score(
                    request, window.start, window.end, daylight
                ),
                confidence=0.65,
            )
        )
    for near in base.near_misses:
        candidates.append(
            MuhurtaRankingCandidate(
                candidate_id=near.candidate_id,
                start=near.start,
                end=near.end,
                eligibility_status="ineligible",
                hard_failure_ids=near.rejection_rule_ids,
                doctrinal_soft_score=0,
                natal_soft_adjustment=0,
                user_preference_score=0,
                confidence=0.65,
            )
        )

    ranking = rank_muhurta_candidates(
        tuple(candidates), load_muhurta_ranking_profile(route.profile)
    )
    report = render_muhurta_report(
        ranking,
        locale=locale,
        mode="deep" if mode == "inspection" else mode,
        include_inspection=mode == "inspection",
    )
    return MuhurtaFullExecution(
        status=ranking.status,
        profile=route.profile,
        report=report,
    )
