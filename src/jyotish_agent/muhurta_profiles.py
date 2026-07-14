"""Checksum-bound Muhūrta governance material; doctrinal admission is fail-closed."""

from __future__ import annotations

import hashlib
import json
from importlib import resources
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


_DATA = resources.files("jyotish_agent").joinpath("data/muhurta")


class MuhurtaGovernanceError(RuntimeError):
    pass


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class MuhurtaRuleDefinition(_Frozen):
    rule_id: str = Field(pattern=r"^muhurta\.[A-Za-z0-9_.-]+$")
    classification: Literal["hard", "soft"]
    source_status: Literal["pending", "approved", "not_required"]
    weight: int | None


class MuhurtaRuleProfile(_Frozen):
    profile_id: Literal["muhurta_focused_work_v1"]
    version: Literal["1.0.0"]
    school: Literal["calculation-only-source-pending"]
    activities: tuple[Literal["general", "focused_work_session_v1"], ...]
    max_range_days: Literal[31]
    default_range_days: Literal[7]
    max_candidates: Literal[5000]
    default_result_limit: Literal[5]
    rules: tuple[MuhurtaRuleDefinition, ...] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def exact_runtime_contract(self) -> "MuhurtaRuleProfile":
        expected = {
            "muhurta.constraints.explicit",
            "muhurta.boundary.event_duration",
            "muhurta.general.doctrinal_eligibility",
            "muhurta.focused_work.preference",
        }
        if set(self.activities) != {"general", "focused_work_session_v1"} or {r.rule_id for r in self.rules} != expected:
            raise ValueError("profile does not exactly match the bounded runtime")
        for rule in self.rules:
            if rule.source_status == "pending" and rule.rule_id.startswith("muhurta.constraints"):
                raise ValueError("explicit constraints do not require doctrine")
            if rule.classification == "hard" and rule.weight is not None:
                raise ValueError("hard rules cannot carry soft weights")
        return self


class MuhurtaReview(_Frozen):
    status: Literal["pending", "approved", "rejected"]
    reviewer: str | None = None
    reviewer_role: str | None = None
    reason: str

    @model_validator(mode="after")
    def approval_named(self) -> "MuhurtaReview":
        if self.status == "approved" and not (self.reviewer and self.reviewer_role):
            raise ValueError("approved review requires named reviewer and role")
        return self


class MuhurtaSourceRule(_Frozen):
    rule_id: str
    source_status: Literal["approved"]
    fragment_id: str
    fragment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class MuhurtaSourceMap(_Frozen):
    profile_id: Literal["muhurta_focused_work_v1"]
    rule_profile_version: Literal["1.0.0"]
    rule_profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    adjudication_fixtures_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    interpretation_status: Literal["available", "unavailable"]
    review: MuhurtaReview
    rules: tuple[MuhurtaSourceRule, ...]

    @model_validator(mode="after")
    def fail_closed(self) -> "MuhurtaSourceMap":
        if self.interpretation_status == "available" and (self.review.status != "approved" or not self.rules):
            raise ValueError("available interpretation requires approval and source mappings")
        return self


class MuhurtaAdjudicationCase(_Frozen):
    case_id: str
    criterion: Literal["one_day", "multi_day", "empty", "cancellation", "high_stakes"]
    activity: Literal["general", "focused_work_session_v1", "unsupported"]
    zone_id: str
    review_status: Literal["pending", "approved", "rejected"]


class MuhurtaAdjudicationFixtures(_Frozen):
    gate_status: Literal["pending", "approved", "rejected"]
    reviewer: str | None = None
    reviewer_role: str | None = None
    reason: str
    cases: tuple[MuhurtaAdjudicationCase, ...] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def coverage(self) -> "MuhurtaAdjudicationFixtures":
        if {case.criterion for case in self.cases} != {"one_day", "multi_day", "empty", "cancellation", "high_stakes"}:
            raise ValueError("fixtures do not cover the frozen criteria")
        if len({case.case_id for case in self.cases}) != 5:
            raise ValueError("fixture IDs must be unique")
        for case in self.cases:
            ZoneInfo(case.zone_id)
        if self.gate_status == "approved" and not (self.reviewer and self.reviewer_role and all(c.review_status == "approved" for c in self.cases)):
            raise ValueError("approved fixtures require complete human sign-off")
        return self


def _bytes(name: str) -> bytes:
    try:
        return _DATA.joinpath(name).read_bytes()
    except (OSError, FileNotFoundError) as exc:
        raise MuhurtaGovernanceError("MUHURTA_GOVERNANCE_MATERIAL_MISSING") from exc


def _json(name: str) -> object:
    try:
        return json.loads(_bytes(name))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise MuhurtaGovernanceError("MUHURTA_GOVERNANCE_JSON_INVALID") from exc


def _sha(name: str) -> str:
    return hashlib.sha256(_bytes(name)).hexdigest()


def muhurta_rule_profile_sha256() -> str:
    return _sha("muhurta_focused_work_v1.json")


def muhurta_source_map_sha256() -> str:
    return _sha("muhurta_focused_work_v1_sources.json")


def muhurta_adjudication_fixtures_sha256() -> str:
    return _sha("adjudication_fixtures_v1.json")


def load_muhurta_rule_profile() -> MuhurtaRuleProfile:
    try:
        return MuhurtaRuleProfile.model_validate(_json("muhurta_focused_work_v1.json"))
    except ValidationError as exc:
        raise MuhurtaGovernanceError("MUHURTA_RULE_PROFILE_INVALID") from exc


def load_muhurta_source_map() -> MuhurtaSourceMap:
    try:
        result = MuhurtaSourceMap.model_validate(_json("muhurta_focused_work_v1_sources.json"))
    except ValidationError as exc:
        raise MuhurtaGovernanceError("MUHURTA_SOURCE_MAP_INVALID") from exc
    if result.rule_profile_sha256 != muhurta_rule_profile_sha256() or result.adjudication_fixtures_sha256 != muhurta_adjudication_fixtures_sha256():
        raise MuhurtaGovernanceError("MUHURTA_GOVERNANCE_HASH_MISMATCH")
    return result


def load_muhurta_adjudication_fixtures() -> MuhurtaAdjudicationFixtures:
    try:
        return MuhurtaAdjudicationFixtures.model_validate(_json("adjudication_fixtures_v1.json"))
    except ValidationError as exc:
        raise MuhurtaGovernanceError("MUHURTA_ADJUDICATION_INVALID") from exc


def muhurta_source_admission_evidence() -> dict[str, object]:
    profile, source, fixtures = load_muhurta_rule_profile(), load_muhurta_source_map(), load_muhurta_adjudication_fixtures()
    verified = bool(
        source.review.status == "approved"
        and source.interpretation_status == "available"
        and fixtures.gate_status == "approved"
        and all(rule.source_status == "approved" for rule in source.rules)
    )
    material = {
        "profile_sha256": muhurta_rule_profile_sha256(),
        "source_sha256": muhurta_source_map_sha256(),
        "fixtures_sha256": muhurta_adjudication_fixtures_sha256(),
        "profile": profile.profile_id,
        "review": source.review.status,
        "verified": verified,
    }
    material["sha256"] = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return material
