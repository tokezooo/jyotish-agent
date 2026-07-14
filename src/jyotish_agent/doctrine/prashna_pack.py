"""Source-bound Full Prashna corpus and doctrine orchestration.

This module starts with an acquisition ledger.  It deliberately distinguishes
verified book bytes from verified published outcomes, and keeps Tajika geometry
as a named overlay instead of silently blending it into the Prasna Marga
baseline.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .models import FrozenModel
from .sources import SourceId, SourceManifest, SourceVerificationReport


class PrashnaCorpusRequirement(StrEnum):
    PRASNA_MARGA_BASELINE = "prasna_marga_baseline"
    DAIVAJNA_VALLABHA = "daivajna_vallabha"
    SATPANCASIKA = "satpancasika"
    TAJIKA_ASPECT_OVERLAY = "tajika_aspect_overlay"
    PUBLISHED_CASES = "published_cases"


class PrashnaCorpusRequirementRecord(FrozenModel):
    requirement: PrashnaCorpusRequirement
    school: str = Field(min_length=1)
    source_ids: tuple[SourceId, ...] = Field(min_length=1)
    doctrine_topics: tuple[str, ...] = ()
    acquisition_blocker: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _coherent_record(self) -> "PrashnaCorpusRequirementRecord":
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("source_ids must be unique")
        if len(set(self.doctrine_topics)) != len(self.doctrine_topics):
            raise ValueError("doctrine_topics must be unique")
        return self


class PrashnaCorpusCatalog(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    required_published_case_count: int = Field(ge=2, le=100)
    safe_question_classes: tuple[str, ...] = Field(min_length=1)
    unsupported_question_classes: tuple[str, ...] = Field(min_length=1)
    missing_doctrine: tuple[str, ...]
    requirements: tuple[PrashnaCorpusRequirementRecord, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _complete_catalog(self) -> "PrashnaCorpusCatalog":
        requirements = [item.requirement for item in self.requirements]
        if len(requirements) != len(set(requirements)):
            raise ValueError("duplicate corpus requirement")
        if set(requirements) != set(PrashnaCorpusRequirement):
            raise ValueError("catalog must declare every Prashna corpus requirement")
        if set(self.safe_question_classes) & set(self.unsupported_question_classes):
            raise ValueError("safe and unsupported question classes must be disjoint")
        baseline = self.requirement(PrashnaCorpusRequirement.PRASNA_MARGA_BASELINE)
        overlay = self.requirement(PrashnaCorpusRequirement.TAJIKA_ASPECT_OVERLAY)
        if baseline.school == overlay.school or set(baseline.source_ids) & set(
            overlay.source_ids
        ):
            raise ValueError("baseline and Tajika overlay must remain separate")
        return self

    def requirement(
        self, requirement: PrashnaCorpusRequirement
    ) -> PrashnaCorpusRequirementRecord:
        return next(
            item for item in self.requirements if item.requirement == requirement
        )


class PrashnaPublishedCase(FrozenModel):
    case_id: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    source_id: SourceId
    question: str = Field(min_length=1)
    question_at: str
    place_label: str = Field(min_length=1)
    question_class: str = Field(min_length=1)
    source_pdf_pages: tuple[int, ...] = Field(min_length=1)
    source_printed_pages: tuple[int, ...] = Field(min_length=1)
    judgment: Literal["positive", "negative", "mixed", "unavailable"]
    timing: str = Field(min_length=1)
    observed_outcome: str = Field(min_length=1)
    outcome_traceable: bool
    admissibility: Literal["admitted_safe", "excluded_high_stakes", "quarantined"]

    @field_validator("question_at")
    @classmethod
    def _aware_question_time(cls, value: str) -> str:
        parsed = dt.datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("question_at must include a UTC offset")
        return value

    @model_validator(mode="after")
    def _traceable_case(self) -> "PrashnaPublishedCase":
        if len(set(self.source_pdf_pages)) != len(self.source_pdf_pages):
            raise ValueError("source_pdf_pages must be unique")
        if len(self.source_pdf_pages) != len(self.source_printed_pages):
            raise ValueError("PDF and printed page anchors must pair one-to-one")
        if self.admissibility == "admitted_safe" and not self.outcome_traceable:
            raise ValueError("admitted cases require a traceable observed outcome")
        return self


class PrashnaCaseCatalog(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    cases: tuple[PrashnaPublishedCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_cases(self) -> "PrashnaCaseCatalog":
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate published case")
        return self

    @property
    def verified_outcome_count(self) -> int:
        return sum(case.outcome_traceable for case in self.cases)


class PrashnaCorpusCoverage(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    manifest_sha256: str
    verified_source_ids: tuple[SourceId, ...]
    unverified_source_ids: tuple[SourceId, ...]
    covered_requirements: tuple[PrashnaCorpusRequirement, ...]
    missing_requirements: tuple[PrashnaCorpusRequirement, ...]
    verified_published_case_count: int = Field(ge=0)
    missing_published_case_count: int = Field(ge=0)
    safe_question_classes: tuple[str, ...]
    unsupported_question_classes: tuple[str, ...]
    missing_doctrine: tuple[str, ...]
    acquisition_blockers: tuple[str, ...]
    ready: bool


def build_prashna_corpus_coverage(
    manifest: SourceManifest,
    verification: SourceVerificationReport,
    catalog: PrashnaCorpusCatalog,
    cases: PrashnaCaseCatalog,
) -> PrashnaCorpusCoverage:
    """Calculate coverage from verified bytes and traceable outcomes only."""

    manifest_ids = {source.source_id for source in manifest.sources}
    catalog_ids = {
        source_id
        for requirement in catalog.requirements
        for source_id in requirement.source_ids
    }
    case_source_ids = {case.source_id for case in cases.cases}
    if catalog_ids - manifest_ids or case_source_ids - manifest_ids:
        raise ValueError("Prashna catalog references a source absent from the manifest")

    verified = set(verification.verified_source_ids)
    verified_cases = sum(
        case.outcome_traceable and case.source_id in verified for case in cases.cases
    )
    missing_case_count = max(0, catalog.required_published_case_count - verified_cases)
    covered: list[PrashnaCorpusRequirement] = []
    missing: list[PrashnaCorpusRequirement] = []
    blockers: list[str] = []
    for item in sorted(catalog.requirements, key=lambda value: value.requirement.value):
        fulfilled = set(item.source_ids) <= verified
        if item.requirement == PrashnaCorpusRequirement.PUBLISHED_CASES:
            fulfilled = fulfilled and missing_case_count == 0
        if fulfilled:
            covered.append(item.requirement)
        else:
            missing.append(item.requirement)
            reason = item.acquisition_blocker
            if item.requirement == PrashnaCorpusRequirement.PUBLISHED_CASES:
                reason = (
                    f"{missing_case_count} additional published case(s) with question "
                    "time, place, judgment, timing, and observed outcome are required."
                )
            elif reason is None:
                reason = "declared source bytes did not verify"
            blockers.append(f"{item.requirement.value}: {reason}")

    return PrashnaCorpusCoverage(
        manifest_sha256=manifest.manifest_sha256,
        verified_source_ids=tuple(sorted(verified)),
        unverified_source_ids=tuple(sorted(manifest_ids - verified)),
        covered_requirements=tuple(sorted(covered, key=lambda item: item.value)),
        missing_requirements=tuple(sorted(missing, key=lambda item: item.value)),
        verified_published_case_count=verified_cases,
        missing_published_case_count=missing_case_count,
        safe_question_classes=tuple(sorted(catalog.safe_question_classes)),
        unsupported_question_classes=tuple(
            sorted(catalog.unsupported_question_classes)
        ),
        missing_doctrine=tuple(sorted(catalog.missing_doctrine)),
        acquisition_blockers=tuple(sorted(blockers)),
        ready=not missing and missing_case_count == 0,
    )


def render_prashna_corpus_coverage(
    report: PrashnaCorpusCoverage,
) -> dict[str, object]:
    """Return a deterministic projection without local paths or copyrighted text."""

    return report.model_dump(mode="json")


class PrashnaRadicalityCriterion(FrozenModel):
    criterion_id: Literal[
        "anchor_exact", "question_not_test", "question_once", "question_proper_form"
    ]
    source_id: SourceId
    pdf_page: int = Field(ge=1)
    printed_page: int = Field(ge=1)
    page_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_locator: str = Field(min_length=1)


class PrashnaRadicalityProfile(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    profile_id: Literal["prasna_marga_radicality_v1"]
    school: Literal["prasna_marga_baseline"]
    profile_kind: Literal["baseline"]
    overlay_profile_id: str | None = None
    confidence_ceiling: float = Field(ge=0.0, le=0.65)
    criteria: tuple[PrashnaRadicalityCriterion, ...] = Field(min_length=4)

    @model_validator(mode="after")
    def _pure_complete_baseline(self) -> "PrashnaRadicalityProfile":
        if self.overlay_profile_id is not None:
            raise ValueError("baseline radicality profile cannot include an overlay")
        ids = [criterion.criterion_id for criterion in self.criteria]
        expected = {
            "anchor_exact",
            "question_not_test",
            "question_once",
            "question_proper_form",
        }
        if set(ids) != expected or len(ids) != len(expected):
            raise ValueError("baseline radicality criteria must be complete and unique")
        return self


class PrashnaRadicalityInput(FrozenModel):
    """Privacy-safe adjudication facts; raw question and place never enter this layer."""

    anchor_state: Literal["sealed", "stale", "invalid"]
    question_relation: Literal[
        "new_anchor", "exact_duplicate", "bounded_clarification", "material_mismatch"
    ]
    topic_state: Literal["single_safe", "composite", "unclear", "unsuitable"]
    question_form: Literal["proper", "improper"]
    intent_state: Literal["sincere", "testing", "unknown"]
    sources_admitted: bool


class PrashnaRadicalityResult(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    status: Literal["readable", "conflicting", "unavailable"]
    outcome_allowed: bool
    anchor_action: Literal[
        "reuse_sealed_anchor",
        "create_new_anchor",
        "require_single_question",
        "inspect_source_admission",
    ]
    confidence_ceiling: float = Field(ge=0.0, le=0.65)
    reason_codes: tuple[str, ...]
    school: Literal["prasna_marga_baseline"]
    source_refs: tuple[str, ...]

    @model_validator(mode="after")
    def _outcome_requires_readability(self) -> "PrashnaRadicalityResult":
        if self.outcome_allowed != (self.status == "readable"):
            raise ValueError(
                "only readable radicality results may reach an outcome path"
            )
        return self


def evaluate_prashna_radicality(
    value: PrashnaRadicalityInput,
    profile: PrashnaRadicalityProfile,
) -> PrashnaRadicalityResult:
    """Evaluate the source-bound gate before any significator or outcome logic."""

    source_refs = tuple(
        f"{item.source_id}:pdf:{item.pdf_page}:sha256:{item.page_sha256}"
        for item in sorted(
            profile.criteria, key=lambda criterion: criterion.criterion_id
        )
    )
    common = {
        "confidence_ceiling": profile.confidence_ceiling,
        "school": profile.school,
        "source_refs": source_refs,
    }
    if not value.sources_admitted:
        return PrashnaRadicalityResult(
            status="unavailable",
            outcome_allowed=False,
            anchor_action="inspect_source_admission",
            reason_codes=("SOURCE_ADMISSION_MISSING",),
            **common,
        )
    if value.anchor_state != "sealed":
        return PrashnaRadicalityResult(
            status="unavailable",
            outcome_allowed=False,
            anchor_action="create_new_anchor",
            reason_codes=(
                "ANCHOR_STALE" if value.anchor_state == "stale" else "ANCHOR_INVALID",
            ),
            **common,
        )
    if value.question_relation == "material_mismatch":
        return PrashnaRadicalityResult(
            status="unavailable",
            outcome_allowed=False,
            anchor_action="create_new_anchor",
            reason_codes=("MATERIAL_MISMATCH",),
            **common,
        )
    if value.topic_state != "single_safe":
        reason = {
            "composite": "TOPIC_COMPOSITE",
            "unclear": "TOPIC_UNCLEAR",
            "unsuitable": "TOPIC_UNSUITABLE",
        }[value.topic_state]
        return PrashnaRadicalityResult(
            status="unavailable",
            outcome_allowed=False,
            anchor_action="require_single_question",
            reason_codes=(reason,),
            **common,
        )
    if value.question_form == "improper" or value.intent_state != "sincere":
        reasons = []
        if value.question_form == "improper":
            reasons.append("FORM_IMPROPER")
        if value.intent_state == "testing":
            reasons.append("INTENT_TESTING")
        elif value.intent_state == "unknown":
            reasons.append("INTENT_UNCLEAR")
        return PrashnaRadicalityResult(
            status="unavailable",
            outcome_allowed=False,
            anchor_action="require_single_question",
            reason_codes=tuple(reasons),
            **common,
        )
    if value.question_relation == "exact_duplicate":
        return PrashnaRadicalityResult(
            status="conflicting",
            outcome_allowed=False,
            anchor_action="reuse_sealed_anchor",
            reason_codes=("QUESTION_REPEATED",),
            **common,
        )
    return PrashnaRadicalityResult(
        status="readable",
        outcome_allowed=True,
        anchor_action="reuse_sealed_anchor",
        reason_codes=(),
        **common,
    )
