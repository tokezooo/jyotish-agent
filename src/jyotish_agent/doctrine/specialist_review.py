"""Content-addressed specialist-review handoff for the Muhurta baseline."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from importlib import resources
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from ..research_store import canonical_json
from .models import FrozenModel
from .muhurta_pack import (
    load_muhurta_admitted_rule_pack,
    load_muhurta_profile_catalog,
    muhurta_compiled_profile_sha256,
)
from .sources import Sha256, SourceId, SourceManifest


ReviewerName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=2, max_length=120),
]
QualificationNote = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=500),
]


class MuhurtaReviewQuestion(StrEnum):
    SOURCE_ALIGNMENT = "source_alignment"
    RULE_SEMANTICS = "rule_semantics"
    EXCEPTIONS_AND_SCOPE = "exceptions_and_scope"
    PROFILE_APPLICABILITY = "profile_applicability"
    RULE_COMPLETENESS = "rule_completeness"
    SAFETY_BOUNDARY = "safety_boundary"


class MuhurtaReviewerRole(StrEnum):
    ELECTIONAL_ASTROLOGY_SPECIALIST = "electional_astrology_specialist"
    JYOTISH_PRACTITIONER = "jyotish_practitioner"
    SANSKRIT_JYOTISH_SPECIALIST = "sanskrit_jyotish_specialist"


class MuhurtaReviewSubject(FrozenModel):
    subject_type: Literal["rule", "profile"]
    subject_id: str = Field(
        pattern=r"^(?:muhurta\.[A-Za-z0-9_.-]+|profile:[a-z][a-z0-9_]+)$"
    )
    current_status: Literal["private_experimental", "available"]
    rule_ids: tuple[str, ...] = Field(min_length=1)
    source_ids: tuple[SourceId, ...] = Field(min_length=1)
    source_locators: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    review_questions: tuple[MuhurtaReviewQuestion, ...] = Field(min_length=1)
    artifact_sha256: Sha256
    subject_sha256: Sha256

    @field_validator(
        "rule_ids",
        "source_ids",
        "source_locators",
        "evidence_refs",
        "review_questions",
    )
    @classmethod
    def _unique_values(cls, value: tuple[object, ...]) -> tuple[object, ...]:
        if len(value) != len(set(value)):
            raise ValueError("review subject values must be unique")
        return value

    @model_validator(mode="after")
    def _content_addressed_and_safe(self) -> "MuhurtaReviewSubject":
        if self.subject_type == "rule" and not self.subject_id.startswith("muhurta."):
            raise ValueError("rule review subject has an invalid ID")
        if self.subject_type == "profile" and not self.subject_id.startswith("profile:"):
            raise ValueError("profile review subject has an invalid ID")
        if any(
            ref.startswith(("/", "private_sources/"))
            or "\\" in ref
            or ".." in ref.split("/")
            for ref in self.evidence_refs
        ):
            raise ValueError("review evidence refs must be safe repository paths")
        payload = self.model_dump(mode="json", exclude={"subject_sha256"})
        if self.subject_sha256 != _hash_payload(payload):
            raise ValueError("review subject identity is not content-addressed")
        return self


class MuhurtaSpecialistReviewHandoff(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    handoff_id: Literal["muhurta_classical_baseline_specialist_v1"]
    release_id: Literal["expanded_muhurta_v1"]
    scope: Literal["classical_baseline_v1_private_experimental"]
    source_manifest_sha256: Sha256
    compiled_profile_sha256: Sha256
    profile_catalog_sha256: Sha256
    admitted_rule_pack_sha256: Sha256
    response_schema_ref: Literal[
        "docs/evidence/doctrine/muhurta-specialist-review-response.schema.json"
    ]
    response_schema_sha256: Sha256
    subject_count: Literal[8]
    subjects: tuple[MuhurtaReviewSubject, ...] = Field(min_length=8, max_length=8)
    decision_options: tuple[Literal["approved", "amended", "rejected"], ...]
    review_requirements: tuple[str, ...] = Field(min_length=1)
    excluded_scope: tuple[str, ...] = Field(min_length=1)
    external_review_status: Literal["missing"]
    ready_for_external_review: Literal[True]
    privacy_projection: Literal["metadata_hashes_and_locators_only"]
    handoff_sha256: Sha256

    @model_validator(mode="after")
    def _complete_and_content_addressed(self) -> "MuhurtaSpecialistReviewHandoff":
        ids = [subject.subject_id for subject in self.subjects]
        if len(ids) != len(set(ids)):
            raise ValueError("specialist handoff subject IDs must be unique")
        if sum(subject.subject_type == "rule" for subject in self.subjects) != 2:
            raise ValueError("specialist handoff requires exactly two admitted rules")
        if sum(subject.subject_type == "profile" for subject in self.subjects) != 6:
            raise ValueError("specialist handoff requires exactly six activity profiles")
        if tuple(self.subjects) != tuple(sorted(self.subjects, key=_subject_sort_key)):
            raise ValueError("specialist handoff subjects must use deterministic order")
        if self.decision_options != ("approved", "amended", "rejected"):
            raise ValueError("specialist handoff decision options drifted")
        expected_schema_sha256 = _hash_payload(
            muhurta_specialist_review_response_schema()
        )
        if self.response_schema_sha256 != expected_schema_sha256:
            raise ValueError("specialist response schema identity drifted")
        payload = self.model_dump(mode="json", exclude={"handoff_sha256"})
        if self.handoff_sha256 != _hash_payload(payload):
            raise ValueError("specialist handoff identity is not content-addressed")
        return self


class MuhurtaSpecialistDecision(FrozenModel):
    subject_type: Literal["rule", "profile"]
    subject_id: str = Field(
        pattern=r"^(?:muhurta\.[A-Za-z0-9_.-]+|profile:[a-z][a-z0-9_]+)$"
    )
    subject_sha256: Sha256
    decision: Literal["approved", "amended", "rejected"]
    note: str | None = Field(default=None, min_length=3, max_length=1_000)
    amendment_summary: str | None = Field(default=None, min_length=3, max_length=1_000)

    @model_validator(mode="after")
    def _decision_has_required_context(self) -> "MuhurtaSpecialistDecision":
        if self.decision == "amended" and self.amendment_summary is None:
            raise ValueError("amended decision requires an amendment summary")
        if self.decision != "amended" and self.amendment_summary is not None:
            raise ValueError("only amended decisions can carry an amendment summary")
        if self.decision == "rejected" and self.note is None:
            raise ValueError("rejected decision requires a note")
        return self


class MuhurtaSpecialistReviewResponse(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    review_id: str = Field(pattern=r"^muhurta_review_[a-z0-9_]{3,80}$")
    handoff_sha256: Sha256
    reviewer_name: ReviewerName
    reviewer_role: MuhurtaReviewerRole
    qualification_note: QualificationNote
    independence_attested: Literal[True]
    source_access_attested: Literal[True]
    contains_source_text: Literal[False]
    decisions: tuple[MuhurtaSpecialistDecision, ...] = Field(
        min_length=1, max_length=8
    )

    @model_validator(mode="after")
    def _unique_decisions(self) -> "MuhurtaSpecialistReviewResponse":
        ids = [decision.subject_id for decision in self.decisions]
        if len(ids) != len(set(ids)):
            raise ValueError("specialist review decisions must be unique")
        return self

    @property
    def response_sha256(self) -> str:
        payload = self.model_dump(mode="json")
        payload["decisions"] = sorted(
            payload["decisions"], key=lambda item: item["subject_id"]
        )
        return _hash_payload(payload)


class MuhurtaSpecialistReviewReport(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    evaluation_id: Literal["muhurta_specialist_review_v1"]
    handoff_sha256: Sha256
    response_sha256: Sha256
    reviewer_identity_sha256: Sha256
    reviewer_role: MuhurtaReviewerRole
    subject_count: Literal[8]
    reviewed_count: int = Field(ge=0, le=8)
    approved_count: int = Field(ge=0, le=8)
    amended_count: int = Field(ge=0, le=8)
    rejected_count: int = Field(ge=0, le=8)
    gate_status: Literal["passed", "failed", "missing"]
    specialist_review_complete: bool
    blockers: tuple[str, ...]
    privacy_projection: Literal["aggregate_decisions_and_identity_hash_only"]
    report_sha256: Sha256

    @model_validator(mode="after")
    def _honest_and_content_addressed(self) -> "MuhurtaSpecialistReviewReport":
        if self.reviewed_count != (
            self.approved_count + self.amended_count + self.rejected_count
        ):
            raise ValueError("specialist review decision counts disagree")
        if self.specialist_review_complete != (self.gate_status == "passed"):
            raise ValueError("specialist review completion and gate status disagree")
        if self.specialist_review_complete == bool(self.blockers):
            raise ValueError("specialist review blockers disagree with completion")
        payload = self.model_dump(mode="json", exclude={"report_sha256"})
        if self.report_sha256 != _hash_payload(payload):
            raise ValueError("specialist review report is not content-addressed")
        return self


def build_muhurta_specialist_review_handoff() -> MuhurtaSpecialistReviewHandoff:
    """Build the exact review packet from packaged, source-bound artifacts."""

    manifest = SourceManifest.model_validate(_resource_json("muhurta-sources.json"))
    profiles = load_muhurta_profile_catalog()
    rule_pack = load_muhurta_admitted_rule_pack()
    source_ids = {source.source_id for source in manifest.sources}

    rule_subjects: list[MuhurtaReviewSubject] = []
    rule_refs: dict[str, str] = {}
    rule_by_id = {rule.rule_id: rule for rule in rule_pack.rules}
    for index, rule in enumerate(rule_pack.rules):
        if rule.source_id not in source_ids:
            raise ValueError("review rule references a source absent from the manifest")
        ref = (
            "src/jyotish_agent/data/doctrine/"
            f"muhurta-admitted-rules-v1.json#/rules/{index}"
        )
        rule_refs[rule.rule_id] = ref
        locators = tuple(
            f"{rule.source_id}:pdf:{pdf_page}:printed:{printed_page}"
            for pdf_page, printed_page in zip(
                rule.source_pdf_pages, rule.source_printed_pages, strict=True
            )
        )
        rule_subjects.append(
            _subject(
                subject_type="rule",
                subject_id=rule.rule_id,
                current_status="private_experimental",
                rule_ids=(rule.rule_id,),
                source_ids=(rule.source_id,),
                source_locators=locators,
                evidence_refs=(ref,),
                review_questions=(
                    MuhurtaReviewQuestion.SOURCE_ALIGNMENT,
                    MuhurtaReviewQuestion.RULE_SEMANTICS,
                    MuhurtaReviewQuestion.EXCEPTIONS_AND_SCOPE,
                    MuhurtaReviewQuestion.SAFETY_BOUNDARY,
                ),
                artifact=rule.model_dump(mode="json"),
            )
        )

    profile_subjects: list[MuhurtaReviewSubject] = []
    for index, profile in enumerate(profiles.profiles):
        rules = tuple(rule_by_id[rule_id] for rule_id in profile.admitted_rule_ids)
        profile_subjects.append(
            _subject(
                subject_type="profile",
                subject_id=f"profile:{profile.profile.value}",
                current_status="available",
                rule_ids=tuple(sorted(profile.admitted_rule_ids)),
                source_ids=tuple(sorted({rule.source_id for rule in rules})),
                source_locators=tuple(
                    sorted(
                        {
                            f"{rule.source_id}:pdf:{pdf_page}:printed:{printed_page}"
                            for rule in rules
                            for pdf_page, printed_page in zip(
                                rule.source_pdf_pages,
                                rule.source_printed_pages,
                                strict=True,
                            )
                        }
                    )
                ),
                evidence_refs=(
                    "src/jyotish_agent/data/doctrine/"
                    f"muhurta-profiles.json#/profiles/{index}",
                    *(rule_refs[rule_id] for rule_id in sorted(profile.admitted_rule_ids)),
                ),
                review_questions=(
                    MuhurtaReviewQuestion.PROFILE_APPLICABILITY,
                    MuhurtaReviewQuestion.RULE_COMPLETENESS,
                    MuhurtaReviewQuestion.EXCEPTIONS_AND_SCOPE,
                    MuhurtaReviewQuestion.SAFETY_BOUNDARY,
                ),
                artifact=profile.model_dump(mode="json"),
            )
        )

    subjects = tuple(sorted((*rule_subjects, *profile_subjects), key=_subject_sort_key))
    payload = {
        "schema_version": "1.0",
        "handoff_id": "muhurta_classical_baseline_specialist_v1",
        "release_id": "expanded_muhurta_v1",
        "scope": "classical_baseline_v1_private_experimental",
        "source_manifest_sha256": manifest.manifest_sha256,
        "compiled_profile_sha256": muhurta_compiled_profile_sha256(),
        "profile_catalog_sha256": _hash_payload(profiles.model_dump(mode="json")),
        "admitted_rule_pack_sha256": _hash_payload(rule_pack.model_dump(mode="json")),
        "response_schema_ref": (
            "docs/evidence/doctrine/"
            "muhurta-specialist-review-response.schema.json"
        ),
        "response_schema_sha256": _hash_payload(
            muhurta_specialist_review_response_schema()
        ),
        "subject_count": len(subjects),
        "subjects": [subject.model_dump(mode="json") for subject in subjects],
        "decision_options": ("approved", "amended", "rejected"),
        "review_requirements": (
            "Review each exact local source page named by the subject locators.",
            "Judge source alignment, rule semantics, exceptions, applicability, and safety.",
            "Record one decision for every subject and identify the qualified reviewer.",
            "Treat amended subjects as pending implementation and re-review, not approval.",
        ),
        "excluded_scope": (
            "B. V. Raman modern overlay until exact licensed source bytes are supplied.",
            "High-stakes medical, longevity, legal, and financial activities.",
            "Copyrighted source text and local private-source paths.",
        ),
        "external_review_status": "missing",
        "ready_for_external_review": True,
        "privacy_projection": "metadata_hashes_and_locators_only",
    }
    return MuhurtaSpecialistReviewHandoff(
        **payload,
        handoff_sha256=_hash_payload(payload),
    )


def muhurta_specialist_review_response_schema() -> dict[str, object]:
    """Return the strict response schema distributed with the review handoff."""

    return MuhurtaSpecialistReviewResponse.model_json_schema()


def evaluate_muhurta_specialist_review(
    handoff: MuhurtaSpecialistReviewHandoff,
    response: MuhurtaSpecialistReviewResponse,
) -> MuhurtaSpecialistReviewReport:
    """Validate a private named review and emit an aggregate release-gate report."""

    if handoff != build_muhurta_specialist_review_handoff():
        raise ValueError("specialist handoff does not match packaged artifacts")
    if response.handoff_sha256 != handoff.handoff_sha256:
        raise ValueError("specialist response targets a different handoff")
    subjects = {subject.subject_id: subject for subject in handoff.subjects}
    for decision in response.decisions:
        subject = subjects.get(decision.subject_id)
        if subject is None:
            raise ValueError("specialist response contains an unknown subject")
        if decision.subject_type != subject.subject_type:
            raise ValueError("specialist response changed the subject type")
        if decision.subject_sha256 != subject.subject_sha256:
            raise ValueError("specialist response changed the subject identity")

    approved = sum(item.decision == "approved" for item in response.decisions)
    amended = sum(item.decision == "amended" for item in response.decisions)
    rejected = sum(item.decision == "rejected" for item in response.decisions)
    missing = handoff.subject_count - len(response.decisions)
    blockers: list[str] = []
    if missing:
        blockers.append(f"missing_subject_decisions:{missing}")
    if amended:
        blockers.append(f"amendments_pending_implementation:{amended}")
    if rejected:
        blockers.append(f"rejected_subjects:{rejected}")
    gate_status = "failed" if rejected else "missing" if blockers else "passed"
    identity = {
        "reviewer_name": response.reviewer_name,
        "reviewer_role": response.reviewer_role.value,
        "qualification_note": response.qualification_note,
    }
    payload = {
        "schema_version": "1.0",
        "evaluation_id": "muhurta_specialist_review_v1",
        "handoff_sha256": handoff.handoff_sha256,
        "response_sha256": response.response_sha256,
        "reviewer_identity_sha256": _hash_payload(identity),
        "reviewer_role": response.reviewer_role.value,
        "subject_count": handoff.subject_count,
        "reviewed_count": len(response.decisions),
        "approved_count": approved,
        "amended_count": amended,
        "rejected_count": rejected,
        "gate_status": gate_status,
        "specialist_review_complete": gate_status == "passed",
        "blockers": tuple(blockers),
        "privacy_projection": "aggregate_decisions_and_identity_hash_only",
    }
    return MuhurtaSpecialistReviewReport(
        **payload,
        report_sha256=_hash_payload(payload),
    )


def _subject(
    *,
    subject_type: Literal["rule", "profile"],
    subject_id: str,
    current_status: Literal["private_experimental", "available"],
    rule_ids: tuple[str, ...],
    source_ids: tuple[SourceId, ...],
    source_locators: tuple[str, ...],
    evidence_refs: tuple[str, ...],
    review_questions: tuple[MuhurtaReviewQuestion, ...],
    artifact: object,
) -> MuhurtaReviewSubject:
    payload = {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "current_status": current_status,
        "rule_ids": rule_ids,
        "source_ids": source_ids,
        "source_locators": source_locators,
        "evidence_refs": evidence_refs,
        "review_questions": review_questions,
        "artifact_sha256": _hash_payload(artifact),
    }
    return MuhurtaReviewSubject(
        **payload,
        subject_sha256=_hash_payload(payload),
    )


def _subject_sort_key(subject: MuhurtaReviewSubject) -> tuple[int, str]:
    return (0 if subject.subject_type == "rule" else 1, subject.subject_id)


def _resource_json(name: str) -> object:
    payload = resources.files("jyotish_agent").joinpath(
        f"data/doctrine/{name}"
    ).read_text(encoding="utf-8")
    return json.loads(payload)


def _hash_payload(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
