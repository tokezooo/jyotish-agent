"""Source-bound corpus ledger for the Expanded Muhūrta release.

The ledger verifies locally held source bytes, keeps baseline, commentary, and
modern overlay roles separate, and never turns a worked illustration into an
observed outcome claim.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from .models import FrozenModel
from .sources import SourceId, SourceManifest, SourceVerificationReport


class MuhurtaCorpusRequirement(StrEnum):
    MUHURTA_CINTAMANI = "muhurta_cintamani"
    KALAPRAKASIKA = "kalaprakasika"
    PANCHANGA_DOSA_REFERENCE = "panchanga_dosa_reference"
    MODERN_OVERLAY = "modern_overlay"
    PUBLISHED_WORKED_ELECTIONS = "published_worked_elections"


class MuhurtaCorpusRequirementRecord(FrozenModel):
    requirement: MuhurtaCorpusRequirement
    school_role: Literal["baseline", "commentary", "overlay", "worked_examples"]
    source_ids: tuple[SourceId, ...] = ()
    rule_topics: tuple[str, ...] = ()
    applicable_safe_profiles: tuple[str, ...] = ()
    acquisition_blocker: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _coherent(self) -> "MuhurtaCorpusRequirementRecord":
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("source_ids must be unique")
        if not self.source_ids and not self.acquisition_blocker:
            raise ValueError("a source-free requirement needs an acquisition blocker")
        if len(set(self.rule_topics)) != len(self.rule_topics):
            raise ValueError("rule_topics must be unique")
        if len(set(self.applicable_safe_profiles)) != len(self.applicable_safe_profiles):
            raise ValueError("applicable_safe_profiles must be unique")
        return self


class MuhurtaCorpusCatalog(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    safe_profiles: tuple[str, ...] = Field(min_length=6)
    unsupported_high_stakes_profiles: tuple[str, ...] = Field(min_length=1)
    requirements: tuple[MuhurtaCorpusRequirementRecord, ...] = Field(min_length=5)

    @model_validator(mode="after")
    def _complete_separated_catalog(self) -> "MuhurtaCorpusCatalog":
        requirements = [item.requirement for item in self.requirements]
        if len(requirements) != len(set(requirements)):
            raise ValueError("duplicate corpus requirement")
        if set(requirements) != set(MuhurtaCorpusRequirement):
            raise ValueError("catalog must declare every Muhurta corpus requirement")
        safe = set(self.safe_profiles)
        if safe & set(self.unsupported_high_stakes_profiles):
            raise ValueError("safe and high-stakes profiles must be disjoint")
        baseline = self.requirement(MuhurtaCorpusRequirement.MUHURTA_CINTAMANI)
        commentary = self.requirement(MuhurtaCorpusRequirement.KALAPRAKASIKA)
        overlay = self.requirement(MuhurtaCorpusRequirement.MODERN_OVERLAY)
        if {baseline.school_role, commentary.school_role, overlay.school_role} != {
            "baseline",
            "commentary",
            "overlay",
        }:
            raise ValueError("baseline, commentary, and overlay roles must stay explicit")
        for item in self.requirements:
            if not set(item.applicable_safe_profiles) <= safe:
                raise ValueError("requirement references an undeclared safe profile")
        covered = {
            profile
            for item in self.requirements
            if item.requirement != MuhurtaCorpusRequirement.MODERN_OVERLAY
            for profile in item.applicable_safe_profiles
        }
        if covered != safe:
            raise ValueError("classical requirements must map every safe profile")
        return self

    def requirement(
        self, requirement: MuhurtaCorpusRequirement
    ) -> MuhurtaCorpusRequirementRecord:
        return next(item for item in self.requirements if item.requirement == requirement)


class MuhurtaWorkedExample(FrozenModel):
    example_id: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    source_id: SourceId
    profile: str = Field(min_length=1)
    example_kind: Literal["worked_rule_illustration"]
    source_pdf_pages: tuple[int, ...] = Field(min_length=1)
    source_printed_pages: tuple[int, ...] = Field(min_length=1)
    rule_topics: tuple[str, ...] = Field(min_length=1)
    observed_outcome_claimed: Literal[False]

    @model_validator(mode="after")
    def _paired_pages(self) -> "MuhurtaWorkedExample":
        if len(self.source_pdf_pages) != len(self.source_printed_pages):
            raise ValueError("PDF and printed page anchors must pair one-to-one")
        if len(set(self.source_pdf_pages)) != len(self.source_pdf_pages):
            raise ValueError("source_pdf_pages must be unique")
        return self


class MuhurtaWorkedExampleCatalog(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    examples: tuple[MuhurtaWorkedExample, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def _unique_examples(self) -> "MuhurtaWorkedExampleCatalog":
        ids = [item.example_id for item in self.examples]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate worked example")
        return self


class MuhurtaCorpusCoverage(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    manifest_sha256: str
    verified_source_ids: tuple[SourceId, ...]
    unverified_source_ids: tuple[SourceId, ...]
    covered_requirements: tuple[MuhurtaCorpusRequirement, ...]
    missing_requirements: tuple[MuhurtaCorpusRequirement, ...]
    verified_worked_example_count: int = Field(ge=0)
    covered_safe_profiles: tuple[str, ...]
    unsupported_high_stakes_profiles: tuple[str, ...]
    acquisition_blockers: tuple[str, ...]
    ready: bool


def build_muhurta_corpus_coverage(
    manifest: SourceManifest,
    verification: SourceVerificationReport,
    catalog: MuhurtaCorpusCatalog,
    examples: MuhurtaWorkedExampleCatalog,
) -> MuhurtaCorpusCoverage:
    manifest_ids = {source.source_id for source in manifest.sources}
    referenced_ids = {
        source_id for item in catalog.requirements for source_id in item.source_ids
    } | {item.source_id for item in examples.examples}
    if referenced_ids - manifest_ids:
        raise ValueError("Muhurta catalog references a source absent from the manifest")

    verified = set(verification.verified_source_ids)
    verified_examples = sum(item.source_id in verified for item in examples.examples)
    covered: list[MuhurtaCorpusRequirement] = []
    missing: list[MuhurtaCorpusRequirement] = []
    blockers: list[str] = []
    profiles: set[str] = set()
    for item in sorted(catalog.requirements, key=lambda value: value.requirement.value):
        fulfilled = bool(item.source_ids) and set(item.source_ids) <= verified
        if item.requirement == MuhurtaCorpusRequirement.PUBLISHED_WORKED_ELECTIONS:
            fulfilled = fulfilled and verified_examples >= 2
        if fulfilled:
            covered.append(item.requirement)
            profiles.update(item.applicable_safe_profiles)
        else:
            missing.append(item.requirement)
            blockers.append(
                f"{item.requirement.value}: "
                f"{item.acquisition_blocker or 'declared source bytes did not verify'}"
            )

    return MuhurtaCorpusCoverage(
        manifest_sha256=manifest.manifest_sha256,
        verified_source_ids=tuple(sorted(verified)),
        unverified_source_ids=tuple(sorted(manifest_ids - verified)),
        covered_requirements=tuple(sorted(covered, key=lambda item: item.value)),
        missing_requirements=tuple(sorted(missing, key=lambda item: item.value)),
        verified_worked_example_count=verified_examples,
        covered_safe_profiles=tuple(sorted(profiles)),
        unsupported_high_stakes_profiles=tuple(
            sorted(catalog.unsupported_high_stakes_profiles)
        ),
        acquisition_blockers=tuple(sorted(blockers)),
        ready=not missing,
    )


def render_muhurta_corpus_coverage(
    report: MuhurtaCorpusCoverage,
) -> dict[str, object]:
    """Return a deterministic projection without source paths or source text."""

    return report.model_dump(mode="json")
