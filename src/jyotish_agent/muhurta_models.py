"""Strict contracts for the bounded Muhūrta focused-work search."""

from __future__ import annotations

import datetime as dt
import re
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, RootModel, computed_field, field_validator, model_validator

from .event_models import EventPlace
from .jaimini_models import ExactJaiminiBirthInput
from .timezone_resolution import TimezoneResolutionError, resolve_iana

MuhurtaRuleProfileId = Literal["muhurta_focused_work_v1"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class MuhurtaHardConstraints(_Strict):
    require_daylight: bool = False
    local_time_start: dt.time | None = None
    local_time_end: dt.time | None = None
    excluded_weekdays: tuple[int, ...] = Field(default=(), max_length=7)

    @field_validator("excluded_weekdays")
    @classmethod
    def weekdays(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if any(day < 0 or day > 6 for day in value) or len(set(value)) != len(value):
            raise ValueError("excluded weekdays must be unique integers in 0..6")
        return value

    @model_validator(mode="after")
    def local_window(self) -> "MuhurtaHardConstraints":
        if (self.local_time_start is None) != (self.local_time_end is None):
            raise ValueError("both local time bounds are required")
        if self.local_time_start is not None and self.local_time_end <= self.local_time_start:
            raise ValueError("local_time_end must be after local_time_start")
        return self


class MuhurtaPreferences(_Strict):
    preferred_local_time_start: dt.time | None = None
    preferred_local_time_end: dt.time | None = None
    prefer_daylight: bool = False

    @model_validator(mode="after")
    def local_window(self) -> "MuhurtaPreferences":
        if (self.preferred_local_time_start is None) != (self.preferred_local_time_end is None):
            raise ValueError("both preferred local time bounds are required")
        if self.preferred_local_time_start is not None and self.preferred_local_time_end <= self.preferred_local_time_start:
            raise ValueError("preferred_local_time_end must be after start")
        return self


class MuhurtaSearchRequest(_Strict):
    activity: str = Field(min_length=1, max_length=80)
    place: EventPlace
    start: dt.datetime
    end: dt.datetime | None = Field(
        default=None,
        description="Optional exclusive end; omitted derives seven local civil days from start",
    )
    start_fold: Literal[0, 1] | None = None
    end_fold: Literal[0, 1] | None = None
    duration_minutes: int = Field(ge=15, le=8 * 60)
    hard_constraints: MuhurtaHardConstraints = Field(default_factory=MuhurtaHardConstraints)
    preferences: MuhurtaPreferences = Field(default_factory=MuhurtaPreferences)
    natal: ExactJaiminiBirthInput | None = None
    rule_profile: MuhurtaRuleProfileId = "muhurta_focused_work_v1"
    result_limit: int = Field(default=5, ge=1, le=20)
    near_miss_limit: int = Field(default=5, ge=0, le=20)
    max_candidate_intervals: int = Field(default=5_000, ge=1, le=5_000)
    deadline_utc: dt.datetime | None = None
    cancel_requested: bool = False
    include_trace: bool = False

    @field_validator("start", "end", "deadline_utc", mode="before")
    @classmethod
    def strict_rfc3339(cls, value: object) -> object:
        if value is None:
            return value
        if not isinstance(value, str) or re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value
        ) is None:
            raise ValueError("event times must be strict timezone-aware RFC3339 strings")
        return value

    @model_validator(mode="after")
    def range_and_zone(self) -> "MuhurtaSearchRequest":
        if self.end is None:
            target_civil = self.start.replace(tzinfo=None) + dt.timedelta(days=7)
            try:
                derived = resolve_iana(
                    target_civil, mode="iana", zone_id=self.place.zone_id,
                    fold=self.end_fold, asserted_offset_hours=None, longitude=self.place.longitude,
                )
            except TimezoneResolutionError as exc:
                raise ValueError(exc.error_code) from exc
            object.__setattr__(self, "end", derived.utc_instant.astimezone(ZoneInfo(self.place.zone_id)))
        assert self.end is not None
        if self.start.tzinfo is None or self.end.tzinfo is None or self.start.utcoffset() is None or self.end.utcoffset() is None:
            raise ValueError("search range must be timezone aware")
        if self.place.fold is not None:
            raise ValueError("Muhūrta ranges require endpoint-specific folds, not place.fold")
        start_utc = self._resolve_endpoint(self.start, self.start_fold, "start")
        end_utc = self._resolve_endpoint(self.end, self.end_fold, "end")
        if end_utc <= start_utc:
            raise ValueError("end must be after start")
        if end_utc - start_utc > dt.timedelta(days=31):
            raise ValueError("SEARCH_RANGE_TOO_LARGE")
        if self.deadline_utc is not None and self.deadline_utc.utcoffset() != dt.timedelta(0):
            raise ValueError("deadline_utc must use UTC offset")
        return self

    def _resolve_endpoint(self, value: dt.datetime, fold: int | None, label: str) -> dt.datetime:
        try:
            resolved = resolve_iana(
                value.replace(tzinfo=None), mode="iana", zone_id=self.place.zone_id,
                fold=fold, asserted_offset_hours=None, longitude=self.place.longitude,
            )
        except TimezoneResolutionError as exc:
            raise ValueError(exc.error_code) from exc
        asserted = value.utcoffset()
        assert asserted is not None
        if asserted.total_seconds() != resolved.offset_minutes * 60:
            raise ValueError(f"{label} offset does not match endpoint fold and IANA zone")
        if value.astimezone(dt.UTC) != resolved.utc_instant:
            raise ValueError(f"{label} instant does not match endpoint civil time")
        return resolved.utc_instant

    def resolved_start(self):
        return resolve_iana(
            self.start.replace(tzinfo=None), mode="iana", zone_id=self.place.zone_id,
            fold=self.start_fold, asserted_offset_hours=None, longitude=self.place.longitude,
        )

    def resolved_end(self):
        assert self.end is not None
        return resolve_iana(
            self.end.replace(tzinfo=None), mode="iana", zone_id=self.place.zone_id,
            fold=self.end_fold, asserted_offset_hours=None, longitude=self.place.longitude,
        )

    @computed_field(return_type=int)
    @property
    def range_duration_seconds(self) -> int:
        return int((self.resolved_end().utc_instant - self.resolved_start().utc_instant).total_seconds())


class MuhurtaFact(_Frozen):
    fact_id: str = Field(pattern=r"^muhurta\.[A-Za-z0-9_.-]+$", max_length=200)
    value: str | int | float | bool | None


class MuhurtaRuleTrace(_Frozen):
    rule_id: str = Field(pattern=r"^muhurta\.[A-Za-z0-9_.-]+$")
    classification: Literal["hard", "soft"]
    status: Literal["pass", "fail", "pending", "not_applicable"]
    source_status: Literal["pending", "approved", "not_required"]
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()


class MuhurtaWindow(_Frozen):
    window_id: str = Field(pattern=r"^mw_[0-9a-f]{24}$")
    start: dt.datetime
    end: dt.datetime
    eligibility_tier: Literal["calculation_only_source_pending"]
    tradeoffs: tuple[str, ...]
    rule_traces: tuple[MuhurtaRuleTrace, ...] = ()


class MuhurtaNearMiss(_Frozen):
    candidate_id: str = Field(pattern=r"^mc_[0-9a-f]{24}$")
    start: dt.datetime
    end: dt.datetime
    rejection_rule_ids: tuple[str, ...] = Field(min_length=1)


class MuhurtaTruncation(_Frozen):
    truncated: bool
    total_count: int = Field(ge=0)
    returned_count: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def consistent(self) -> "MuhurtaTruncation":
        if self.returned_count > self.total_count or self.truncated != (self.returned_count < self.total_count):
            raise ValueError("truncation counts are inconsistent")
        return self


class MuhurtaProvenance(_Frozen):
    zone_id: str
    tzdb_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    start_normalized_utc: str
    end_normalized_utc: str
    start_resolved_offset_minutes: int
    end_resolved_offset_minutes: int
    start_fold: Literal[0, 1]
    end_fold: Literal[0, 1]
    ephemeris_mode: Literal["moshier", "swiss"]
    engine_version: str | None = None
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rule_profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_map_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_admission_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_review_status: Literal["pending", "approved", "rejected"]
    boundary_collector: Literal["pyjhora_daily_transition_batch_v1"]


class _BaseResult(_Strict):
    request_id: str = Field(pattern=r"^muh_[0-9a-f]{24}$")
    mode: Literal["muhurta"] = "muhurta"
    rule_profile: MuhurtaRuleProfileId = "muhurta_focused_work_v1"


class MuhurtaCompletedResult(_BaseResult):
    status: Literal["completed"]
    activity: Literal["general", "focused_work_session_v1"]
    anchor_summary: str = Field(max_length=240)
    search_range_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    facts: tuple[MuhurtaFact, ...]
    windows: tuple[MuhurtaWindow, ...] = Field(max_length=20)
    near_misses: tuple[MuhurtaNearMiss, ...] = Field(max_length=20)
    ranking_status: Literal["unavailable"] = "unavailable"
    interpretation_status: Literal["unavailable"] = "unavailable"
    interpretation: None = None
    empty_reason: str | None = None
    total_candidate_intervals: int = Field(ge=0, le=5_000)
    processed_candidate_intervals: int = Field(ge=0, le=5_000)
    window_truncation: MuhurtaTruncation
    near_miss_truncation: MuhurtaTruncation
    rule_traces: tuple[MuhurtaRuleTrace, ...] = Field(min_length=4, max_length=4)
    limitations: tuple[str, ...]
    provenance: MuhurtaProvenance
    artifact_id: str = Field(pattern=r"^jya_[0-9a-f]{24}$")
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    trace: tuple[MuhurtaRuleTrace, ...] | None = Field(default=None, max_length=100)
    trace_truncation: MuhurtaTruncation | None = None


class _Rescue(_BaseResult):
    stage: str
    retryable: bool
    problem: str
    cause: str
    fix: str


class MuhurtaNeedsInputResult(_Rescue):
    status: Literal["needs_input"]
    error_code: Literal["ACTIVITY_UNSUPPORTED", "SEARCH_RANGE_TOO_LARGE", "RULE_PROFILE_UNSUPPORTED", "INPUT_INVALID"]
    next_action: Literal["select_supported_activity", "narrow_search_range", "select_supported_rule_profile", "correct_request"]
    supported_values: tuple[str, ...] = ("general", "focused_work_session_v1")


class MuhurtaUnavailableResult(_Rescue):
    status: Literal["unavailable"]
    error_code: Literal["HIGH_STAKES_ACTIVITY", "GOVERNANCE_INTEGRITY_ERROR"]
    next_action: Literal["consult_qualified_professional", "inspect_source_status"]


class MuhurtaIncompleteResult(_Rescue):
    status: Literal["incomplete"]
    error_code: Literal["SEARCH_CANCELLED", "SEARCH_DEADLINE_EXCEEDED", "CANDIDATE_LIMIT_EXCEEDED", "ENGINE_CROSSCHECK_FAILED"]
    next_action: Literal["narrow_search_range", "retry_calculation"]
    ranking_status: Literal["unavailable"] = "unavailable"
    boundary_count: int = Field(default=0, ge=0, le=10_000)
    processed_candidate_intervals: int = Field(default=0, ge=0, le=5_000)
    days_processed: int = Field(default=0, ge=0, le=32)


MuhurtaResult = Annotated[MuhurtaCompletedResult | MuhurtaNeedsInputResult | MuhurtaUnavailableResult | MuhurtaIncompleteResult, Field(discriminator="status")]


class MuhurtaResultModel(RootModel[MuhurtaResult]):
    pass


class MuhurtaAnswerClaim(_Frozen):
    claim_type: Literal["computed_fact"]
    path: str = Field(pattern=r"^muhurta\.[A-Za-z0-9_.-]+$")
    value: str
    text: str


class MuhurtaAnswerSubmission(_Strict):
    artifact_id: str
    artifact_sha256: str
    artifact_token: str
    search_range_sha256: str
    window_ids: tuple[str, ...]
    claims: tuple[MuhurtaAnswerClaim, ...] = Field(min_length=1, max_length=100)
    visible_text: str
