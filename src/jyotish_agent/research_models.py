"""Strict Pydantic v2 boundary models for persisted research runs."""

from __future__ import annotations

import datetime as dt
import re
import uuid
from typing import Annotated, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import BirthTimeConfidence, CalculationConfigRequest

_ID_RE = re.compile(r"^op_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_RUN_ID_RE = re.compile(r"^rr_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_CLAIM_ID_PATTERN = r"^cl_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
NumericLegacyOffset = Annotated[
    float,
    Field(ge=-12, le=14, allow_inf_nan=False),
]


class FixedOffsetLegacy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["fixed_offset_legacy"]
    offset_hours: float = Field(ge=-12, le=14, allow_inf_nan=False)


class IanaTimezone(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["iana"]
    zone_id: str = Field(min_length=1, max_length=100)
    fold: Literal[0, 1] | None = None


class IanaWithAssertedOffset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["iana_with_asserted_offset"]
    zone_id: str = Field(min_length=1, max_length=100)
    asserted_offset_hours: float = Field(ge=-12, le=14, allow_inf_nan=False)
    fold: Literal[0, 1] | None = None


TimezoneSpec = Annotated[
    FixedOffsetLegacy | IanaTimezone | IanaWithAssertedOffset,
    Field(discriminator="kind"),
]


class ResearchPlace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timezone: NumericLegacyOffset | TimezoneSpec


class ResearchBirthProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    date: dt.date
    time: dt.time
    place: ResearchPlace
    birth_time_confidence: BirthTimeConfidence = BirthTimeConfidence.exact
    birth_time_range: tuple[dt.time, dt.time] | None = None

    @model_validator(mode="after")
    def unknown_time_requires_bounded_range(self):
        if self.birth_time_confidence == BirthTimeConfidence.unknown:
            if self.birth_time_range is None:
                raise ValueError("unknown birth time requires an explicit bounded birth_time_range")
            start, end = self.birth_time_range
            if start.tzinfo or end.tzinfo or start >= end:
                raise ValueError("birth_time_range must be an ordered same-day civil range")
            if not start <= self.time <= end:
                raise ValueError("birth time must fall within birth_time_range")
            span = (dt.datetime.combine(self.date, end) - dt.datetime.combine(self.date, start))
            if span > dt.timedelta(hours=6):
                raise ValueError("birth_time_range must not exceed six hours")
        elif self.birth_time_range is not None:
            raise ValueError("birth_time_range is valid only when birth_time_confidence is unknown")
        return self

    @field_validator("date")
    @classmethod
    def supported_year(cls, value: dt.date) -> dt.date:
        if not 1800 <= value.year <= 2200:
            raise ValueError("year must be between 1800 and 2200")
        return value

    @field_validator("time")
    @classmethod
    def civil_time_has_no_embedded_offset(cls, value: dt.time) -> dt.time:
        if value.tzinfo is not None:
            raise ValueError("civil birth time must not include a UTC offset")
        return value


class CreateResearchRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str | None = None
    operation_id: str
    expected_revision: int = Field(default=0, ge=0)
    question: str = Field(min_length=1, max_length=10_000)
    birth_profile: ResearchBirthProfileRequest
    calculation_config: CalculationConfigRequest = Field(
        default_factory=CalculationConfigRequest
    )
    model_version: str = Field(min_length=1, max_length=200)
    planner_version: str = Field(min_length=1, max_length=200)
    corpus_version: str = Field(min_length=1, max_length=200)
    contract_version: str = Field(default="2.0", min_length=1, max_length=50)

    @field_validator("operation_id")
    @classmethod
    def valid_operation_id(cls, value: str) -> str:
        if not _ID_RE.fullmatch(value):
            raise ValueError("operation_id must be an op_ prefixed UUID4")
        return value

    @field_validator("run_id")
    @classmethod
    def valid_run_id(cls, value: str | None) -> str | None:
        if value is not None and not _RUN_ID_RE.fullmatch(value):
            raise ValueError("run_id must be an rr_ prefixed UUID4")
        return value


class ResearchOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str
    expected_revision: int = Field(ge=1)

    @field_validator("operation_id")
    @classmethod
    def valid_operation_id(cls, value: str) -> str:
        if not _ID_RE.fullmatch(value):
            raise ValueError("operation_id must be an op_ prefixed UUID4")
        return value


class ResearchOperationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    operation_id: str
    revision: int
    backend_seq: int
    event_hash: str
    status: str


QuestionIntentFamily = Literal[
    "career_factors_and_timing", "unknown", "composite", "unsupported"
]


class QuestionIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    family: QuestionIntentFamily
    explicit_annual_scope: bool = False

    @field_validator("explicit_annual_scope")
    @classmethod
    def annual_scope_requires_supported_family(cls, value: bool, info):
        family = info.data.get("family")
        if value and family != "career_factors_and_timing":
            raise ValueError("annual scope is valid only for the supported career family")
        return value


class ClassifierMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)
    classifier_model: str = Field(
        min_length=1,
        max_length=200,
        validation_alias=AliasChoices("classifier_model", "model"),
    )
    classifier_version: str = Field(
        min_length=1,
        max_length=200,
        validation_alias=AliasChoices("classifier_version", "version"),
    )
    prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class QuestionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    outcome: Literal["supported", "needs_clarification", "unsupported"]
    family: Literal["career_factors_and_timing"] | None
    explicit_annual_scope: bool
    charts: tuple[Literal["D1", "D9", "D10"], ...]
    modules: tuple[
        Literal["shadbala", "transits", "ashtakavarga", "varshaphal"], ...
    ]
    fact_paths: tuple[str, ...] = ()


class PlanResearchRunRequest(ResearchOperationRequest):
    intent: QuestionIntent
    classifier: ClassifierMetadata


class ResearchPlanResponse(ResearchOperationResponse):
    intent: QuestionIntent
    classifier: ClassifierMetadata
    plan: QuestionPlan
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class RetrieveResearchRunRequest(ResearchOperationRequest):
    query: str = Field(min_length=1, max_length=2_000)
    limit: int = Field(default=8, ge=1, le=50)


SourceClass = Literal[
    "original_text", "translation", "commentary", "modern_secondary"
]
ReviewStatus = Literal["pending", "approved", "rejected", "quarantined"]


class CorpusOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str
    expected_revision: int = Field(ge=0)

    @field_validator("operation_id")
    @classmethod
    def valid_operation_id(cls, value: str) -> str:
        if not _ID_RE.fullmatch(value):
            raise ValueError("operation_id must be an op_ prefixed UUID4")
        return value


class CorpusSourceIngest(CorpusOperationRequest):
    model_config = ConfigDict(extra="forbid")
    source_version_id: str = Field(pattern=r"^sv_[a-z0-9][a-z0-9_.-]{2,127}$")
    work_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,99}$")
    title: str = Field(min_length=1, max_length=500)
    source_class: SourceClass
    language: str = Field(min_length=2, max_length=50)
    edition: str = Field(min_length=1, max_length=1_000)
    provenance_url: str = Field(min_length=1, max_length=2_000)
    rights_note: str = Field(min_length=1, max_length=4_000)
    manifest_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")


class CorpusFragmentIngest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fragment_id: str = Field(pattern=r"^sf_[a-z0-9][a-z0-9_.-]{2,127}$")
    ordinal: int = Field(ge=1)
    locator: str = Field(min_length=1, max_length=1_000)
    text: str = Field(min_length=1, max_length=50_000)
    transliteration_aliases: list[str] = Field(default_factory=list, max_length=50)
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")


class CorpusFragmentsIngestRequest(CorpusOperationRequest):
    fragments: list[CorpusFragmentIngest] = Field(min_length=1, max_length=500)


class CorpusReviewRequest(CorpusOperationRequest):
    status: Literal["approved", "rejected", "quarantined"]
    reviewer: str = Field(min_length=1, max_length=200)
    note: str = Field(min_length=1, max_length=2_000)


class CorpusSourceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str
    source_version_id: str
    work_id: str
    title: str
    source_class: SourceClass
    language: str
    edition: str
    provenance_url: str
    rights_note: str
    manifest_checksum: str
    manifest_checksum_original: str | None = None
    manifest_reconciliation_note: str | None = None
    approval_status: ReviewStatus
    revision: int = Field(ge=1)
    reviewed_by: str | None
    review_note: str | None
    reviewed_at: str | None
    created_at: str
    updated_at: str


class CorpusFragmentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str | None = None
    fragment_id: str
    source_version_id: str
    ordinal: int = Field(ge=1)
    locator: str
    text: str
    transliteration_aliases: list[str]
    checksum: str
    approval_status: ReviewStatus
    revision: int = Field(ge=1)
    reviewed_by: str | None
    review_note: str | None
    reviewed_at: str | None
    created_at: str
    updated_at: str


class CorpusFragmentsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str
    source_version_id: str
    revision: int = Field(ge=1)
    fragments: list[CorpusFragmentResponse]


class RetrievedCorpusFragment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    content_role: Literal["quoted_source_data"] = "quoted_source_data"
    evidence_id: str | None = None
    fragment_id: str
    source_version_id: str
    work_id: str
    title: str
    source_class: SourceClass
    locator: str
    quote: str
    checksum: str
    rights_note: str
    provenance_url: str
    source_approval_status: Literal["approved"]
    source_reviewed_by: str
    source_review_note: str
    source_reviewed_at: str
    fragment_approval_status: Literal["approved"]
    fragment_reviewed_by: str
    fragment_review_note: str
    fragment_reviewed_at: str


class ResearchRetrievalResponse(ResearchOperationResponse):
    query: str
    results: list[RetrievedCorpusFragment]


class TimezoneResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    original_civil_datetime: str
    mode: Literal["fixed_offset_legacy", "iana", "iana_with_asserted_offset"]
    zone_id: str | None
    tzdb_fingerprint: str
    resolved_offset_minutes: int
    utc_instant: str
    fold: Literal[0, 1]
    warnings: list[str]


class ResearchRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    revision: int
    status: str
    question: str
    birth_profile: dict
    calculation_config: dict
    reference_date: dt.date
    timezone_resolution: TimezoneResolution
    engine_name: str
    engine_version: str
    model_version: str
    planner_version: str
    corpus_version: str
    contract_version: str
    request_hash: str
    created_at: str
    updated_at: str


class ResearchEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    seq: int
    event_id: str
    operation_id: str | None
    event_type: str
    event_version: int
    schema_version: int
    payload: dict
    payload_hash: str
    previous_event_hash: str | None
    event_hash: str
    producer: str
    producer_version: str
    created_at: str


class ResearchEventsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[ResearchEventResponse]


class ResearchInspectResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run: ResearchRunResponse
    intent: dict | None
    plan: dict | None
    events: list[ResearchEventResponse]
    evidence: list[dict]
    answers: list[dict]


class ResearchScreenResponse(ResearchOperationResponse):
    safe: bool
    category: str | None
    redirect: str | None


class ResearchCalculationResponse(ResearchOperationResponse):
    normalized_input: dict
    calculation_config: dict
    facts: dict
    provenance: dict
    warnings: list[str]
    evidence_ids: list[str]
    sensitivity: list[dict] = Field(default_factory=list)


class ClaimBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_id: str = Field(pattern=_CLAIM_ID_PATTERN)
    materiality: Literal["major", "supporting"]
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    supports: list[str] = Field(min_length=1)
    caveats: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)

    @field_validator("claim_id")
    @classmethod
    def valid_claim_id(cls, value: str) -> str:
        if not value.startswith("cl_"):
            raise ValueError("claim_id must use the cl_ prefix")
        try:
            parsed = uuid.UUID(value[3:])
        except ValueError as exc:
            raise ValueError("claim_id must be a cl_ prefixed UUID4") from exc
        if parsed.version != 4:
            raise ValueError("claim_id must be a cl_ prefixed UUID4")
        return value


class ComputedClaim(ClaimBase):
    claim_type: Literal["computed"]


class SourceClaim(ClaimBase):
    claim_type: Literal["source"]
    text: str = Field(min_length=1, max_length=20_000)


class SynthesisClaim(ClaimBase):
    claim_type: Literal["synthesis"]
    text: str = Field(min_length=1, max_length=20_000)


ClaimV2 = Annotated[
    ComputedClaim | SourceClaim | SynthesisClaim,
    Field(discriminator="claim_type"),
]


class AnswerContractV2(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["2.0"]
    run_status: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=500)
    claims: list[ClaimV2] = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)
    followups: list[str] = Field(default_factory=list)


class SubmitAnswerRequest(ResearchOperationRequest):
    answer: AnswerContractV2


class ResearchAnswerResponse(ResearchOperationResponse):
    valid: bool
    violations: list[str]
    repair_remaining: int
    answer_id: str | None = None
    markdown: str | None = None
    markdown_sha256: str | None = None


class ResearchReplayResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    status: Literal["replayed"]
    offline: Literal[True] = True
    projection_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    claims_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    memo_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    answer_id: str
    source_disagreements: list[dict]
