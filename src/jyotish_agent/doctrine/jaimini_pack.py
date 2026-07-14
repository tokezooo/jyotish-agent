"""Source-bound Full Jaimini release orchestration.

The first slice is deliberately an acquisition ledger rather than a doctrine
shortcut: an absent book can never become coverage merely because its title is
known. Later Jaimini slices consume this same verified corpus identity.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from .models import FrozenModel, ScanQuality
from .sources import SourceId, SourceManifest, SourceVerificationReport


class JaiminiCorpusRequirement(StrEnum):
    SANSKRIT_UPADESA_SUTRAS = "sanskrit_upadesa_sutras"
    NILAKANTHA_SUBODHINI_TRANSLATION = "nilakantha_subodhini_translation"
    INDEPENDENT_TRANSLATION = "independent_translation"
    PRACTICAL_CHARA_DASHA = "practical_chara_dasha"
    PUBLISHED_WORKED_CHARTS = "published_worked_charts"
    SANJAY_RATH_OVERLAY = "sanjay_rath_overlay"
    KN_RAO_OVERLAY = "kn_rao_overlay"


class JaiminiCorpusRequirementRecord(FrozenModel):
    requirement: JaiminiCorpusRequirement
    source_ids: tuple[SourceId, ...] = ()
    topics: tuple[str, ...] = ()
    worked_chart_count: int = Field(default=0, ge=0)
    acquisition_blocker: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _honest_acquisition_state(self) -> "JaiminiCorpusRequirementRecord":
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("source_ids must be unique")
        if not self.source_ids and self.acquisition_blocker is None:
            raise ValueError("missing requirements need an acquisition blocker")
        if self.source_ids and self.acquisition_blocker is not None:
            raise ValueError("acquired requirements cannot retain an acquisition blocker")
        if (
            self.requirement != JaiminiCorpusRequirement.PUBLISHED_WORKED_CHARTS
            and self.worked_chart_count
        ):
            raise ValueError("worked_chart_count belongs only to the worked-chart requirement")
        return self


class JaiminiCorpusCatalog(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    required_worked_chart_count: int = Field(ge=20, le=30)
    required_topics: tuple[str, ...] = Field(min_length=1)
    requirements: tuple[JaiminiCorpusRequirementRecord, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _complete_catalog(self) -> "JaiminiCorpusCatalog":
        requirements = [item.requirement for item in self.requirements]
        if len(requirements) != len(set(requirements)):
            raise ValueError("duplicate corpus requirement")
        if set(requirements) != set(JaiminiCorpusRequirement):
            raise ValueError("catalog must declare every Jaimini corpus requirement")
        if len(set(self.required_topics)) != len(self.required_topics):
            raise ValueError("required_topics must be unique")
        unknown_topics = {
            topic
            for item in self.requirements
            for topic in item.topics
            if topic not in self.required_topics
        }
        if unknown_topics:
            raise ValueError("requirement references an unknown topic")
        return self


class JaiminiCorpusCoverage(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    manifest_sha256: str
    verified_source_ids: tuple[SourceId, ...]
    unverified_source_ids: tuple[SourceId, ...]
    covered_requirements: tuple[JaiminiCorpusRequirement, ...]
    missing_requirements: tuple[JaiminiCorpusRequirement, ...]
    covered_topics: tuple[str, ...]
    missing_topics: tuple[str, ...]
    low_quality_source_ids: tuple[SourceId, ...]
    verified_worked_chart_count: int = Field(ge=0)
    missing_worked_chart_count: int = Field(ge=0)
    acquisition_blockers: tuple[str, ...]
    ready: bool


def build_jaimini_corpus_coverage(
    manifest: SourceManifest,
    verification: SourceVerificationReport,
    catalog: JaiminiCorpusCatalog,
) -> JaiminiCorpusCoverage:
    """Build privacy-safe coverage from verified bytes, never from titles alone."""

    manifest_ids = {source.source_id for source in manifest.sources}
    catalog_ids = {
        source_id for item in catalog.requirements for source_id in item.source_ids
    }
    unknown = catalog_ids - manifest_ids
    if unknown:
        raise ValueError("corpus catalog references a source absent from the manifest")

    verified = set(verification.verified_source_ids)
    covered: list[JaiminiCorpusRequirement] = []
    missing: list[JaiminiCorpusRequirement] = []
    covered_topics: set[str] = set()
    worked_charts = 0
    blockers: list[str] = []

    for item in sorted(catalog.requirements, key=lambda entry: entry.requirement.value):
        fulfilled = bool(item.source_ids) and set(item.source_ids) <= verified
        if fulfilled:
            covered.append(item.requirement)
            covered_topics.update(item.topics)
            worked_charts += item.worked_chart_count
        else:
            missing.append(item.requirement)
            if item.acquisition_blocker:
                blockers.append(f"{item.requirement.value}: {item.acquisition_blocker}")
            elif item.source_ids:
                blockers.append(
                    f"{item.requirement.value}: declared source bytes did not verify"
                )

    unverified = manifest_ids - verified
    low_quality = sorted(
        source.source_id
        for source in manifest.sources
        if source.scan_quality == ScanQuality.POOR
    )
    missing_topics = set(catalog.required_topics) - covered_topics
    missing_worked_charts = max(0, catalog.required_worked_chart_count - worked_charts)
    ready = not missing and not missing_topics and missing_worked_charts == 0

    return JaiminiCorpusCoverage(
        manifest_sha256=manifest.manifest_sha256,
        verified_source_ids=tuple(sorted(verified)),
        unverified_source_ids=tuple(sorted(unverified)),
        covered_requirements=tuple(sorted(covered, key=lambda item: item.value)),
        missing_requirements=tuple(sorted(missing, key=lambda item: item.value)),
        covered_topics=tuple(sorted(covered_topics)),
        missing_topics=tuple(sorted(missing_topics)),
        low_quality_source_ids=tuple(low_quality),
        verified_worked_chart_count=worked_charts,
        missing_worked_chart_count=missing_worked_charts,
        acquisition_blockers=tuple(sorted(blockers)),
        ready=ready,
    )


def render_jaimini_corpus_coverage(report: JaiminiCorpusCoverage) -> dict[str, object]:
    """Return a deterministic projection containing no local filenames or paths."""

    return report.model_dump(mode="json")

