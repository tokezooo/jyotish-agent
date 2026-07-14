"""Checksum-bound Muhūrta governance material; doctrinal admission is fail-closed."""

from __future__ import annotations

import hashlib
import json
from importlib import resources
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .corpus import load_builtin_manifest


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
    rule_id: str = Field(pattern=r"^muhurta\.[A-Za-z0-9_.-]+$")
    source_status: Literal["approved"]
    fragment_id: str = Field(pattern=r"^sf_[A-Za-z0-9_.-]+$")
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
        doctrinal = {"muhurta.general.doctrinal_eligibility", "muhurta.focused_work.preference"}
        mapped = {rule.rule_id for rule in self.rules}
        if len(mapped) != len(self.rules):
            raise ValueError("source mappings must be unique")
        if self.interpretation_status == "available":
            if self.review.status != "approved" or mapped != doctrinal:
                raise ValueError("available interpretation requires exact doctrinal rule coverage")
        elif self.rules:
            raise ValueError("unavailable source maps cannot carry partially admitted mappings")
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
        expected = {
            "one_day": "focused_work_session_v1", "multi_day": "general",
            "empty": "focused_work_session_v1", "cancellation": "general",
            "high_stakes": "unsupported",
        }
        if {case.criterion for case in self.cases} != set(expected):
            raise ValueError("fixtures do not cover the frozen criteria")
        if len({case.case_id for case in self.cases}) != 5:
            raise ValueError("fixture IDs must be unique")
        for case in self.cases:
            ZoneInfo(case.zone_id)
            if case.activity != expected[case.criterion]:
                raise ValueError("fixture criterion/activity semantics are invalid")
        if len({(case.criterion, case.activity, case.zone_id) for case in self.cases}) != 5:
            raise ValueError("fixture coverage must be meaningful and unique")
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
    admitted: dict[str, dict[str, str]] = {}
    for item in load_builtin_manifest()["sources"]:
        review = item.get("review", {})
        if (
            review.get("status") != "approved" or not review.get("reviewer")
            or not review.get("reviewer_role") or not item.get("rights_note")
            or not item.get("provenance_url") or not item.get("manifest_checksum")
        ):
            continue
        for fragment in item.get("fragments", []):
            admitted[fragment["fragment_id"]] = {
                "checksum": fragment["checksum"],
                "source_version_id": item["source_version_id"],
                "provenance_url": item["provenance_url"],
                "rights_sha256": hashlib.sha256(item["rights_note"].encode()).hexdigest(),
                "reviewer": review["reviewer"],
                "reviewer_role": review["reviewer_role"],
            }
    doctrinal = {rule.rule_id for rule in profile.rules if rule.source_status != "not_required"}
    mappings = {rule.rule_id: rule for rule in source.rules}
    verified = bool(
        source.review.status == "approved"
        and source.interpretation_status == "available"
        and fixtures.gate_status == "approved"
        and fixtures.reviewer and fixtures.reviewer_role
        and all(case.review_status == "approved" for case in fixtures.cases)
        and doctrinal == set(mappings)
        and all(
            mapping.fragment_id in admitted
            and mapping.fragment_sha256 == admitted[mapping.fragment_id]["checksum"]
            for mapping in mappings.values()
        )
    )
    material = {
        "profile_sha256": muhurta_rule_profile_sha256(),
        "source_sha256": muhurta_source_map_sha256(),
        "fixtures_sha256": muhurta_adjudication_fixtures_sha256(),
        "profile": profile.profile_id,
        "review": source.review.status,
        "verified": verified,
        "rule_sources": {
            rule_id: {"fragment_id": mapping.fragment_id, **admitted[mapping.fragment_id]}
            for rule_id, mapping in mappings.items()
        } if verified else {},
    }
    material["sha256"] = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return material
