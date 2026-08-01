"""Source-bound Full Prashna corpus and doctrine orchestration.

This module starts with an acquisition ledger.  It deliberately distinguishes
verified book bytes from verified published outcomes, and keeps Tajika geometry
as a named overlay instead of silently blending it into the Prasna Marga
baseline.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import unicodedata
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..prashna import calculate_prashna_aspect_geometry
from ..prashna_models import (
    PrashnaAspectDoctrineProfile,
    PrashnaAspectGeometryInput,
    PrashnaAspectGeometryResult,
    PrashnaFact,
)
from ..research_store import canonical_json
from .evaluation import AdmissionEvaluator
from .models import FrozenModel
from .sources import (
    SourceId,
    SourceManifest,
    SourceVerificationReport,
    SourceVerifier,
    load_source_manifest,
)


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
    fragment_start_offset: int = Field(ge=0)
    fragment_end_offset: int = Field(ge=1)
    fragment_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fragment_word_count: int = Field(ge=1)
    fragment_normalization: Literal["whitespace_collapse_v1"]
    admission_status: Literal["private_experimental"]
    specialist_review_status: Literal["missing"]

    @model_validator(mode="after")
    def _bounded_fragment(self) -> "PrashnaRadicalityCriterion":
        if self.fragment_end_offset <= self.fragment_start_offset:
            raise ValueError("fragment offsets must describe a non-empty range")
        return self


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
        f"{item.source_id}:pdf:{item.pdf_page}:sha256:{item.page_sha256}:"
        f"fragment:sha256:{item.fragment_text_sha256}"
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


class PrashnaQuestionProfile(StrEnum):
    WORK_PROJECT_STATUS = "work_project_status"
    COMMUNICATION_CONTACT = "communication_contact"
    LOST_OBJECT = "lost_object"
    GENERAL_LOW_RISK_OUTCOME = "general_low_risk_outcome"


class _QuestionProfileBinding(FrozenModel):
    profile: PrashnaQuestionProfile
    primary_house: int = Field(ge=1, le=12)
    secondary_houses: tuple[int, ...]
    significators: tuple[str, ...]
    source_refs: tuple[str, ...]


class PrashnaQuestionRoute(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    status: Literal["supported", "unsupported", "composite", "high_stakes", "ambiguous"]
    profile: PrashnaQuestionProfile | None = None
    primary_house: int | None = Field(default=None, ge=1, le=12)
    secondary_houses: tuple[int, ...] = ()
    significators: tuple[str, ...] = ()
    required_fact_paths: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    guidance_code: Literal[
        "PROCEED",
        "ASK_ONE_MATERIAL_QUESTION",
        "CONSULT_QUALIFIED_PROFESSIONAL",
        "NAME_A_SUPPORTED_LOW_RISK_TOPIC",
        "TOPIC_NOT_SUPPORTED",
    ]

    @model_validator(mode="after")
    def _supported_route_is_complete(self) -> "PrashnaQuestionRoute":
        details = (
            self.profile,
            self.primary_house,
            self.secondary_houses,
            self.significators,
            self.required_fact_paths,
            self.source_refs,
        )
        if self.status == "supported" and (
            self.guidance_code != "PROCEED" or any(not item for item in details)
        ):
            raise ValueError("supported routes require complete source-bound details")
        if self.status != "supported" and any(item for item in details):
            raise ValueError("rejected routes cannot expose doctrine significators")
        return self


_QUESTION_BINDINGS = {
    PrashnaQuestionProfile.WORK_PROJECT_STATUS: _QuestionProfileBinding(
        profile=PrashnaQuestionProfile.WORK_PROJECT_STATUS,
        primary_house=10,
        secondary_houses=(1, 6, 11),
        significators=("lagna_lord", "primary_house_lord", "moon"),
        source_refs=(
            "daivajna_vallabha_2003_scan:pdf:3:sha256:"
            "e881c291388fd5e02f8717c5902380ef8ad2b68985572caa6eeaa4eba4d41759",
        ),
    ),
    PrashnaQuestionProfile.COMMUNICATION_CONTACT: _QuestionProfileBinding(
        profile=PrashnaQuestionProfile.COMMUNICATION_CONTACT,
        primary_house=7,
        secondary_houses=(3, 11),
        significators=("lagna_lord", "primary_house_lord", "moon"),
        source_refs=(
            "daivajna_vallabha_2003_scan:pdf:2:sha256:"
            "52855cdb9c26b1cb15c795f471a9c12d33bbe5b1d6071a2a42b3f8e8b0e9c894",
        ),
    ),
    PrashnaQuestionProfile.LOST_OBJECT: _QuestionProfileBinding(
        profile=PrashnaQuestionProfile.LOST_OBJECT,
        primary_house=1,
        secondary_houses=(2, 4, 7, 11),
        significators=("lagna_lord", "primary_house_lord", "moon"),
        source_refs=(
            "daivajna_vallabha_2003_scan:pdf:13:sha256:"
            "08a051f2c5bda4e0583fd7311690a1faaf64237d4b1cddfb90b8953cb42fbe05",
            "daivajna_vallabha_2003_scan:pdf:14:sha256:"
            "1891ca12a62377cb054a077f2b52a1a1ab0b1a3aaef07933e80a390c2eda2551",
        ),
    ),
    PrashnaQuestionProfile.GENERAL_LOW_RISK_OUTCOME: _QuestionProfileBinding(
        profile=PrashnaQuestionProfile.GENERAL_LOW_RISK_OUTCOME,
        primary_house=1,
        secondary_houses=(4, 7, 10, 11),
        significators=("lagna_lord", "primary_house_lord", "moon"),
        source_refs=(
            "daivajna_vallabha_2003_scan:pdf:3:sha256:"
            "e881c291388fd5e02f8717c5902380ef8ad2b68985572caa6eeaa4eba4d41759",
        ),
    ),
}

_WORK_MARKERS = (
    "work",
    "project",
    "job",
    "career",
    "business",
    "startup",
    "работ",
    "проект",
    "карьер",
    "бизнес",
    "стартап",
)
_CONTACT_MARKERS = (
    "contact",
    "message",
    "email",
    "reply",
    "call me",
    "reach me",
    "свяж",
    "сообщен",
    "письм",
    "ответит",
    "позвон",
)
_LOST_MARKERS = (
    "lost",
    "missing object",
    "missing item",
    "where are my",
    "where is my",
    "потерян",
    "пропал",
    "пропала",
    "где мои",
    "где моя",
    "где мой",
)
_GENERAL_MARKERS = (
    "low risk",
    "non critical outcome",
    "work out",
    "безрисков",
    "низкорисков",
    "получится ли",
)
_HIGH_STAKES_MARKERS = (
    "medical",
    "health",
    "surgery",
    "cancer",
    "pregnan",
    "death",
    "die",
    "harm",
    "lawsuit",
    "court",
    "legal",
    "invest",
    "stock",
    "crypto",
    "loan",
    "dangerous",
    "здоров",
    "операц",
    "рак",
    "беремен",
    "смерт",
    "умр",
    "вред",
    "суд",
    "юрид",
    "инвест",
    "крипт",
    "кредит",
    "опасн",
)


def _normalized_route_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    return " ".join(re.sub(r"[^\w]+", " ", normalized).split())


def _has_marker(value: str, markers: tuple[str, ...]) -> bool:
    return any(marker in value for marker in markers)


def classify_prashna_question(question: str) -> PrashnaQuestionRoute:
    """Route exactly one safe material topic without returning its private wording."""

    normalized = _normalized_route_text(question)
    if _has_marker(normalized, _HIGH_STAKES_MARKERS):
        return PrashnaQuestionRoute(
            status="high_stakes", guidance_code="CONSULT_QUALIFIED_PROFESSIONAL"
        )
    detected: list[PrashnaQuestionProfile] = []
    explicitly_low_risk = _has_marker(
        normalized, ("low risk", "безрисков", "низкорисков")
    )
    specific_text = (
        normalized.replace("work out", "") if explicitly_low_risk else normalized
    )
    for profile, markers in (
        (PrashnaQuestionProfile.WORK_PROJECT_STATUS, _WORK_MARKERS),
        (PrashnaQuestionProfile.COMMUNICATION_CONTACT, _CONTACT_MARKERS),
        (PrashnaQuestionProfile.LOST_OBJECT, _LOST_MARKERS),
    ):
        if _has_marker(specific_text, markers):
            detected.append(profile)
    if not detected and explicitly_low_risk:
        detected.append(PrashnaQuestionProfile.GENERAL_LOW_RISK_OUTCOME)
    if len(detected) > 1:
        return PrashnaQuestionRoute(
            status="composite", guidance_code="ASK_ONE_MATERIAL_QUESTION"
        )
    if not detected and _has_marker(normalized, _GENERAL_MARKERS):
        detected.append(PrashnaQuestionProfile.GENERAL_LOW_RISK_OUTCOME)
    if not detected:
        generic_future = bool(
            re.search(r"\b(will|happen|будет|случится|получится)\b", normalized)
        )
        return PrashnaQuestionRoute(
            status="ambiguous" if generic_future else "unsupported",
            guidance_code=(
                "NAME_A_SUPPORTED_LOW_RISK_TOPIC"
                if generic_future
                else "TOPIC_NOT_SUPPORTED"
            ),
        )

    binding = _QUESTION_BINDINGS[detected[0]]
    houses = (binding.primary_house, *binding.secondary_houses)
    required = {
        "prashna.lagna.sign",
        "prashna.moon.sign",
        "prashna.topic.primary_house",
        "prashna.topic.primary_lord",
        "prashna.topic.primary_lord_house",
        *(f"prashna.bhava.{house}.lord" for house in houses),
    }
    return PrashnaQuestionRoute(
        status="supported",
        profile=binding.profile,
        primary_house=binding.primary_house,
        secondary_houses=binding.secondary_houses,
        significators=binding.significators,
        required_fact_paths=tuple(sorted(required)),
        source_refs=binding.source_refs,
        guidance_code="PROCEED",
    )


def validate_prashna_significator_claim(
    route: PrashnaQuestionRoute,
    *,
    claimed_primary_house: int,
    claimed_significators: tuple[str, ...],
) -> tuple[str, ...]:
    """Reject a renderer that changes the selected house or significators."""

    if route.status != "supported":
        return ("ROUTE_NOT_SUPPORTED",)
    failures: list[str] = []
    if claimed_primary_house != route.primary_house:
        failures.append("PRIMARY_HOUSE_SUBSTITUTED")
    if claimed_significators != route.significators:
        failures.append("SIGNIFICATORS_SUBSTITUTED")
    return tuple(failures)


def prashna_aspect_profile(
    school: Literal["prasna_marga_baseline", "tajika_nilakanthi_overlay"],
) -> PrashnaAspectDoctrineProfile:
    """Return an explicit fail-closed geometry profile for the selected school."""

    common = {
        "max_orb_degrees": 6.0,
        "exact_tolerance_degrees": 0.01,
        "boundary_tolerance_degrees": 0.05,
        "relative_speed_floor": 0.01,
        "probe_days": 1.0 / 1440.0,
        "source_admitted": False,
        "source_refs": (),
    }
    if school == "prasna_marga_baseline":
        return PrashnaAspectDoctrineProfile(
            profile_id="prasna_marga_baseline_geometry_v1",
            school=school,
            profile_kind="baseline",
            base_profile_id=None,
            allowed_aspects=(0.0,),
            **common,
        )
    return PrashnaAspectDoctrineProfile(
        profile_id="tajika_nilakanthi_geometry_v1",
        school=school,
        profile_kind="overlay",
        base_profile_id="prasna_marga_baseline_geometry_v1",
        allowed_aspects=(0.0, 60.0, 90.0, 120.0, 180.0),
        **common,
    )


class PrashnaBaselineRule(FrozenModel):
    rule_id: Literal[
        "primary_house_lord_connection",
        "relative_benefic_support",
        "relative_malefic_obstacle",
    ]
    kind: Literal["geometry", "assistance", "obstacle"]
    confidence: float = Field(gt=0.0, le=0.65)
    source_ref: str = Field(
        pattern=(
            r"^[a-z][a-z0-9_]+:pdf:[1-9][0-9]*:sha256:[0-9a-f]{64}$"
        )
    )


class PrashnaBaselineRulePack(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    profile_id: Literal["full_prashna_private_baseline_v1"]
    school: Literal["prasna_marga_baseline"]
    confidence_ceiling: float = Field(gt=0.0, le=0.65)
    benefic_planets: tuple[Literal["Jupiter", "Venus"], ...]
    malefic_planets: tuple[Literal["Mars", "Saturn"], ...]
    rules: tuple[PrashnaBaselineRule, ...] = Field(min_length=3)

    @model_validator(mode="after")
    def _complete_conservative_pack(self) -> "PrashnaBaselineRulePack":
        expected = {
            "primary_house_lord_connection": "geometry",
            "relative_benefic_support": "assistance",
            "relative_malefic_obstacle": "obstacle",
        }
        actual = {rule.rule_id: rule.kind for rule in self.rules}
        if actual != expected or len(self.rules) != len(expected):
            raise ValueError("Prashna baseline rule pack is incomplete or blended")
        if set(self.benefic_planets) & set(self.malefic_planets):
            raise ValueError("benefic and malefic classifications must be disjoint")
        return self

    def rule(self, rule_id: str) -> PrashnaBaselineRule:
        return next(rule for rule in self.rules if rule.rule_id == rule_id)


_PRASHNA_BASELINE_PROFILE = (
    Path(__file__).resolve().parents[1]
    / "data/doctrine/prashna-baseline-profile.json"
)


def load_prashna_baseline_rule_pack() -> PrashnaBaselineRulePack:
    return PrashnaBaselineRulePack.model_validate_json(
        _PRASHNA_BASELINE_PROFILE.read_text(encoding="utf-8")
    )


def prashna_compiled_profile_sha256() -> str:
    pack = load_prashna_baseline_rule_pack()
    return hashlib.sha256(
        canonical_json(pack.model_dump(mode="json")).encode("utf-8")
    ).hexdigest()


class PrashnaBaselineGeometryResult(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    profile_id: Literal["full_prashna_private_baseline_v1"]
    school: Literal["prasna_marga_baseline"]
    state: Literal["connected", "unconnected", "unavailable"]
    primary_house: int = Field(ge=1, le=12)
    primary_lord: str | None
    connection: Literal["associated", "aspected", "none", "unavailable"]
    reason_code: str | None
    source_refs: tuple[str, ...]
    fact_refs: tuple[str, ...]
    geometry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _coherent_geometry(self) -> "PrashnaBaselineGeometryResult":
        if self.state == "unavailable":
            if self.connection != "unavailable" or self.reason_code is None:
                raise ValueError("unavailable baseline geometry requires a reason")
        elif self.reason_code is not None or self.connection == "unavailable":
            raise ValueError("available baseline geometry cannot carry an error")
        if (self.state == "connected") != (
            self.connection in {"associated", "aspected"}
        ):
            raise ValueError("baseline connection and state disagree")
        return self


def _baseline_geometry(
    payload: dict[str, object],
) -> PrashnaBaselineGeometryResult:
    draft = PrashnaBaselineGeometryResult(**payload, geometry_sha256="0" * 64)
    encoded = canonical_json(
        draft.model_dump(mode="json", exclude={"geometry_sha256"})
    )
    return draft.model_copy(
        update={"geometry_sha256": hashlib.sha256(encoded.encode()).hexdigest()}
    )


def _prashna_fact_map(facts: tuple[PrashnaFact, ...]) -> dict[str, object]:
    return {fact.fact_id: fact.value for fact in facts}


def evaluate_prashna_baseline_geometry(
    facts: tuple[PrashnaFact, ...],
    route: PrashnaQuestionRoute,
    pack: PrashnaBaselineRulePack | None = None,
) -> PrashnaBaselineGeometryResult:
    """Evaluate the admitted Daivajna house-lord connection without Tajika."""

    pack = pack or load_prashna_baseline_rule_pack()
    source_ref = pack.rule("primary_house_lord_connection").source_ref
    primary_house = route.primary_house or 1
    values = _prashna_fact_map(facts)
    lord_path = "prashna.topic.primary_lord"
    lord_house_path = "prashna.topic.primary_lord_house"
    primary_lord = values.get(lord_path)
    primary_lord_house = values.get(lord_house_path)
    if not isinstance(primary_lord, str) or not isinstance(primary_lord_house, int):
        return _baseline_geometry(
            {
                "schema_version": "1.0",
                "profile_id": pack.profile_id,
                "school": pack.school,
                "state": "unavailable",
                "primary_house": primary_house,
                "primary_lord": primary_lord if isinstance(primary_lord, str) else None,
                "connection": "unavailable",
                "reason_code": "PRIMARY_LORD_FACTS_MISSING",
                "source_refs": (source_ref,),
                "fact_refs": (),
            }
        )
    aspect_path = f"prashna.graha_drishti.{primary_lord}.houses"
    aspect_value = values.get(aspect_path)
    if not isinstance(aspect_value, str):
        return _baseline_geometry(
            {
                "schema_version": "1.0",
                "profile_id": pack.profile_id,
                "school": pack.school,
                "state": "unavailable",
                "primary_house": primary_house,
                "primary_lord": primary_lord,
                "connection": "unavailable",
                "reason_code": "PRIMARY_LORD_ASPECT_FACT_MISSING",
                "source_refs": (source_ref,),
                "fact_refs": (lord_path, lord_house_path),
            }
        )
    aspected_houses = {
        int(value) for value in aspect_value.split(",") if value.isdigit()
    }
    if primary_lord_house == primary_house:
        connection = "associated"
    elif primary_house in aspected_houses:
        connection = "aspected"
    else:
        connection = "none"
    return _baseline_geometry(
        {
            "schema_version": "1.0",
            "profile_id": pack.profile_id,
            "school": pack.school,
            "state": "connected" if connection != "none" else "unconnected",
            "primary_house": primary_house,
            "primary_lord": primary_lord,
            "connection": connection,
            "reason_code": None,
            "source_refs": (source_ref,),
            "fact_refs": (aspect_path, lord_path, lord_house_path),
        }
    )


class PrashnaTestimony(FrozenModel):
    testimony_id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    polarity: Literal["assistance", "obstacle"]
    confidence: float = Field(gt=0.0, le=0.65)
    fact_refs: tuple[str, ...] = Field(min_length=1)
    source_refs: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_lineage(self) -> "PrashnaTestimony":
        if len(set(self.fact_refs)) != len(self.fact_refs):
            raise ValueError("testimony fact references must be unique")
        if len(set(self.source_refs)) != len(self.source_refs):
            raise ValueError("testimony source references must be unique")
        return self


def build_prashna_baseline_testimonies(
    facts: tuple[PrashnaFact, ...],
    route: PrashnaQuestionRoute,
    geometry: PrashnaBaselineGeometryResult,
    pack: PrashnaBaselineRulePack | None = None,
) -> tuple[PrashnaTestimony, ...]:
    """Build only conservative testimonies declared by the private baseline pack."""

    if route.status != "supported" or route.primary_house is None:
        return ()
    pack = pack or load_prashna_baseline_rule_pack()
    values = _prashna_fact_map(facts)
    testimonies: list[PrashnaTestimony] = []
    if geometry.state == "connected":
        rule = pack.rule("primary_house_lord_connection")
        testimonies.append(
            PrashnaTestimony(
                testimony_id=rule.rule_id,
                polarity="assistance",
                confidence=rule.confidence,
                fact_refs=geometry.fact_refs,
                source_refs=(rule.source_ref,),
            )
        )

    supporting_paths: list[str] = []
    obstacle_paths: list[str] = []
    favorable_relative_houses = {2, 4, 7, 10, 12}
    for planet in (*pack.benefic_planets, *pack.malefic_planets):
        path = f"prashna.planets.{planet}.house"
        house = values.get(path)
        if not isinstance(house, int):
            continue
        relative_house = ((house - route.primary_house) % 12) + 1
        if relative_house not in favorable_relative_houses:
            continue
        if planet in pack.benefic_planets:
            supporting_paths.append(path)
        else:
            obstacle_paths.append(path)

    if supporting_paths:
        rule = pack.rule("relative_benefic_support")
        testimonies.append(
            PrashnaTestimony(
                testimony_id=rule.rule_id,
                polarity="assistance",
                confidence=rule.confidence,
                fact_refs=tuple(sorted(supporting_paths)),
                source_refs=(rule.source_ref,),
            )
        )
    if obstacle_paths:
        rule = pack.rule("relative_malefic_obstacle")
        testimonies.append(
            PrashnaTestimony(
                testimony_id=rule.rule_id,
                polarity="obstacle",
                confidence=rule.confidence,
                fact_refs=tuple(sorted(obstacle_paths)),
                source_refs=(rule.source_ref,),
            )
        )
    return tuple(sorted(testimonies, key=lambda item: item.testimony_id))


class PrashnaTimingSupport(FrozenModel):
    minimum: int = Field(ge=0, le=10_000)
    maximum: int = Field(ge=0, le=10_000)
    unit: Literal["minutes", "hours", "days", "weeks", "months"]
    source_refs: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _bounded_window(self) -> "PrashnaTimingSupport":
        if self.maximum <= self.minimum:
            raise ValueError("timing maximum must be greater than minimum")
        return self


class PrashnaTimingWindow(FrozenModel):
    minimum: int = Field(ge=0, le=10_000)
    maximum: int = Field(ge=0, le=10_000)
    unit: Literal["minutes", "hours", "days", "weeks", "months"]
    confidence: float = Field(ge=0.0, le=0.65)


class PrashnaOutcomeGraph(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    profile: PrashnaQuestionProfile | None
    school: str
    gates: tuple[tuple[str, str], ...]
    testimonies: tuple[PrashnaTestimony, ...]
    conflicts: tuple[tuple[str, str], ...]
    judgment: Literal["favorable", "unfavorable", "mixed", "no_answer", "unavailable"]
    outcome_allowed: bool
    score: float = Field(ge=-1.0, le=1.0)
    confidence: float = Field(ge=0.0, le=0.65)
    timing_window: PrashnaTimingWindow | None
    reason_codes: tuple[str, ...]
    source_refs: tuple[str, ...]
    graph_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _judgment_gate(self) -> "PrashnaOutcomeGraph":
        allowed = self.judgment in {"favorable", "unfavorable", "mixed"}
        if self.outcome_allowed != allowed:
            raise ValueError("only bounded judgments may produce outcome prose")
        if self.timing_window is not None and not self.outcome_allowed:
            raise ValueError("blocked outcomes cannot contain timing")
        return self


def _outcome_graph(payload: dict[str, object]) -> PrashnaOutcomeGraph:
    draft = PrashnaOutcomeGraph(**payload, graph_sha256="0" * 64)
    encoded = canonical_json(draft.model_dump(mode="json", exclude={"graph_sha256"}))
    return draft.model_copy(
        update={"graph_sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest()}
    )


def _blocked_prashna_outcome(
    *,
    profile: PrashnaQuestionProfile | None,
    school: str,
    gates: tuple[tuple[str, str], ...],
    judgment: Literal["no_answer", "unavailable"],
    reason_code: str,
    testimonies: tuple[PrashnaTestimony, ...] = (),
    source_refs: tuple[str, ...] = (),
) -> PrashnaOutcomeGraph:
    return _outcome_graph(
        {
            "schema_version": "1.0",
            "profile": profile,
            "school": school,
            "gates": gates,
            "testimonies": testimonies,
            "conflicts": (),
            "judgment": judgment,
            "outcome_allowed": False,
            "score": 0.0,
            "confidence": 0.0,
            "timing_window": None,
            "reason_codes": (reason_code,),
            "source_refs": source_refs,
        }
    )


def evaluate_prashna_outcome(
    radicality: PrashnaRadicalityResult,
    route: PrashnaQuestionRoute,
    geometry: PrashnaAspectGeometryResult | PrashnaBaselineGeometryResult,
    *,
    testimonies: tuple[PrashnaTestimony, ...],
    available_fact_paths: tuple[str, ...],
    timing_support: PrashnaTimingSupport | None = None,
) -> PrashnaOutcomeGraph:
    """Build a bounded judgment only after all upstream gates pass."""

    school = geometry.school
    if radicality.status != "readable" or not radicality.outcome_allowed:
        return _blocked_prashna_outcome(
            profile=route.profile,
            school=school,
            gates=(("radicality", "blocked"),),
            judgment="unavailable",
            reason_code="RADICALITY_BLOCKED",
            source_refs=radicality.source_refs,
        )
    if route.status != "supported":
        return _blocked_prashna_outcome(
            profile=None,
            school=school,
            gates=(("radicality", "passed"), ("significators", "blocked")),
            judgment="unavailable",
            reason_code="QUESTION_PROFILE_NOT_SUPPORTED",
            source_refs=radicality.source_refs,
        )
    if not set(route.required_fact_paths) <= set(available_fact_paths):
        return _blocked_prashna_outcome(
            profile=route.profile,
            school=school,
            gates=(("radicality", "passed"), ("significators", "blocked")),
            judgment="unavailable",
            reason_code="REQUIRED_FACTS_MISSING",
            source_refs=tuple(sorted(set(radicality.source_refs + route.source_refs))),
        )
    geometry_available = (
        geometry.state in {"connected", "unconnected"}
        if isinstance(geometry, PrashnaBaselineGeometryResult)
        else geometry.state in {"applying", "exact", "separating"}
    )
    if not geometry_available:
        return _blocked_prashna_outcome(
            profile=route.profile,
            school=school,
            gates=(
                ("radicality", "passed"),
                ("significators", "passed"),
                ("geometry", "blocked"),
            ),
            judgment="unavailable",
            reason_code="GEOMETRY_UNAVAILABLE",
            source_refs=tuple(
                sorted(
                    set(
                        radicality.source_refs
                        + route.source_refs
                        + geometry.source_refs
                    )
                )
            ),
        )
    ordered_testimonies = tuple(sorted(testimonies, key=lambda item: item.testimony_id))
    common_refs = set(radicality.source_refs + route.source_refs + geometry.source_refs)
    common_refs.update(
        reference
        for testimony in ordered_testimonies
        for reference in testimony.source_refs
    )
    if not ordered_testimonies:
        return _blocked_prashna_outcome(
            profile=route.profile,
            school=school,
            gates=(
                ("radicality", "passed"),
                ("significators", "passed"),
                ("geometry", "passed"),
            ),
            judgment="no_answer",
            reason_code="TESTIMONY_MISSING",
            source_refs=tuple(sorted(common_refs)),
        )

    assistance = [item for item in ordered_testimonies if item.polarity == "assistance"]
    obstacles = [item for item in ordered_testimonies if item.polarity == "obstacle"]
    if isinstance(geometry, PrashnaBaselineGeometryResult):
        geometry_score = 0.2 if geometry.state == "connected" else 0.0
    else:
        geometry_score = 0.2 if geometry.state in {"applying", "exact"} else -0.2
    score = (
        geometry_score
        + sum(item.confidence for item in assistance)
        - sum(item.confidence for item in obstacles)
    )
    score = round(max(-1.0, min(1.0, score)), 6)
    if abs(score) < 0.15:
        judgment = "mixed"
    elif score > 0:
        judgment = "favorable"
    else:
        judgment = "unfavorable"
    conflicts = tuple(
        sorted(
            (left.testimony_id, right.testimony_id)
            for left in obstacles
            for right in assistance
        )
    )
    confidence = round(min(0.65, 0.35 + min(abs(score), 0.3)), 6)
    timing_window = None
    if (
        timing_support is not None
        and not isinstance(geometry, PrashnaBaselineGeometryResult)
        and geometry.state in {"applying", "exact"}
    ):
        common_refs.update(timing_support.source_refs)
        timing_window = PrashnaTimingWindow(
            minimum=timing_support.minimum,
            maximum=timing_support.maximum,
            unit=timing_support.unit,
            confidence=min(confidence, 0.55),
        )
    return _outcome_graph(
        {
            "schema_version": "1.0",
            "profile": route.profile,
            "school": school,
            "gates": (
                ("radicality", "passed"),
                ("significators", "passed"),
                ("geometry", "passed"),
            ),
            "testimonies": ordered_testimonies,
            "conflicts": conflicts,
            "judgment": judgment,
            "outcome_allowed": True,
            "score": score,
            "confidence": confidence,
            "timing_window": timing_window,
            "reason_codes": (),
            "source_refs": tuple(sorted(common_refs)),
        }
    )


class PrashnaPublishedCaseEvaluation(FrozenModel):
    case_id: str
    declared_school: str
    computed_judgment: Literal["positive", "negative", "mixed", "unavailable"]
    matches_published_judgment: bool
    observed_outcome_matches: bool
    product_admissible: bool


def verify_published_case_judgment(
    case: PrashnaPublishedCase,
    *,
    declared_school: str,
    computed_judgment: Literal["positive", "negative", "mixed", "unavailable"],
) -> PrashnaPublishedCaseEvaluation:
    """Compare an offline replay without admitting a high-stakes case to product use."""

    return PrashnaPublishedCaseEvaluation(
        case_id=case.case_id,
        declared_school=declared_school,
        computed_judgment=computed_judgment,
        matches_published_judgment=computed_judgment == case.judgment,
        observed_outcome_matches=case.outcome_traceable,
        product_admissible=case.admissibility == "admitted_safe",
    )


class PrashnaRenderedReport(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    status: Literal["completed", "unavailable"]
    language: Literal["ru", "en"]
    depth: Literal["quick", "full", "deep"]
    graph_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    conclusion: str
    reasoning: tuple[str, ...]
    uncertainty: str
    timing: str | None
    next_clarification: str | None
    disclosure: Literal["not_evaluated"] = "not_evaluated"
    evidence_appendix: tuple[str, ...] | None
    reason_code: str | None

    @model_validator(mode="after")
    def _complete_or_empty(self) -> "PrashnaRenderedReport":
        if self.status == "completed" and (
            not self.reasoning or self.reason_code is not None
        ):
            raise ValueError("completed report requires reasoning and no error")
        if self.status == "unavailable" and (
            self.reasoning or self.reason_code is None
        ):
            raise ValueError("unavailable report cannot contain reasoning")
        return self


def _prashna_graph_identity_valid(graph: PrashnaOutcomeGraph) -> bool:
    payload = graph.model_dump(mode="json", exclude={"graph_sha256"})
    expected = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return expected == graph.graph_sha256


def _safe_evidence_ref(reference: str) -> bool:
    lowered = reference.casefold()
    return not (
        any(marker in lowered for marker in ("private", ".pdf", "token", "secret"))
        or "/" in reference
        or "\\" in reference
        or re.search(r"[<>\r\n]", reference) is not None
    )


def _unavailable_prashna_report(
    graph: PrashnaOutcomeGraph,
    *,
    language: Literal["ru", "en"],
    depth: Literal["quick", "full", "deep"],
    reason_code: str,
) -> PrashnaRenderedReport:
    return PrashnaRenderedReport(
        status="unavailable",
        language=language,
        depth=depth,
        graph_sha256=graph.graph_sha256,
        conclusion=(
            "Проверяемый вывод сейчас недоступен."
            if language == "ru"
            else "A validated conclusion is currently unavailable."
        ),
        reasoning=(),
        uncertainty=(
            "Исходный граф не прошёл обязательную проверку."
            if language == "ru"
            else "The source graph did not pass a required validation gate."
        ),
        timing=None,
        next_clarification=None,
        evidence_appendix=None,
        reason_code=reason_code,
    )


def render_prashna_outcome(
    graph: PrashnaOutcomeGraph,
    *,
    language: Literal["ru", "en"],
    depth: Literal["quick", "full", "deep"],
    include_evidence: bool,
) -> PrashnaRenderedReport:
    """Render only an identity-valid bounded graph; never accept free-form claims."""

    if not _prashna_graph_identity_valid(graph):
        return _unavailable_prashna_report(
            graph,
            language=language,
            depth=depth,
            reason_code="GRAPH_IDENTITY_INVALID",
        )
    if not graph.outcome_allowed:
        return _unavailable_prashna_report(
            graph,
            language=language,
            depth=depth,
            reason_code=graph.reason_codes[0] if graph.reason_codes else "NO_ANSWER",
        )
    if any(not _safe_evidence_ref(reference) for reference in graph.source_refs):
        return _unavailable_prashna_report(
            graph,
            language=language,
            depth=depth,
            reason_code="EVIDENCE_REFERENCE_UNSAFE",
        )

    conclusions = {
        "ru": {
            "favorable": "Граф указывает на ограниченно благоприятную тенденцию.",
            "unfavorable": "Граф указывает на ограниченно неблагоприятную тенденцию.",
            "mixed": "Граф показывает смешанные и противоречивые свидетельства.",
        },
        "en": {
            "favorable": "The graph indicates a bounded favorable tendency.",
            "unfavorable": "The graph indicates a bounded unfavorable tendency.",
            "mixed": "The graph contains mixed and conflicting testimony.",
        },
    }
    assistance = sum(item.polarity == "assistance" for item in graph.testimonies)
    obstacles = sum(item.polarity == "obstacle" for item in graph.testimonies)
    if language == "ru":
        reasoning = [
            f"Пройдено обязательных шлюзов: {len(graph.gates)}.",
            f"Поддерживающих факторов: {assistance}; препятствий: {obstacles}.",
        ]
        if depth == "deep" and graph.conflicts:
            reasoning.append(f"Явных конфликтов в графе: {len(graph.conflicts)}.")
        uncertainty = (
            f"Уверенность ограничена значением {graph.confidence:.2f}; "
            f"школа: {graph.school}."
        )
        next_clarification = "Можно уточнить один уже заданный аспект вопроса."
    else:
        reasoning = [
            f"Required gates passed: {len(graph.gates)}.",
            f"Assistance factors: {assistance}; obstacle factors: {obstacles}.",
        ]
        if depth == "deep" and graph.conflicts:
            reasoning.append(f"Explicit graph conflicts: {len(graph.conflicts)}.")
        uncertainty = (
            f"Confidence is capped at {graph.confidence:.2f}; school: {graph.school}."
        )
        next_clarification = "You may clarify one bounded aspect of the same question."
    if depth == "quick":
        reasoning = reasoning[:1]

    timing = None
    if graph.timing_window is not None:
        window = graph.timing_window
        timing = (
            f"Ограниченное окно: {window.minimum}–{window.maximum} {window.unit}."
            if language == "ru"
            else f"Bounded window: {window.minimum}–{window.maximum} {window.unit}."
        )
    return PrashnaRenderedReport(
        status="completed",
        language=language,
        depth=depth,
        graph_sha256=graph.graph_sha256,
        conclusion=conclusions[language][graph.judgment],
        reasoning=tuple(reasoning),
        uncertainty=uncertainty,
        timing=timing,
        next_clarification=next_clarification,
        evidence_appendix=graph.source_refs if include_evidence else None,
        reason_code=None,
    )


class PrashnaClarificationDecision(FrozenModel):
    action: Literal["reuse_sealed_anchor", "create_new_anchor"]
    anchor_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    reason_code: Literal["BOUNDED_CLARIFICATION", "MATERIAL_MISMATCH"]

    @model_validator(mode="after")
    def _anchor_matches_action(self) -> "PrashnaClarificationDecision":
        if (self.action == "reuse_sealed_anchor") != (self.anchor_sha256 is not None):
            raise ValueError("only bounded clarification may preserve the anchor")
        return self


def decide_prashna_clarification(
    *,
    anchor_sha256: str,
    original_fingerprint: str,
    current_fingerprint: str,
    relation: Literal["bounded_clarification", "material_mismatch"],
) -> PrashnaClarificationDecision:
    """Preserve the sealed moment only for an already-proven bounded clarification."""

    if not all(
        re.fullmatch(r"[0-9a-f]{64}", value)
        for value in (anchor_sha256, original_fingerprint, current_fingerprint)
    ):
        raise ValueError("invalid replay identity")
    if relation == "bounded_clarification":
        return PrashnaClarificationDecision(
            action="reuse_sealed_anchor",
            anchor_sha256=anchor_sha256,
            reason_code="BOUNDED_CLARIFICATION",
        )
    return PrashnaClarificationDecision(
        action="create_new_anchor",
        anchor_sha256=None,
        reason_code="MATERIAL_MISMATCH",
    )


class PrashnaReleaseGate(FrozenModel):
    gate_id: str = Field(min_length=1)
    status: Literal["passed", "failed", "missing"]
    evidence: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _honest_evidence(self) -> "PrashnaReleaseGate":
        if self.status == "passed" and self.evidence is None:
            raise ValueError("passed release gate requires evidence")
        if self.status == "missing" and self.evidence is not None:
            raise ValueError("missing release gate cannot claim evidence")
        return self


class PrashnaReleaseMetrics(FrozenModel):
    published_outcome_case_count: int = Field(ge=0)
    held_out_question_count: int = Field(ge=0)
    material_error_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    no_answer_rate: float | None = Field(default=None, ge=0.0, le=1.0)


class PrashnaReleaseAudit(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    release_id: Literal["full_prashna_v1"]
    corpus_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    compiled_profile_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    admission_state: Literal[
        "blocked_sources", "automated_verified", "experimental_full", "reviewed"
    ]
    gates: tuple[PrashnaReleaseGate, ...]
    metrics: PrashnaReleaseMetrics
    completed_evidence: tuple[str, ...]
    future_outcome_follow_up: tuple[str, ...]
    blockers: tuple[str, ...]
    external_review_missing: bool
    available: bool

    @model_validator(mode="after")
    def _honest_release(self) -> "PrashnaReleaseAudit":
        ids = [gate.gate_id for gate in self.gates]
        if len(ids) != len(set(ids)):
            raise ValueError("release gate IDs must be unique")
        expected_available = self.admission_state in {"experimental_full", "reviewed"}
        if self.available != expected_available:
            raise ValueError("release availability must follow admission state")
        if self.available and (self.compiled_profile_sha256 is None or self.blockers):
            raise ValueError("available release requires a profile and no blockers")
        AdmissionEvaluator.assert_required_gates(
            gates=self.gates,
            required_gate_ids=(
                "source_manifest",
                "radicality_and_anchor_suite",
                "taxonomy_ru_en",
                "geometry_property_suite",
                "outcome_graph_and_privacy",
                "baseline_geometry_admission",
                "published_outcome_cases",
                "held_out_questions",
            ),
            available=self.available,
        )
        if (
            self.compiled_profile_sha256 is None
            and self.admission_state != "blocked_sources"
        ):
            raise ValueError("missing compiled profile is source-blocked")
        if not self.completed_evidence or not self.future_outcome_follow_up:
            raise ValueError(
                "release audit must separate completed and future evidence"
            )
        return self


class PrashnaHeldOutCorpusError(ValueError):
    """The held-out question corpus is malformed, substituted, or unsafe."""


_PRASHNA_ROOT = Path(__file__).resolve().parents[3]
_PRASHNA_HELD_OUT_CORPUS = (
    _PRASHNA_ROOT / "eval/prashna/questions-held-out-v1.json"
)
_PRASHNA_HELD_OUT_MANIFEST = (
    _PRASHNA_ROOT / "eval/prashna/questions-held-out-v1-checksums.json"
)
_PRASHNA_RADICALITY_PROFILE = (
    _PRASHNA_ROOT / "src/jyotish_agent/data/doctrine/prashna-rules.json"
)
_PRASHNA_SOURCE_MANIFEST = (
    _PRASHNA_ROOT / "src/jyotish_agent/data/doctrine/prashna-sources.json"
)
_PRASHNA_PACKAGED_RELEASE = (
    _PRASHNA_ROOT / "src/jyotish_agent/data/doctrine/prashna-release.json"
)
_PRASHNA_HELD_OUT_ID = re.compile(r"^[a-z][a-z0-9_]{2,80}$")


def load_prashna_release_audit(
    *, verify_source_bytes: bool = True
) -> PrashnaReleaseAudit:
    """Load the private release and verify only its admitted baseline bytes."""

    audit = PrashnaReleaseAudit.model_validate_json(
        _PRASHNA_PACKAGED_RELEASE.read_text(encoding="utf-8")
    )
    manifest = load_source_manifest(_PRASHNA_SOURCE_MANIFEST)
    if audit.corpus_manifest_sha256 != manifest.manifest_sha256:
        raise ValueError("PRASHNA_SOURCE_MANIFEST_SUBSTITUTED")
    if audit.compiled_profile_sha256 != prashna_compiled_profile_sha256():
        raise ValueError("PRASHNA_COMPILED_PROFILE_SUBSTITUTED")
    if audit.available and verify_source_bytes:
        radicality = PrashnaRadicalityProfile.model_validate_json(
            _PRASHNA_RADICALITY_PROFILE.read_text(encoding="utf-8")
        )
        required_ids = {item.source_id for item in radicality.criteria}
        required_ids.update(
            rule.source_ref.split(":", 1)[0]
            for rule in load_prashna_baseline_rule_pack().rules
        )
        runtime_sources = tuple(
            source for source in manifest.sources if source.source_id in required_ids
        )
        if {source.source_id for source in runtime_sources} != required_ids:
            raise ValueError("PRASHNA_ADMITTED_SOURCE_MISSING")
        runtime_manifest = SourceManifest(
            schema_version=manifest.schema_version,
            sources=runtime_sources,
        )
        root = Path(
            os.environ.get(
                "JYOTISH_PRIVATE_SOURCES_ROOT",
                str(Path.cwd() / "private_sources"),
            )
        )
        if not SourceVerifier.verify(runtime_manifest, root).ok:
            raise ValueError("PRASHNA_SOURCE_BYTES_UNVERIFIED")
    return audit


def _held_out_json(path: Path, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PrashnaHeldOutCorpusError(f"invalid {label}") from exc
    if not isinstance(value, dict):
        raise PrashnaHeldOutCorpusError(f"invalid {label}")
    return value


def _held_out_keys(
    value: dict[str, object], expected: set[str], label: str
) -> None:
    if set(value) != expected:
        raise PrashnaHeldOutCorpusError(f"{label} has an invalid schema")


def _check_prashna_held_out_checksum(
    corpus_path: Path, manifest_path: Path
) -> None:
    manifest = _held_out_json(manifest_path, "Prashna held-out checksum manifest")
    _held_out_keys(
        manifest,
        {"schema_version", "algorithm", "files"},
        "Prashna held-out checksum manifest",
    )
    files = manifest["files"]
    if (
        manifest["schema_version"] != "1.0"
        or manifest["algorithm"] != "sha256"
        or not isinstance(files, dict)
        or set(files) != {corpus_path.name}
    ):
        raise PrashnaHeldOutCorpusError("invalid Prashna held-out checksum manifest")
    expected = files[corpus_path.name]
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise PrashnaHeldOutCorpusError("invalid Prashna held-out checksum manifest")
    try:
        actual = hashlib.sha256(corpus_path.read_bytes()).hexdigest()
    except OSError as exc:
        raise PrashnaHeldOutCorpusError("invalid Prashna held-out corpus") from exc
    if actual != expected:
        raise PrashnaHeldOutCorpusError("Prashna held-out checksum mismatch")


def _validate_prashna_held_out_corpus(payload: dict[str, object]) -> None:
    _held_out_keys(
        payload,
        {
            "schema_version",
            "corpus_id",
            "authorship",
            "used_for_tuning",
            "public_safe",
            "source_admission_mode",
            "corpus_manifest_sha256",
            "radicality_profile_sha256",
            "cases",
        },
        "Prashna held-out corpus",
    )
    source_manifest = load_source_manifest(_PRASHNA_SOURCE_MANIFEST)
    radicality_sha256 = hashlib.sha256(
        _PRASHNA_RADICALITY_PROFILE.read_bytes()
    ).hexdigest()
    if (
        payload["schema_version"] != "1.0"
        or payload["corpus_id"] != "prashna_questions_held_out_v1"
        or payload["authorship"] != "independently_hand_authored"
        or payload["used_for_tuning"] is not False
        or payload["public_safe"] is not True
        or payload["source_admission_mode"] != "synthetic_test_fixture_only"
        or payload["corpus_manifest_sha256"] != source_manifest.manifest_sha256
        or payload["radicality_profile_sha256"] != radicality_sha256
    ):
        raise PrashnaHeldOutCorpusError("Prashna held-out provenance is invalid")

    cases = payload["cases"]
    if not isinstance(cases, list) or len(cases) < 12:
        raise PrashnaHeldOutCorpusError(
            "Prashna held-out corpus requires at least twelve questions"
        )
    case_ids: list[str] = []
    locales: set[str] = set()
    statuses: set[str] = set()
    profiles: set[str] = set()
    supported_count = 0
    valid_statuses = {
        "supported",
        "unsupported",
        "composite",
        "high_stakes",
        "ambiguous",
    }
    valid_profiles = {profile.value for profile in PrashnaQuestionProfile}
    valid_guidance = {
        "PROCEED",
        "ASK_ONE_MATERIAL_QUESTION",
        "CONSULT_QUALIFIED_PROFESSIONAL",
        "NAME_A_SUPPORTED_LOW_RISK_TOPIC",
        "TOPIC_NOT_SUPPORTED",
    }
    for case in cases:
        if not isinstance(case, dict):
            raise PrashnaHeldOutCorpusError("Prashna held-out case must be an object")
        _held_out_keys(
            case,
            {
                "id",
                "locale",
                "question",
                "route_expected",
                "scenario",
                "outcome_expected",
            },
            "Prashna held-out case",
        )
        case_id, locale, question = case["id"], case["locale"], case["question"]
        if (
            not isinstance(case_id, str)
            or not _PRASHNA_HELD_OUT_ID.fullmatch(case_id)
            or locale not in {"ru", "en"}
            or not isinstance(question, str)
            or not 1 <= len(question) <= 500
            or any(
                marker in question.casefold()
                for marker in ("private_sources", ".pdf", "/users/")
            )
        ):
            raise PrashnaHeldOutCorpusError("Prashna held-out case identity is invalid")

        route_expected = case["route_expected"]
        scenario = case["scenario"]
        outcome_expected = case["outcome_expected"]
        if not all(
            isinstance(value, dict)
            for value in (route_expected, scenario, outcome_expected)
        ):
            raise PrashnaHeldOutCorpusError("Prashna held-out case data is invalid")
        _held_out_keys(
            route_expected,
            {"status", "profile", "guidance_code"},
            "Prashna held-out route expectation",
        )
        route_status = route_expected["status"]
        route_profile = route_expected["profile"]
        if (
            route_status not in valid_statuses
            or route_expected["guidance_code"] not in valid_guidance
            or (
                route_status == "supported"
                and route_profile not in valid_profiles
            )
            or (route_status != "supported" and route_profile is not None)
        ):
            raise PrashnaHeldOutCorpusError(
                "Prashna held-out route expectation is invalid"
            )

        _held_out_keys(
            scenario,
            {"radicality", "geometry", "testimonies", "fact_mode"},
            "Prashna held-out scenario",
        )
        radicality = scenario["radicality"]
        geometry = scenario["geometry"]
        testimonies = scenario["testimonies"]
        if not isinstance(radicality, dict) or not isinstance(geometry, dict):
            raise PrashnaHeldOutCorpusError("Prashna held-out scenario is invalid")
        try:
            PrashnaRadicalityInput.model_validate(radicality)
            geometry_input = {
                key: value for key, value in geometry.items() if key != "source_admitted"
            }
            PrashnaAspectGeometryInput.model_validate(
                {
                    "anchor_sha256": "a" * 64,
                    "body_a": "lagna_lord",
                    "body_b": "primary_house_lord",
                    **geometry_input,
                }
            )
        except ValueError as exc:
            raise PrashnaHeldOutCorpusError(
                "Prashna held-out typed scenario is invalid"
            ) from exc
        if type(geometry.get("source_admitted")) is not bool:
            raise PrashnaHeldOutCorpusError(
                "Prashna held-out geometry admission flag is invalid"
            )
        if scenario["fact_mode"] not in {"complete", "missing"}:
            raise PrashnaHeldOutCorpusError("Prashna held-out fact mode is invalid")
        if not isinstance(testimonies, list):
            raise PrashnaHeldOutCorpusError("Prashna held-out testimonies are invalid")
        for testimony in testimonies:
            if not isinstance(testimony, dict):
                raise PrashnaHeldOutCorpusError(
                    "Prashna held-out testimony is invalid"
                )
            _held_out_keys(
                testimony,
                {"testimony_id", "polarity", "confidence"},
                "Prashna held-out testimony",
            )
            try:
                PrashnaTestimony.model_validate(
                    {
                        **testimony,
                        "fact_refs": ("prashna.lagna.sign",),
                        "source_refs": ("held-out:synthetic-testimony",),
                    }
                )
            except ValueError as exc:
                raise PrashnaHeldOutCorpusError(
                    "Prashna held-out testimony is invalid"
                ) from exc

        _held_out_keys(
            outcome_expected,
            {"judgment", "reason_codes", "outcome_allowed"},
            "Prashna held-out outcome expectation",
        )
        if (
            outcome_expected["judgment"]
            not in {"favorable", "unfavorable", "mixed", "no_answer", "unavailable"}
            or not isinstance(outcome_expected["reason_codes"], list)
            or not all(
                isinstance(code, str) and code
                for code in outcome_expected["reason_codes"]
            )
            or type(outcome_expected["outcome_allowed"]) is not bool
        ):
            raise PrashnaHeldOutCorpusError(
                "Prashna held-out outcome expectation is invalid"
            )

        case_ids.append(case_id)
        locales.add(locale)
        statuses.add(route_status)
        if route_profile is not None:
            profiles.add(route_profile)
        if route_status == "supported":
            supported_count += 1
    if len(case_ids) != len(set(case_ids)):
        raise PrashnaHeldOutCorpusError("duplicate Prashna held-out case ID")
    if (
        locales != {"ru", "en"}
        or statuses != valid_statuses
        or profiles != valid_profiles
        or supported_count < 8
    ):
        raise PrashnaHeldOutCorpusError(
            "Prashna held-out corpus has incomplete route coverage"
        )


def evaluate_prashna_held_out_questions(
    *,
    corpus_path: Path = _PRASHNA_HELD_OUT_CORPUS,
    manifest_path: Path = _PRASHNA_HELD_OUT_MANIFEST,
    allow_held_out: bool = False,
) -> dict[str, object]:
    """Evaluate a sealed question set without promoting synthetic source fixtures."""
    if not allow_held_out:
        raise ValueError("Prashna held-out execution requires allow_held_out=True")
    _check_prashna_held_out_checksum(corpus_path, manifest_path)
    corpus = _held_out_json(corpus_path, "Prashna held-out corpus")
    _validate_prashna_held_out_corpus(corpus)
    radicality_profile = PrashnaRadicalityProfile.model_validate_json(
        _PRASHNA_RADICALITY_PROFILE.read_text(encoding="utf-8")
    )

    failures: list[dict[str, object]] = []
    covered_statuses: set[str] = set()
    covered_profiles: set[str] = set()
    supported_count = 0
    no_answer_count = 0
    cases = corpus["cases"]
    assert isinstance(cases, list)
    for case in cases:
        assert isinstance(case, dict)
        route = classify_prashna_question(str(case["question"]))
        scenario = case["scenario"]
        assert isinstance(scenario, dict)
        radicality_payload = scenario["radicality"]
        geometry_payload = scenario["geometry"]
        testimonies_payload = scenario["testimonies"]
        assert isinstance(radicality_payload, dict)
        assert isinstance(geometry_payload, dict)
        assert isinstance(testimonies_payload, list)

        radicality = evaluate_prashna_radicality(
            PrashnaRadicalityInput.model_validate(radicality_payload),
            radicality_profile,
        )
        source_admitted = bool(geometry_payload["source_admitted"])
        geometry_profile = prashna_aspect_profile(
            "tajika_nilakanthi_overlay"
        ).model_copy(
            update={
                "source_admitted": source_admitted,
                "source_refs": (
                    ("held-out:synthetic-tajika-fixture",)
                    if source_admitted
                    else ()
                ),
            }
        )
        geometry = calculate_prashna_aspect_geometry(
            PrashnaAspectGeometryInput.model_validate(
                {
                    "anchor_sha256": "a" * 64,
                    "body_a": "lagna_lord",
                    "body_b": "primary_house_lord",
                    **{
                        key: value
                        for key, value in geometry_payload.items()
                        if key != "source_admitted"
                    },
                }
            ),
            geometry_profile,
        )
        testimonies = tuple(
            PrashnaTestimony.model_validate(
                {
                    **testimony,
                    "fact_refs": ("prashna.lagna.sign",),
                    "source_refs": ("held-out:synthetic-testimony",),
                }
            )
            for testimony in testimonies_payload
        )
        available_fact_paths = (
            route.required_fact_paths
            if scenario["fact_mode"] == "complete"
            else ("prashna.lagna.sign",)
        )
        outcome = evaluate_prashna_outcome(
            radicality,
            route,
            geometry,
            testimonies=testimonies,
            available_fact_paths=available_fact_paths,
        )

        observed = {
            "route": {
                "status": route.status,
                "profile": route.profile.value if route.profile is not None else None,
                "guidance_code": route.guidance_code,
            },
            "outcome": {
                "judgment": outcome.judgment,
                "reason_codes": list(outcome.reason_codes),
                "outcome_allowed": outcome.outcome_allowed,
            },
        }
        expected = {
            "route": case["route_expected"],
            "outcome": case["outcome_expected"],
        }
        if observed != expected:
            failures.append(
                {
                    "case_id": case["id"],
                    "expected": expected,
                    "observed": observed,
                }
            )
        covered_statuses.add(route.status)
        if route.profile is not None:
            covered_profiles.add(route.profile.value)
        if case["route_expected"]["status"] == "supported":
            supported_count += 1
            if outcome.judgment == "no_answer":
                no_answer_count += 1

    question_count = len(cases)
    failed_count = len(failures)
    return {
        "corpus_id": corpus["corpus_id"],
        "corpus_sha256": hashlib.sha256(corpus_path.read_bytes()).hexdigest(),
        "corpus_manifest_sha256": corpus["corpus_manifest_sha256"],
        "radicality_profile_sha256": corpus["radicality_profile_sha256"],
        "source_admission_mode": corpus["source_admission_mode"],
        "status": "failed" if failures else "passed",
        "question_count": question_count,
        "passed_count": question_count - failed_count,
        "failed_count": failed_count,
        "material_error_rate": round(failed_count / question_count, 6),
        "no_answer_rate": round(no_answer_count / supported_count, 6),
        "covered_route_statuses": sorted(covered_statuses),
        "covered_profiles": sorted(covered_profiles),
        "failures": failures,
    }
