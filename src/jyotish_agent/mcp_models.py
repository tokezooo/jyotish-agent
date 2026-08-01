"""Strict structured boundaries for the Codex-native Jyotish MCP."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .jaimini_models import AnalysisScope, JaiminiRuleProfileId
from .prashna_models import PrashnaRequest
from .muhurta_models import MuhurtaSearchRequest
from .research_models import ResearchBirthProfileRequest


ProfileMode = Literal["default", "inline"]
AllowedChart = Literal["D1", "D2", "D3", "D7", "D9", "D10", "D12"]
AllowedModule = Literal["shadbala", "ashtakavarga", "transits", "varshaphal"]


class ExactJaiminiBirthSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confidence: Literal["exact"]


class ApproximateJaiminiBirthSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confidence: Literal["approximate"]
    earliest_time: dt.time
    latest_time: dt.time

    @model_validator(mode="after")
    def bounded_range(self) -> "ApproximateJaiminiBirthSelection":
        start = dt.datetime.combine(dt.date(2000, 1, 1), self.earliest_time)
        end = dt.datetime.combine(dt.date(2000, 1, 1), self.latest_time)
        seconds = (end - start).total_seconds()
        if seconds <= 0:
            raise ValueError("latest_time must be after earliest_time")
        if seconds > 120 * 60:
            raise ValueError("birth time range must not exceed 120 minutes")
        if seconds % (5 * 60):
            raise ValueError("birth time range must be divisible by 5 minutes")
        return self


JaiminiBirthSelection = Annotated[
    ExactJaiminiBirthSelection | ApproximateJaiminiBirthSelection,
    Field(discriminator="confidence"),
]


class ProfileSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: ProfileMode = "default"
    inline_profile: ResearchBirthProfileRequest | None = None


class ProfileInput(ProfileSelection):
    pass


class ProfileResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["profile"] = "profile"
    source: ProfileMode
    profile: dict[str, Any]


class CalculateInput(ProfileSelection):
    question: str = Field(min_length=1, max_length=2_000)
    charts: list[AllowedChart] = Field(
        default_factory=lambda: ["D1", "D9"], min_length=1, max_length=7
    )
    modules: list[AllowedModule] = Field(default_factory=list, max_length=4)
    reference_date: dt.date | None = None


class CalculateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["quick"] = "quick"
    profile_name: str
    selected_scope: dict[str, Any]
    normalized_input: dict[str, Any]
    facts: dict[str, Any]
    warnings: list[str]
    provenance: dict[str, Any]


class JaiminiMcpInput(ProfileSelection):
    question: str = Field(min_length=1, max_length=2_000)
    birth: JaiminiBirthSelection = Field(
        default_factory=lambda: ExactJaiminiBirthSelection(confidence="exact")
    )
    rule_profile: JaiminiRuleProfileId = "jaimini_core_v1"
    analysis_scope: AnalysisScope = "core_with_chara_dasha"
    gender: Literal["female", "male"] | None = None
    reference_date: dt.date | None = None
    include_trace: bool = False

    @model_validator(mode="after")
    def gender_matches_scope(self) -> "JaiminiMcpInput":
        if self.analysis_scope == "core_with_chara_dasha" and self.gender is None:
            raise ValueError("gender is required for core_with_chara_dasha")
        if self.analysis_scope == "core" and self.gender is not None:
            raise ValueError("gender is not accepted for core geometry")
        return self


class JaiminiFullMcpInput(ProfileSelection):
    question: str = Field(min_length=1, max_length=2_000)
    birth: JaiminiBirthSelection = Field(
        default_factory=lambda: ExactJaiminiBirthSelection(confidence="exact")
    )
    mode: Literal["quick", "full", "deep", "inspection"] = "full"
    locale: Literal["ru", "en"] = "ru"
    topics: list[Literal["self", "career", "relationships", "timing"]] = Field(
        default_factory=lambda: ["self", "career", "relationships", "timing"],
        min_length=1,
        max_length=4,
    )
    include_evidence: bool = False

    @model_validator(mode="after")
    def _inspection_owns_evidence(self) -> "JaiminiFullMcpInput":
        if len(self.topics) != len(set(self.topics)):
            raise ValueError("topics must be unique")
        if self.include_evidence and self.mode != "inspection":
            raise ValueError("include_evidence is available only in inspection mode")
        return self


class JaiminiFullReleaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    surface: Literal["experimental_full"] = "experimental_full"
    status: Literal["completed", "unavailable", "needs_input", "incomplete"]
    request_mode: Literal["quick", "full", "deep", "inspection"] | None = None
    locale: Literal["ru", "en"] | None = None
    topics: list[Literal["self", "career", "relationships", "timing"]] = Field(
        default_factory=list
    )
    profile: Literal["full_jaimini_private_baseline_v1"] | None = None
    admission_state: Literal["blocked_sources", "experimental_full"] | None = None
    blockers: list[str] = Field(default_factory=list)
    public_release_blockers: list[str] = Field(default_factory=list)
    external_review_missing: bool
    report: dict[str, Any] | None = None
    error_code: str | None = None

    @model_validator(mode="after")
    def _status_contract(self) -> "JaiminiFullReleaseResult":
        if self.status == "completed":
            if (
                self.admission_state != "experimental_full"
                or self.profile is None
                or self.report is None
                or self.error_code is not None
            ):
                raise ValueError("completed release requires a private profile and report")
        elif self.report is not None or self.error_code is None:
            raise ValueError("non-success release requires a sanitized error")
        if self.status == "needs_input" and self.error_code == "INPUT_INVALID":
            if self.admission_state is not None or self.profile is not None:
                raise ValueError("malformed input cannot claim an admitted profile")
        return self


class PrashnaMcpInput(PrashnaRequest):
    """Additive MCP input; intentionally independent from natal profiles."""


class PrashnaFullMcpInput(PrashnaRequest):
    """Governed Full Prashna request over the existing sealed-anchor contract."""

    mode: Literal["quick", "full", "deep", "inspection"] = "full"
    locale: Literal["ru", "en"] = "ru"
    include_evidence: bool = False

    @model_validator(mode="after")
    def _inspection_owns_evidence(self) -> "PrashnaFullMcpInput":
        if self.include_evidence and self.mode != "inspection":
            raise ValueError("include_evidence is available only in inspection mode")
        return self


class PrashnaFullReleaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    surface: Literal["experimental_full"] = "experimental_full"
    status: Literal["completed", "unavailable", "needs_input", "incomplete"]
    request_mode: Literal["quick", "full", "deep", "inspection"] | None = None
    locale: Literal["ru", "en"] | None = None
    profile: Literal[
        "work_project_status",
        "communication_contact",
        "lost_object",
        "general_low_risk_outcome",
    ] | None = None
    admission_state: Literal["blocked_sources", "experimental_full"] | None = None
    blockers: list[str] = Field(default_factory=list)
    external_review_missing: bool
    report: dict[str, Any] | None = None
    error_code: str | None = None

    @model_validator(mode="after")
    def _status_contract(self) -> "PrashnaFullReleaseResult":
        if self.status == "completed":
            if (
                self.admission_state != "experimental_full"
                or self.profile is None
                or self.report is None
                or self.error_code is not None
            ):
                raise ValueError("successful private release requires profile and report")
        elif self.report is not None or self.error_code is None:
            raise ValueError("non-success release requires a sanitized error")
        return self


class MuhurtaMcpInput(MuhurtaSearchRequest):
    """Additive event-search input; it never selects or persists a natal profile."""


class MuhurtaFullMcpInput(MuhurtaSearchRequest):
    """Private source-bound Muhurta request over the existing event-search contract."""

    mode: Literal["quick", "full", "deep", "inspection"] = "full"
    locale: Literal["ru", "en"] = "ru"
    include_evidence: bool = False

    @model_validator(mode="after")
    def _inspection_owns_evidence(self) -> "MuhurtaFullMcpInput":
        if self.include_evidence and self.mode != "inspection":
            raise ValueError("include_evidence is available only in inspection mode")
        return self


class MuhurtaFullReleaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    surface: Literal["experimental_full"] = "experimental_full"
    status: Literal["completed", "no_window", "unavailable", "needs_input", "incomplete"]
    request_mode: Literal["quick", "full", "deep", "inspection"] | None = None
    locale: Literal["ru", "en"] | None = None
    profile: Literal[
        "focused_work",
        "study_learning",
        "creative_production",
        "product_launch_communication",
        "low_risk_travel_planning",
        "general_private_task",
    ] | None = None
    admission_state: Literal["blocked_evaluation", "private_experimental"] | None = None
    public_release_blockers: list[str] = Field(default_factory=list)
    external_review_missing: bool
    report: dict[str, Any] | None = None
    error_code: str | None = None

    @model_validator(mode="after")
    def _status_contract(self) -> "MuhurtaFullReleaseResult":
        if self.status in {"completed", "no_window"}:
            if (
                self.admission_state != "private_experimental"
                or self.profile is None
                or self.report is None
                or self.error_code is not None
            ):
                raise ValueError("successful private release requires profile and report")
        elif self.report is not None or self.error_code is None:
            raise ValueError("non-success release requires a sanitized error")
        return self


class SourceSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=2_000)
    limit: int = Field(default=8, ge=1, le=20)


class SourceSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["quick"] = "quick"
    query: str
    results: list[dict[str, Any]]


class ResearchInput(ProfileSelection):
    question: str = Field(min_length=1, max_length=10_000)
    reference_date: dt.date | None = None
    explicit_annual_scope: bool = False
    retrieval_query: str | None = Field(default=None, min_length=1, max_length=2_000)
    source_limit: int = Field(default=8, ge=1, le=20)
    model_version: str = Field(default="codex", min_length=1, max_length=200)


class ResearchBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["deep"] = "deep"
    run_id: str
    revision: int
    status: str
    safe: bool
    redirect: str | None = None
    plan: dict[str, Any] | None = None
    facts: dict[str, Any] | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class FindingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=20_000)
    supports: list[str] = Field(min_length=1, max_length=50)
    materiality: Literal["major", "supporting"] = "supporting"
    confidence: float = Field(default=0.7, ge=0, le=1, allow_inf_nan=False)
    caveats: list[str] = Field(default_factory=list, max_length=20)


class FinalizeResearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(pattern=r"^rr_[0-9a-f-]{36}$")
    expected_revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=500)
    findings: list[FindingInput] = Field(min_length=1, max_length=50)
    limitations: list[str] = Field(default_factory=list, max_length=50)
    followups: list[str] = Field(default_factory=list, max_length=20)


class FinalizedResearch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["deep"] = "deep"
    run_id: str
    revision: int
    status: str
    valid: bool
    violations: list[str]
    answer_id: str | None = None
    markdown: str | None = None
    markdown_sha256: str | None = None


class InspectResearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(pattern=r"^rr_[0-9a-f-]{36}$")
    include_provenance: bool = False
    replay: bool = False


class ResearchInspection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["inspection"] = "inspection"
    run_id: str
    status: str
    revision: int
    title: str | None = None
    answer: str | None = None
    limitations: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] | None = None
    events: list[dict[str, Any]] | None = None
    claims: list[dict[str, Any]] | None = None
    hashes: dict[str, str] | None = None
