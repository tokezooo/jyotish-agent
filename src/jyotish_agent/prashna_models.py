"""Strict public contracts for the bounded Praśna work/project vertical."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator

from .event_models import EventAnchor, EventPlace

PrashnaRuleProfileId = Literal["prashna_work_v1"]
RuleStatus = Literal["pass", "warn", "fail", "not_applicable"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class PrashnaRequest(_Strict):
    question: str = Field(min_length=1, max_length=2_000)
    anchor: EventAnchor | None = None
    capture_now: bool = False
    place: EventPlace | None = None
    anchor_token: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    clarification_of_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9._:-]{16,128}$"
    )
    rule_profile: PrashnaRuleProfileId = "prashna_work_v1"
    include_trace: bool = False

    @model_validator(mode="after")
    def anchor_lifecycle(self) -> "PrashnaRequest":
        if self.anchor_token is not None:
            if self.anchor is not None or self.capture_now or self.place is not None or self.idempotency_key is not None:
                raise ValueError("follow-up supplies a token or new anchor, never both")
            return self
        if self.clarification_of_fingerprint is not None:
            raise ValueError("clarification_of_fingerprint requires an anchor token")
        if self.anchor is not None:
            if self.capture_now or self.place is not None or self.idempotency_key is not None:
                raise ValueError("explicit anchor and capture_now are mutually exclusive")
            return self
        if not self.capture_now:
            raise ValueError("a new request requires an anchor or capture_now")
        if self.place is None:
            raise ValueError("capture_now requires an event place")
        if self.idempotency_key is None:
            raise ValueError("capture_now requires an explicit idempotency_key")
        return self


class PrashnaFact(_Frozen):
    fact_id: str = Field(pattern=r"^prashna\.[A-Za-z0-9_.-]+$", max_length=180)
    value: str | int | float | bool | None


class PrashnaRuleResult(_Frozen):
    rule_id: str = Field(pattern=r"^prashna\.[A-Za-z0-9_.-]+$", max_length=180)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    status: RuleStatus
    severity: Literal["info", "warning", "blocking"]
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    source_status: Literal["pending", "approved", "not_required"]
    source_refs: tuple[str, ...] = ()


class PrashnaTruncation(_Frozen):
    truncated: bool
    total_count: int = Field(ge=0)
    returned_count: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def consistent(self) -> "PrashnaTruncation":
        if self.returned_count > self.total_count:
            raise ValueError("returned_count cannot exceed total_count")
        if self.truncated != (self.returned_count < self.total_count):
            raise ValueError("truncation counts are inconsistent")
        return self


class PrashnaProvenance(_Frozen):
    normalized_utc: str
    zone_id: str
    resolved_offset_minutes: int
    fold: Literal[0, 1]
    tzdb_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    engine: Literal["PyJHora"] = "PyJHora"
    engine_version: str | None = None
    ephemeris_mode: Literal["moshier", "swiss"]
    rule_profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_map_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_review_status: Literal["pending", "approved", "rejected"]


class _BaseResult(_Strict):
    request_id: str = Field(pattern=r"^prq_[0-9a-f]{24}$")
    mode: Literal["prashna"] = "prashna"
    rule_profile: PrashnaRuleProfileId = "prashna_work_v1"


class _ErrorResultBase(_BaseResult):
    stage: str = Field(min_length=1, max_length=80)
    retryable: bool
    problem: str = Field(min_length=1, max_length=500)
    cause: str = Field(min_length=1, max_length=500)
    fix: str = Field(min_length=1, max_length=500)


class PrashnaCompletedResult(_BaseResult):
    status: Literal["completed"]
    anchor_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    anchor_summary: str = Field(max_length=200)
    normalized_anchor_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    question_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_question_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    question_relation: Literal["new_anchor", "exact_duplicate", "bounded_clarification"]
    facts: tuple[PrashnaFact, ...]
    rules: tuple[PrashnaRuleResult, ...] = Field(max_length=100)
    truncation: PrashnaTruncation
    interpretation_status: Literal["unavailable"] = "unavailable"
    interpretation: None = None
    limitations: tuple[str, ...]
    provenance: PrashnaProvenance
    artifact_id: str = Field(pattern=r"^jya_[0-9a-f]{24}$")
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    trace: tuple[PrashnaFact, ...] | None = Field(default=None, max_length=100)


class PrashnaNeedsInputResult(_ErrorResultBase):
    status: Literal["needs_input"]
    error_code: Literal["ANCHOR_MISMATCH", "ANCHOR_STALE", "TOPIC_UNSUPPORTED", "TOPIC_COMPOSITE", "IDEMPOTENCY_CONFLICT", "INPUT_INVALID"]
    next_action: Literal["create_new_anchor", "provide_primary_question", "use_new_idempotency_key", "correct_request"]
    supported_values: tuple[str, ...] = ("work_project_status_and_obstacles",)


class PrashnaUnavailableResult(_ErrorResultBase):
    status: Literal["unavailable"]
    error_code: Literal["HIGH_STAKES_TOPIC", "INTERPRETATION_SOURCE_UNAVAILABLE", "GOVERNANCE_INTEGRITY_ERROR"]
    next_action: Literal["consult_qualified_professional", "inspect_source_status"]
    interpretation_status: Literal["unavailable"] = "unavailable"


class PrashnaIncompleteResult(_ErrorResultBase):
    status: Literal["incomplete"]
    error_code: Literal["ENGINE_CROSSCHECK_FAILED"]
    next_action: Literal["retry_calculation"] = "retry_calculation"


PrashnaResult = Annotated[
    PrashnaCompletedResult | PrashnaNeedsInputResult | PrashnaUnavailableResult | PrashnaIncompleteResult,
    Field(discriminator="status"),
]


class PrashnaResultModel(RootModel[PrashnaResult]):
    pass


class PrashnaAnswerClaim(_Frozen):
    claim_type: Literal["computed_fact"]
    path: str = Field(pattern=r"^prashna\.[A-Za-z0-9_.-]+$", max_length=180)
    value: str = Field(max_length=500)
    text: str = Field(max_length=800)


class PrashnaAnswerSubmission(_Strict):
    """Complete facts-only answer boundary; every replay binding is mandatory."""

    artifact_id: str = Field(pattern=r"^jya_[0-9a-f]{24}$")
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    anchor_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_anchor_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    question_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_question_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    question_relation: Literal["new_anchor", "exact_duplicate", "bounded_clarification"]
    claims: tuple[PrashnaAnswerClaim, ...] = Field(min_length=1, max_length=100)
    visible_text: str = Field(max_length=100_000)
