"""Additive Phase 0 contracts for the Jaimini domain.

This module deliberately contains no chart geometry.  It freezes the public input,
result, rule-profile, source-gate, and fixture shapes that later calculation work
must satisfy.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
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
        max_length=100,
        description="IANA timezone identifier; fixed or inferred offsets are not accepted",
        examples=["Asia/Kolkata"],
    )
    fold: Literal[0, 1] | None = None
    asserted_offset_hours: float | None = Field(default=None, ge=-12, le=14)

    @field_validator("timezone")
    @classmethod
    def valid_iana_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("timezone must be a real IANA timezone identifier") from exc
        return value


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
        if (end - start).total_seconds() % (self.sensitivity_step_minutes * 60):
            raise ValueError("birth time range must be divisible by 5 minutes")
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
    gender: Literal["female", "male"] | None = None
    reference_date: dt.date | None = None
    include_trace: bool = False

    @model_validator(mode="after")
    def gender_matches_analysis_scope(self) -> "JaiminiInput":
        if self.analysis_scope == "core_with_chara_dasha" and self.gender is None:
            raise ValueError("gender is required for core_with_chara_dasha")
        if self.analysis_scope == "core" and self.gender is not None:
            raise ValueError("gender is not accepted for core geometry")
        return self


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
    source_admission_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_reviewer: str | None = None
    source_reviewer_role: str | None = None
    engine_version: str | None = None
    ephemeris_mode: Literal["moshier", "swiss"]
    tzdb_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class _JaiminiIdentityBase(_StrictModel):
    request_id: str = Field(min_length=1, max_length=100)
    mode: Literal["jaimini"] = "jaimini"
    rule_profile: JaiminiRuleProfileId = "jaimini_core_v1"


class _JaiminiResultBase(_JaiminiIdentityBase):
    warnings: tuple[str, ...] = ()
    limitations: tuple[JaiminiLimitation, ...]
    interpretation_status: InterpretationStatus
    provenance: JaiminiProvenance

    @model_validator(mode="after")
    def interpretation_fails_closed(self) -> "_JaiminiResultBase":
        if self.interpretation_status == "available":
            # Future activation must add signed renderer ID/version fields and verify
            # both that binding and governed source admission before relaxing this
            # public invariant. Source-review metadata alone is never sufficient.
            raise ValueError(
                "available interpretation requires a verified governed renderer "
                "ID/version; no governed renderer is admitted"
            )
        return self


class JaiminiCompletedResult(_JaiminiResultBase):
    status: Literal["completed"]
    profile_name: str = Field(min_length=1, max_length=200)
    anchor_summary: str = Field(min_length=1, max_length=200)
    sections: tuple[JaiminiSection, ...] = Field(max_length=12)
    truncation: JaiminiTruncation
    interpretation: tuple[str, ...] | None = None
    trace: tuple[JaiminiFact, ...] | None = Field(default=None, max_length=256)
    artifact_id: str = Field(pattern=r"^jya_[0-9a-f]{24}$")
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_token: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def interpretation_matches_status(self) -> "JaiminiCompletedResult":
        if self.interpretation_status == "unavailable" and self.interpretation is not None:
            raise ValueError("unavailable interpretation cannot contain rendering")
        return self


class JaiminiNeedsInputResult(_JaiminiIdentityBase):
    status: Literal["needs_input"]
    next_action: Literal["provide_birth_range", "confirm_birth_time", "correct_request"]
    error_code: Literal["INPUT_INVALID", "BIRTH_TIME_RANGE_REQUIRED"] | None = None
    stage: str | None = Field(default=None, min_length=1, max_length=80)
    retryable: bool | None = None
    problem: str | None = Field(default=None, min_length=1, max_length=500)
    cause: str | None = Field(default=None, min_length=1, max_length=500)
    fix: str | None = Field(default=None, min_length=1, max_length=500)
    warnings: tuple[str, ...] = ()
    limitations: tuple[JaiminiLimitation, ...] = ()
    interpretation_status: Literal["unavailable"] = "unavailable"
    provenance: JaiminiProvenance | None = None


class JaiminiUnavailableResult(_JaiminiResultBase):
    status: Literal["unavailable"]
    next_action: Literal["inspect_source_status"]


class JaiminiIncompleteResult(_JaiminiResultBase):
    status: Literal["incomplete"]
    next_action: Literal[
        "retry_calculation", "narrow_request", "adjudicate_karaka_tie"
    ]


JaiminiResult = Annotated[
    JaiminiCompletedResult
    | JaiminiNeedsInputResult
    | JaiminiUnavailableResult
    | JaiminiIncompleteResult,
    Field(discriminator="status"),
]


class JaiminiResultModel(RootModel[JaiminiResult]):
    """Concrete MCP-serializable root model preserving the result discriminator."""


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


class RasiDrishtiRules(_FrozenStrictModel):
    variant: Literal["modal_sign_aspects"]
    movable: Literal["non_adjacent_fixed"]
    fixed: Literal["non_adjacent_movable"]
    dual: Literal["other_dual"]


class ArgalaRules(_FrozenStrictModel):
    contributing_houses: tuple[Literal[2], Literal[4], Literal[11], Literal[5]]
    obstruction_pairs: tuple[
        tuple[Literal[2], Literal[12]],
        tuple[Literal[4], Literal[10]],
        tuple[Literal[11], Literal[3]],
        tuple[Literal[5], Literal[9]],
    ]
    obstruction_rule: Literal["count_comparison"]
    empty_status: Literal["absent"]
    zero_obstructors_status: Literal["unobstructed"]
    fewer_obstructors_status: Literal["partial"]
    equal_or_more_obstructors_status: Literal["obstructed"]


class SvamsaRules(_FrozenStrictModel):
    svamsa: Literal["d9_lagna_sign"]
    karakamsa: Literal["d9_atmakaraka_sign"]


class SpecialLagnaRates(_FrozenStrictModel):
    bhava_lagna: Literal[120]
    hora_lagna: Literal[60]
    ghati_lagna: Literal[24]


class SpecialLagnaRules(_FrozenStrictModel):
    included: tuple[
        Literal["bhava_lagna"], Literal["hora_lagna"], Literal["ghati_lagna"]
    ]
    anchor: Literal["sun_longitude_at_sunrise"]
    elapsed: Literal["minutes_since_sunrise"]
    rates_minutes_per_sign: SpecialLagnaRates
    wrap: Literal["modulo_360"]


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
    rasi_drishti: RasiDrishtiRules
    argala: ArgalaRules
    svamsa: SvamsaRules
    special_lagnas: SpecialLagnaRules
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
        if self.status == "approved" and (not self.reviewer or not self.reviewer_role):
            raise ValueError("approved review metadata requires reviewer identity and role")
        return self


class RuleSourceMapping(_FrozenStrictModel):
    rule_id: str
    school: str
    fragment_id: str | None = Field(default=None, pattern=r"^sf_[a-z0-9_]+$")
    fragment_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
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
    interpretation_status: InterpretationStatus
    review: ReviewMetadata
    rules: tuple[RuleSourceMapping, ...]

    @model_validator(mode="after")
    def approved_gate_binds_every_rule(self) -> "JaiminiSourceMap":
        every_rule_approved = bool(self.rules) and all(
            rule.source_status == "approved" for rule in self.rules
        )
        if self.review.status == "approved" and not every_rule_approved:
            raise ValueError("approved source review requires every rule to be approved and bound")
        if self.interpretation_status == "available" and (
            self.review.status != "approved" or not every_rule_approved
        ):
            raise ValueError("available interpretation requires an approved, fully bound source map")
        return self


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
