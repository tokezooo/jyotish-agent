"""Additive Phase 0 contracts for the Jaimini domain.

This module deliberately contains no chart geometry.  It freezes the public input,
result, rule-profile, source-gate, and fixture shapes that later calculation work
must satisfy.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

JaiminiRuleProfileId = Literal["jaimini_core_v1"]
AnalysisScope = Literal["core", "core_with_chara_dasha"]
InterpretationStatus = Literal["available", "unavailable"]
ReviewStatus = Literal["pending", "approved", "rejected"]

_MIN_YEAR = 1800
_MAX_YEAR = 2200
_MAX_APPROXIMATE_MINUTES = 120


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _FrozenStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class JaiminiPlace(_StrictModel):
    name: str = Field(min_length=1, max_length=200, description="Non-authoritative place label")
    latitude: float = Field(ge=-90, le=90, description="Decimal degrees north")
    longitude: float = Field(ge=-180, le=180, description="Decimal degrees east")
    timezone: str = Field(
        min_length=1,
        max_length=100,
        description="IANA timezone identifier; fixed or inferred offsets are not accepted",
        examples=["Asia/Kolkata"],
    )


class ExactJaiminiBirthInput(_StrictModel):
    confidence: Literal["exact"]
    date: dt.date
    time: dt.time
    place: JaiminiPlace

    @field_validator("date")
    @classmethod
    def supported_year(cls, value: dt.date) -> dt.date:
        if not _MIN_YEAR <= value.year <= _MAX_YEAR:
            raise ValueError(f"year must be between {_MIN_YEAR} and {_MAX_YEAR}")
        return value


class ApproximateJaiminiBirthInput(_StrictModel):
    confidence: Literal["approximate"]
    date: dt.date
    earliest_time: dt.time
    latest_time: dt.time
    place: JaiminiPlace
    sensitivity_step_minutes: Literal[5] = 5

    @field_validator("date")
    @classmethod
    def supported_year(cls, value: dt.date) -> dt.date:
        return ExactJaiminiBirthInput.supported_year(value)

    @model_validator(mode="after")
    def bounded_ordered_range(self) -> "ApproximateJaiminiBirthInput":
        start = dt.datetime.combine(self.date, self.earliest_time)
        end = dt.datetime.combine(self.date, self.latest_time)
        minutes = (end - start).total_seconds() / 60
        if minutes <= 0:
            raise ValueError("latest_time must be after earliest_time on the same date")
        if minutes > _MAX_APPROXIMATE_MINUTES:
            raise ValueError("birth time range must not exceed 120 minutes")
        return self

    @computed_field(return_type=int)
    @property
    def sample_count(self) -> int:
        start = dt.datetime.combine(self.date, self.earliest_time)
        end = dt.datetime.combine(self.date, self.latest_time)
        minutes = int((end - start).total_seconds() // 60)
        return minutes // self.sensitivity_step_minutes + 1


JaiminiBirthInput = Annotated[
    ExactJaiminiBirthInput | ApproximateJaiminiBirthInput,
    Field(discriminator="confidence"),
]


class JaiminiInput(_StrictModel):
    profile: str = Field(min_length=1, max_length=200, description="Caller-owned profile reference")
    birth: JaiminiBirthInput
    rule_profile: JaiminiRuleProfileId = "jaimini_core_v1"
    analysis_scope: AnalysisScope = "core_with_chara_dasha"
    reference_date: dt.date | None = None
    include_trace: bool = False


class JaiminiFact(_FrozenStrictModel):
    fact_id: str = Field(min_length=1, max_length=160)
    value: str | int | float | bool | None
    stability: Literal["stable", "unstable", "not_assessed"] = "not_assessed"


class JaiminiSection(_FrozenStrictModel):
    section_id: str = Field(min_length=1, max_length=80)
    facts: tuple[JaiminiFact, ...] = Field(max_length=144)


class JaiminiLimitation(_FrozenStrictModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    message: str = Field(min_length=1, max_length=500)


class JaiminiTruncation(_FrozenStrictModel):
    truncated: bool
    total_count: int = Field(ge=0)
    returned_count: int = Field(ge=0)

    @model_validator(mode="after")
    def counts_are_consistent(self) -> "JaiminiTruncation":
        if self.returned_count > self.total_count:
            raise ValueError("returned_count cannot exceed total_count")
        if self.truncated != (self.returned_count < self.total_count):
            raise ValueError("truncated must describe the returned and total counts")
        return self


class JaiminiProvenance(_FrozenStrictModel):
    rule_profile_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    rule_profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_map_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_review_status: ReviewStatus
    engine_version: str | None = None
    ephemeris: str | None = None
    tzdb_version: str | None = None


class _JaiminiResultBase(_StrictModel):
    request_id: str = Field(min_length=1, max_length=100)
    mode: Literal["jaimini"] = "jaimini"
    rule_profile: JaiminiRuleProfileId = "jaimini_core_v1"
    warnings: tuple[str, ...] = ()
    limitations: tuple[JaiminiLimitation, ...]
    interpretation_status: InterpretationStatus
    provenance: JaiminiProvenance


class JaiminiCompletedResult(_JaiminiResultBase):
    status: Literal["completed"]
    profile_name: str = Field(min_length=1, max_length=200)
    anchor_summary: str = Field(min_length=1, max_length=200)
    sections: tuple[JaiminiSection, ...] = Field(max_length=12)
    truncation: JaiminiTruncation


class JaiminiNeedsInputResult(_JaiminiResultBase):
    status: Literal["needs_input"]
    next_action: Literal["provide_birth_range", "confirm_birth_time"]


class JaiminiUnavailableResult(_JaiminiResultBase):
    status: Literal["unavailable"]
    next_action: Literal["inspect_source_status"]


class JaiminiIncompleteResult(_JaiminiResultBase):
    status: Literal["incomplete"]
    next_action: Literal["retry_calculation", "narrow_request"]


JaiminiResult = Annotated[
    JaiminiCompletedResult
    | JaiminiNeedsInputResult
    | JaiminiUnavailableResult
    | JaiminiIncompleteResult,
    Field(discriminator="status"),
]


class KarakaRules(_FrozenStrictModel):
    schemes: tuple[Literal[7, 8], ...]
    seven_karakas: tuple[str, ...]
    eight_karaka_addition: Literal["PiK"]
    rahu_treatment: Literal["reverse_within_sign"]
    longitude_precision_arcseconds: Literal[1]
    exact_tie_policy: Literal["error_requires_adjudication"]
    near_tie_threshold_arcseconds: Literal[60]
    near_tie_policy: Literal["flag_without_reordering"]


class ArudhaRules(_FrozenStrictModel):
    counting: Literal["inclusive_sign_count"]
    exception: Literal["same_or_seventh_moves_to_tenth"]


class CoLordRules(_FrozenStrictModel):
    scorpio: tuple[Literal["Mars", "Ketu"], ...]
    aquarius: tuple[Literal["Saturn", "Rahu"], ...]
    resolution: Literal["greater_rashi_duration_then_degree_then_fixed_order"]
    fixed_order: tuple[str, ...]


class CharaDashaRules(_FrozenStrictModel):
    progression: Literal["odd_forward_even_reverse"]
    duration: Literal["inclusive_count_to_lord_minus_one_minimum_one"]
    antardasha: Literal["same_direction_from_next_sign"]
    gender_semantics: Literal["required_binary_for_progression_seed"]
    supported_gender_values: tuple[Literal["female", "male"], ...]


class TimeRules(_FrozenStrictModel):
    year_length_days: Literal[365.2425]
    rounding: Literal["microsecond_half_even"]
    interval_bounds: Literal["[start,end)"]


class JaiminiRuleProfile(_FrozenStrictModel):
    schema_version: Literal[1]
    profile_id: JaiminiRuleProfileId
    version: Literal["1.0.0"]
    school: str
    karakas: KarakaRules
    arudha: ArudhaRules
    co_lords: CoLordRules
    chara_dasha: CharaDashaRules
    time: TimeRules


class ReviewMetadata(_FrozenStrictModel):
    status: ReviewStatus
    reviewer: str | None
    reviewer_role: str | None
    approval_criteria: tuple[str, ...]
    adjudication_procedure: str
    note: str

    @model_validator(mode="after")
    def approved_requires_reviewer(self) -> "ReviewMetadata":
        if self.status == "approved" and not self.reviewer:
            raise ValueError("approved review metadata requires a reviewer")
        return self


class RuleSourceMapping(_FrozenStrictModel):
    rule_id: str
    school: str
    fragment_id: str | None
    fragment_sha256: str | None
    source_status: ReviewStatus

    @model_validator(mode="after")
    def approved_requires_source(self) -> "RuleSourceMapping":
        if self.source_status == "approved" and (
            not self.fragment_id or not self.fragment_sha256
        ):
            raise ValueError("approved rule mappings require fragment ID and checksum")
        return self


class JaiminiSourceMap(_FrozenStrictModel):
    schema_version: Literal[1]
    rule_profile_id: JaiminiRuleProfileId
    rule_profile_version: Literal["1.0.0"]
    rule_profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    calculation_status: Literal["available"]
    interpretation_status: Literal["unavailable"]
    review: ReviewMetadata
    rules: tuple[RuleSourceMapping, ...]


class JaiminiFixture(_FrozenStrictModel):
    fixture_id: str
    coverage: Literal[
        "karaka_tie",
        "arudha_exception",
        "co_lord_case",
        "exact_dasha_boundary",
        "approximate_time_sensitivity",
    ]
    synthetic: Literal[True]
    public_safe: Literal[True]
    input: JaiminiInput
    scenario_parameters: dict[str, Any]
    expected_calculation_status: Literal["pending_independent_implementation"]
    rule_profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_map_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review: ReviewMetadata
