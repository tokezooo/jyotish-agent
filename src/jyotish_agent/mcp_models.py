"""Strict structured boundaries for the Codex-native Jyotish MCP."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .research_models import ResearchBirthProfileRequest


ProfileMode = Literal["default", "inline"]
AllowedChart = Literal["D1", "D2", "D3", "D7", "D9", "D10", "D12"]
AllowedModule = Literal["shadbala", "ashtakavarga", "transits", "varshaphal"]


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
    charts: list[AllowedChart] = Field(default_factory=lambda: ["D1", "D9"], min_length=1, max_length=7)
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
