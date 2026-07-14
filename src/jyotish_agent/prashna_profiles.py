"""Strict, checksum-bound access to immutable Praśna governance data."""

from __future__ import annotations

import hashlib
import json
from importlib import resources
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .corpus import load_builtin_manifest

_DATA = resources.files("jyotish_agent").joinpath("data/prashna")


class PrashnaGovernanceError(RuntimeError):
    """Package governance material is missing, malformed, or hash-inconsistent."""


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class PrashnaRuleDefinition(_Frozen):
    rule_id: str = Field(pattern=r"^prashna\.[A-Za-z0-9_.-]+$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    source_status: Literal["pending", "approved", "not_required"]


class PrashnaRuleProfile(_Frozen):
    profile_id: Literal["prashna_work_v1"]
    version: Literal["1.0.0"]
    school: Literal["bounded-time-chart-calculation-only"]
    lagna_method: Literal["time_chart"]
    question_family: Literal["work_project_status_and_obstacles"]
    primary_house: int = Field(ge=1, le=12)
    secondary_houses: tuple[int, ...] = Field(min_length=1, max_length=4)
    unsupported_lagna_methods: tuple[Literal["kp_249", "kp_108", "nadi"], ...]
    rule_result_limit: int = Field(ge=1, le=100)
    rules: tuple[PrashnaRuleDefinition, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def supported_runtime_rules(self) -> "PrashnaRuleProfile":
        expected = {
            "prashna.readability.anchor_complete",
            "prashna.readability.single_topic",
            "prashna.radicality.source_gate",
            "prashna.geometry.applying_separating",
        }
        if {rule.rule_id for rule in self.rules} != expected:
            raise ValueError("rule profile does not exactly match supported runtime rules")
        if (
            set(self.unsupported_lagna_methods) != {"kp_249", "kp_108", "nadi"}
            or len(self.unsupported_lagna_methods) != 3
        ):
            raise ValueError("unsupported lagna methods must be complete and unique")
        if (
            any(not 1 <= house <= 12 for house in self.secondary_houses)
            or len(set(self.secondary_houses)) != len(self.secondary_houses)
            or self.primary_house in self.secondary_houses
        ):
            raise ValueError("primary and secondary house routing is invalid")
        return self


class PrashnaReview(_Frozen):
    status: Literal["pending", "approved", "rejected"]
    reviewer: str | None = None
    reviewer_role: str | None = None
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def approved_review_is_named(self) -> "PrashnaReview":
        if self.status == "approved" and not (self.reviewer and self.reviewer_role):
            raise ValueError("approved review requires reviewer identity and role")
        return self


class PrashnaSourceRule(_Frozen):
    rule_id: str = Field(pattern=r"^prashna\.[A-Za-z0-9_.-]+$")
    source_status: Literal["approved"]
    fragment_id: str
    fragment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PrashnaSourceMap(_Frozen):
    profile_id: Literal["prashna_work_v1"]
    rule_profile_version: Literal["1.0.0"]
    rule_profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    adjudication_fixtures_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    interpretation_status: Literal["available", "unavailable"]
    review: PrashnaReview
    rules: tuple[PrashnaSourceRule, ...]

    @model_validator(mode="after")
    def interpretation_gate_is_consistent(self) -> "PrashnaSourceMap":
        if self.interpretation_status == "available" and (
            self.review.status != "approved" or not self.rules
        ):
            raise ValueError("available interpretation requires approved review and mappings")
        if len({rule.rule_id for rule in self.rules}) != len(self.rules):
            raise ValueError("source rule mappings must be unique")
        return self


class PrashnaAdjudicationCase(_Frozen):
    case_id: str = Field(min_length=1, max_length=100)
    family: str = Field(min_length=1, max_length=100)
    zone_id: str = Field(min_length=1, max_length=100)
    anchor_kind: str = Field(min_length=1, max_length=100)
    review_status: Literal["pending", "approved", "rejected"]


class PrashnaAdjudicationFixtures(_Frozen):
    gate_status: Literal["pending", "approved", "rejected"]
    reviewer: str | None = None
    reviewer_role: str | None = None
    reason: str = Field(min_length=1, max_length=500)
    cases: tuple[PrashnaAdjudicationCase, ...] = Field(min_length=5, max_length=5)


def _bytes(name: str) -> bytes:
    try:
        return _DATA.joinpath(name).read_bytes()
    except (FileNotFoundError, OSError) as exc:
        raise PrashnaGovernanceError("PRASHNA_GOVERNANCE_MATERIAL_MISSING") from exc


def _json(name: str) -> object:
    try:
        return json.loads(_bytes(name))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PrashnaGovernanceError("PRASHNA_GOVERNANCE_JSON_INVALID") from exc


def _sha256(name: str) -> str:
    return hashlib.sha256(_bytes(name)).hexdigest()


def prashna_rule_profile_sha256() -> str:
    return _sha256("prashna_work_v1.json")


def prashna_source_map_sha256() -> str:
    return _sha256("prashna_work_v1_sources.json")


def prashna_adjudication_fixtures_sha256() -> str:
    return _sha256("adjudication_fixtures_v1.json")


def load_prashna_rule_profile() -> PrashnaRuleProfile:
    try:
        profile = PrashnaRuleProfile.model_validate(_json("prashna_work_v1.json"))
    except ValidationError as exc:
        raise PrashnaGovernanceError("PRASHNA_RULE_PROFILE_INVALID") from exc
    ids = [rule.rule_id for rule in profile.rules]
    if len(ids) != len(set(ids)):
        raise PrashnaGovernanceError("PRASHNA_RULE_PROFILE_DUPLICATE_RULE")
    return profile


def load_prashna_source_map() -> PrashnaSourceMap:
    try:
        value = PrashnaSourceMap.model_validate(_json("prashna_work_v1_sources.json"))
    except ValidationError as exc:
        raise PrashnaGovernanceError("PRASHNA_SOURCE_MAP_INVALID") from exc
    if value.rule_profile_sha256 != prashna_rule_profile_sha256():
        raise PrashnaGovernanceError("PRASHNA_RULE_PROFILE_HASH_MISMATCH")
    if value.adjudication_fixtures_sha256 != prashna_adjudication_fixtures_sha256():
        raise PrashnaGovernanceError("PRASHNA_ADJUDICATION_HASH_MISMATCH")
    return value


def load_prashna_adjudication_fixtures() -> PrashnaAdjudicationFixtures:
    try:
        value = PrashnaAdjudicationFixtures.model_validate(
            _json("adjudication_fixtures_v1.json")
        )
    except ValidationError as exc:
        raise PrashnaGovernanceError("PRASHNA_ADJUDICATION_FIXTURES_INVALID") from exc
    if value.gate_status == "approved" and not (
        value.reviewer
        and value.reviewer_role
        and all(case.review_status == "approved" for case in value.cases)
    ):
        raise PrashnaGovernanceError("PRASHNA_ADJUDICATION_APPROVAL_INVALID")
    return value


def prashna_source_admission_evidence() -> dict:
    """Verify every future approved doctrine mapping against governed corpus bytes."""
    profile = load_prashna_rule_profile()
    source_map = load_prashna_source_map()
    fixtures = load_prashna_adjudication_fixtures()
    admitted: dict[str, dict[str, str]] = {}
    for source in load_builtin_manifest()["sources"]:
        review = source.get("review", {})
        if review.get("status") != "approved":
            continue
        if not source.get("rights_note") or not source.get("provenance_url"):
            continue
        if not review.get("reviewer") or not review.get("reviewer_role"):
            continue
        for fragment in source.get("fragments", []):
            admitted[fragment["fragment_id"]] = {
                "fragment_sha256": fragment["checksum"],
                "source_version_id": source["source_version_id"],
                "manifest_checksum": source["manifest_checksum"],
                "rights_note_sha256": hashlib.sha256(source["rights_note"].encode()).hexdigest(),
                "provenance_url": source["provenance_url"],
                "source_reviewer": review["reviewer"],
                "source_reviewer_role": review["reviewer_role"],
            }
    doctrinal_rules = {rule.rule_id for rule in profile.rules if rule.source_status != "not_required"}
    mappings = {rule.rule_id: rule for rule in source_map.rules}
    verified = bool(
        source_map.interpretation_status == "available"
        and source_map.review.status == "approved"
        and source_map.review.reviewer
        and source_map.review.reviewer_role
        and fixtures.gate_status == "approved"
        and fixtures.reviewer
        and fixtures.reviewer_role
        and all(case.review_status == "approved" for case in fixtures.cases)
        and doctrinal_rules
        and doctrinal_rules == set(mappings)
        and all(
            mapping.fragment_id in admitted
            and mapping.fragment_sha256 == admitted[mapping.fragment_id]["fragment_sha256"]
            for mapping in mappings.values()
        )
    )
    rule_sources = {
        rule_id: {"fragment_id": mapping.fragment_id, **admitted[mapping.fragment_id]}
        for rule_id, mapping in mappings.items()
    } if verified else {}
    payload = {
        "verified": verified,
        "rule_profile_sha256": prashna_rule_profile_sha256(),
        "source_map_sha256": prashna_source_map_sha256(),
        "adjudication_fixtures_sha256": prashna_adjudication_fixtures_sha256(),
        "rule_sources": rule_sources,
    }
    payload["sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return payload
