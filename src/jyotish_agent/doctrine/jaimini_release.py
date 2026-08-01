"""Restricted private Full Jaimini renderer over signed structural facts.

This module intentionally does not activate the legacy broad rule map or either
named overlay.  It renders only six source-bound structural factors and keeps the
school-conflicted timing branch visibly unavailable.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from pydantic import Field, model_validator

from ..interpretations import iter_jaimini_fact_atoms
from ..jaimini_models import JaiminiCompletedResult, JaiminiResult
from ..research_store import canonical_json
from ..signing import get_cached_domain_artifact, verify_domain_artifact
from .jaimini_pack import (
    JaiminiPrivateBaselineProfile,
    JaiminiPrivateClaim,
    JaiminiPrivateSourceRef,
    JaiminiReleaseAudit,
    jaimini_compiled_profile_sha256,
    load_jaimini_private_baseline_profile,
)
from .models import FrozenModel


JaiminiFullMode = Literal["quick", "full", "deep", "inspection"]
JaiminiLocale = Literal["ru", "en"]
JaiminiFullTopic = Literal["self", "career", "relationships", "timing"]


class JaiminiRenderedFactor(FrozenModel):
    claim_id: str
    label: str
    value: str
    fact_ref: str = Field(pattern=r"^jaimini\.[A-Za-z0-9_.]+$")
    symbolic_role: str | None = None
    confidence: float | None = Field(default=None, gt=0.0, le=0.65)


class JaiminiRenderedSection(FrozenModel):
    topic: JaiminiFullTopic
    status: Literal["completed", "partial", "unavailable"]
    factors: tuple[JaiminiRenderedFactor, ...]
    reason_code: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _coherent_section(self) -> "JaiminiRenderedSection":
        if self.status == "completed" and (not self.factors or self.reason_code):
            raise ValueError("completed topic requires factors and no reason")
        if self.status == "unavailable" and (
            self.factors or self.reason_code is None
        ):
            raise ValueError("unavailable topic requires a reason and no factors")
        if self.status == "partial" and (not self.factors or self.reason_code is None):
            raise ValueError("partial topic requires factors and a reason")
        return self


class JaiminiInspectionClaim(FrozenModel):
    claim_id: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    fact_ref: str = Field(pattern=r"^jaimini\.[A-Za-z0-9_.]+$")
    source_refs: tuple[JaiminiPrivateSourceRef, ...]


class JaiminiInspection(FrozenModel):
    compiled_profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fact_artifact_id: str = Field(pattern=r"^jya_[0-9a-f]{24}$")
    fact_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cross_check_policy: str
    claims: tuple[JaiminiInspectionClaim, ...]


class JaiminiRenderedReport(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    profile_id: Literal["full_jaimini_private_baseline_v1"]
    mode: JaiminiFullMode
    locale: JaiminiLocale
    status: Literal["completed"] = "completed"
    headline: str
    sections: tuple[JaiminiRenderedSection, ...]
    limitations: tuple[str, ...]
    method_notes: tuple[str, ...]
    quarantined_rule_ids: tuple[str, ...]
    external_review_missing: Literal[True]
    inspection: JaiminiInspection | None = None
    visible_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _depth_contract(self) -> "JaiminiRenderedReport":
        if self.mode == "quick" and (self.method_notes or self.quarantined_rule_ids):
            raise ValueError("quick report cannot include deep method material")
        if self.mode == "full" and self.quarantined_rule_ids:
            raise ValueError("full report cannot include deep quarantine detail")
        if self.inspection is not None and self.mode != "inspection":
            raise ValueError("source appendix belongs only to inspection mode")
        return self


@dataclass(frozen=True)
class JaiminiFullExecution:
    status: Literal["completed", "unavailable", "needs_input", "incomplete"]
    report: JaiminiRenderedReport | None
    reason_code: str | None = None


def _localized(value: JaiminiPrivateClaim, locale: JaiminiLocale, field: str) -> str:
    return str(getattr(value, f"{field}_{locale}"))


def _report_hash(report: JaiminiRenderedReport) -> str:
    payload = report.model_dump(
        mode="json", exclude={"visible_text_sha256"}, exclude_none=True
    )
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def validate_jaimini_visible_report(report: JaiminiRenderedReport) -> list[str]:
    """Detect any mutation after the deterministic renderer seals its output."""

    if report.visible_text_sha256 != _report_hash(report):
        return ["VISIBLE_REPORT_MISMATCH"]
    return []


def _method_notes(
    mode: JaiminiFullMode, locale: JaiminiLocale
) -> tuple[str, ...]:
    if mode == "quick":
        return ()
    ru = (
        "Значения взяты только из подписанного расчётного артефакта.",
        "Baseline использует семикраковую схему Nilakantha; Sanjay Rath указан только как независимая сверка, не как активный overlay.",
        "Роль фактора описывается отдельно от его вычисленного значения; выводы о событиях, профессии или браке не компилировались.",
    )
    en = (
        "Values come only from the signed calculation artifact.",
        "The baseline uses the seven-karaka Nilakantha scheme; Sanjay Rath is independent context, not an active overlay.",
        "Factor roles are kept separate from computed values; event, career, and marriage predictions were not compiled.",
    )
    notes = ru if locale == "ru" else en
    return notes[:2] if mode == "full" else notes


def _limitations(locale: JaiminiLocale) -> tuple[str, ...]:
    if locale == "ru":
        return (
            "Это частный экспериментальный символический отчёт, а не медицинский, юридический, финансовый или детерминистический прогноз.",
            "Внешний специалист ещё не проверил профиль; уверенность ограничена 0.65.",
            "Интерпретации планет в знаках и предсказания событий не входят в этот baseline.",
        )
    return (
        "This is a private experimental symbolic report, not medical, legal, financial, or deterministic advice.",
        "The profile has not yet received external specialist review; confidence is capped at 0.65.",
        "Planet-in-sign interpretations and event predictions are outside this baseline.",
    )


def _section_note(topic: str, locale: JaiminiLocale) -> str:
    labels = {
        "ru": {
            "self": "Структурные факторы темы самости; без характеристики личности по планете или знаку.",
            "career": "Структурные факторы деятельности и проявленного статуса; без выбора профессии.",
            "relationships": "Структурные факторы партнёрской роли и союза; без прогноза отношений.",
        },
        "en": {
            "self": "Structural self-topic factors, without personality claims from the planet or sign.",
            "career": "Structural activity and manifested-status factors, without choosing a profession.",
            "relationships": "Structural partner-role and union factors, without a relationship forecast.",
        },
    }
    return labels[locale][topic]


def _inspection(
    *,
    profile: JaiminiPrivateBaselineProfile,
    audit: JaiminiReleaseAudit,
    base: JaiminiCompletedResult,
    visible_claims: tuple[JaiminiPrivateClaim, ...],
) -> JaiminiInspection:
    return JaiminiInspection(
        compiled_profile_sha256=jaimini_compiled_profile_sha256(),
        source_manifest_sha256=audit.corpus_manifest_sha256,
        fact_artifact_id=base.artifact_id,
        fact_artifact_sha256=base.artifact_sha256,
        cross_check_policy=profile.cross_check_policy,
        claims=tuple(
            JaiminiInspectionClaim(
                claim_id=claim.claim_id,
                fact_ref=claim.fact_path,
                source_refs=claim.source_refs,
            )
            for claim in visible_claims
        ),
    )


def execute_jaimini_full(
    base: JaiminiResult,
    *,
    audit: JaiminiReleaseAudit,
    topics: tuple[JaiminiFullTopic, ...],
    locale: JaiminiLocale,
    mode: JaiminiFullMode,
    include_evidence: bool,
) -> JaiminiFullExecution:
    """Render the immutable private profile from the just-created signed artifact."""

    if base.status != "completed":
        return JaiminiFullExecution(
            status="incomplete" if base.status == "incomplete" else base.status,
            report=None,
            reason_code=(
                getattr(base, "error_code", None) or "BASE_CALCULATION_UNAVAILABLE"
            ),
        )
    assert isinstance(base, JaiminiCompletedResult)
    artifact = get_cached_domain_artifact(base.artifact_token)
    if (
        artifact is None
        or not verify_domain_artifact(artifact)
        or artifact.get("mode") != "jaimini"
        or artifact.get("artifact_id") != base.artifact_id
        or artifact.get("artifact_sha256") != base.artifact_sha256
        or artifact.get("rule_profile_sha256")
        != base.provenance.rule_profile_sha256
        or artifact.get("source_map_sha256") != base.provenance.source_map_sha256
        or artifact.get("source_admission_sha256")
        != base.provenance.source_admission_sha256
    ):
        return JaiminiFullExecution(
            status="incomplete",
            report=None,
            reason_code="FACT_ARTIFACT_INVALID",
        )
    raw_facts = artifact.get("facts")
    if not isinstance(raw_facts, list):
        return JaiminiFullExecution(
            status="incomplete",
            report=None,
            reason_code="FACT_ARTIFACT_INVALID",
        )
    try:
        atoms = iter_jaimini_fact_atoms(raw_facts)
    except ValueError:
        return JaiminiFullExecution(
            status="incomplete", report=None, reason_code="FACT_ARTIFACT_INVALID"
        )
    stability = {
        str(item.get("fact_id")): item.get("stability")
        for item in raw_facts
        if isinstance(item, dict)
    }

    profile = load_jaimini_private_baseline_profile()
    returned_atoms = iter_jaimini_fact_atoms(
        [
            fact.model_dump(mode="json")
            for section in base.sections
            for fact in section.facts
        ]
    )
    if any(
        returned_atoms.get(claim.fact_path) != atoms.get(claim.fact_path)
        for claim in profile.claims
    ):
        return JaiminiFullExecution(
            status="incomplete",
            report=None,
            reason_code="FACT_ARTIFACT_INVALID",
        )
    sections: list[JaiminiRenderedSection] = []
    visible_claims: list[JaiminiPrivateClaim] = []
    for topic in topics:
        if topic == "timing":
            unavailable = profile.unavailable_topics[0]
            sections.append(
                JaiminiRenderedSection(
                    topic="timing",
                    status="unavailable",
                    factors=(),
                    reason_code=unavailable.reason_code,
                    note=(
                        unavailable.reason_ru
                        if locale == "ru"
                        else unavailable.reason_en
                    ),
                )
            )
            continue
        claims = tuple(claim for claim in profile.claims if claim.topic == topic)
        available_claims = tuple(
            claim
            for claim in claims
            if claim.fact_path in atoms
            and stability.get(claim.fact_path) != "unstable"
        )
        if not available_claims:
            sections.append(
                JaiminiRenderedSection(
                    topic=topic,
                    status="unavailable",
                    factors=(),
                    reason_code="NO_STABLE_SOURCE_BOUND_FACTORS",
                    note=(
                        "Факторы меняются в указанном диапазоне времени рождения."
                        if locale == "ru"
                        else "The factors change across the supplied birth-time range."
                    ),
                )
            )
            continue
        missing = len(available_claims) != len(claims)
        visible_claims.extend(available_claims)
        factors = tuple(
            JaiminiRenderedFactor(
                claim_id=claim.claim_id,
                label=_localized(claim, locale, "label"),
                value=atoms[claim.fact_path],
                fact_ref=claim.fact_path,
                symbolic_role=(
                    _localized(claim, locale, "meaning")
                    if mode != "quick"
                    else None
                ),
                confidence=claim.confidence if mode != "quick" else None,
            )
            for claim in available_claims
        )
        sections.append(
            JaiminiRenderedSection(
                topic=topic,
                status="partial" if missing else "completed",
                factors=factors,
                reason_code="BIRTH_TIME_SENSITIVE_FACTS_SUPPRESSED" if missing else None,
                note=_section_note(topic, locale) if mode != "quick" else None,
            )
        )

    headline = (
        "Ограниченный source-bound отчёт Jaimini"
        if locale == "ru"
        else "Bounded source-bound Jaimini report"
    )
    report = JaiminiRenderedReport(
        profile_id=profile.profile_id,
        mode=mode,
        locale=locale,
        headline=headline,
        sections=tuple(sections),
        limitations=_limitations(locale),
        method_notes=_method_notes(mode, locale),
        quarantined_rule_ids=(
            profile.quarantined_rule_ids if mode in {"deep", "inspection"} else ()
        ),
        external_review_missing=True,
        inspection=(
            _inspection(
                profile=profile,
                audit=audit,
                base=base,
                visible_claims=tuple(visible_claims),
            )
            if mode == "inspection" and include_evidence
            else None
        ),
        visible_text_sha256="0" * 64,
    )
    report = report.model_copy(update={"visible_text_sha256": _report_hash(report)})
    if validate_jaimini_visible_report(report):  # pragma: no cover - constructor seal
        return JaiminiFullExecution(
            status="incomplete", report=None, reason_code="VISIBLE_REPORT_INVALID"
        )
    return JaiminiFullExecution(status="completed", report=report)
