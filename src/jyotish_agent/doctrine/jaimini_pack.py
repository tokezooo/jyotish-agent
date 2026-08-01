"""Source-bound Full Jaimini release orchestration.

The first slice is deliberately an acquisition ledger rather than a doctrine
shortcut: an absent book can never become coverage merely because its title is
known. Later Jaimini slices consume this same verified corpus identity.
"""

from __future__ import annotations

import hashlib
import datetime as dt
import json
import os
import re
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from ..research_store import canonical_json
from .evaluation import AdmissionEvaluator, REQUIRED_AUTOMATED_GATES
from .evidence import FragmentRef, SourceFragment
from .graph import AnalysisGraph
from .models import FrozenModel, ScanQuality
from .sources import (
    Sha256,
    SourceId,
    SourceManifest,
    SourceVerifier,
    SourceVerificationReport,
    load_source_manifest,
)


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
            raise ValueError(
                "acquired requirements cannot retain an acquisition blocker"
            )
        if (
            self.requirement != JaiminiCorpusRequirement.PUBLISHED_WORKED_CHARTS
            and self.worked_chart_count
        ):
            raise ValueError(
                "worked_chart_count belongs only to the worked-chart requirement"
            )
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


class JaiminiRuleStatus(StrEnum):
    ANCHORED_UNREVIEWED = "anchored_unreviewed"
    QUARANTINED_MISSING_ANCHOR = "quarantined_missing_anchor"
    QUARANTINED_CONFLICT = "quarantined_conflict"
    ADMITTED = "admitted"


class JaiminiSourceAnchor(FrozenModel):
    pdf_page: int = Field(ge=1)
    printed_page: int
    sutra: str = Field(min_length=1)
    fragment_sha256: Sha256


class JaiminiRuleCandidate(FrozenModel):
    rule_id: str = Field(pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+$")
    school: str = Field(min_length=1)
    source_id: SourceId
    fact_families: tuple[str, ...] = Field(min_length=1)
    anchor: JaiminiSourceAnchor | None = None
    status: JaiminiRuleStatus
    ambiguity: str | None = Field(default=None, min_length=1)
    discrepancy: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _anchor_matches_status(self) -> "JaiminiRuleCandidate":
        anchored = self.status in {
            JaiminiRuleStatus.ANCHORED_UNREVIEWED,
            JaiminiRuleStatus.ADMITTED,
        }
        if anchored and self.anchor is None:
            raise ValueError("anchored or admitted candidates require an exact anchor")
        if self.status == JaiminiRuleStatus.QUARANTINED_MISSING_ANCHOR:
            if self.anchor is not None or self.discrepancy is None:
                raise ValueError(
                    "missing-anchor quarantine requires only a discrepancy"
                )
        if self.status == JaiminiRuleStatus.QUARANTINED_CONFLICT and (
            self.anchor is None or self.discrepancy is None
        ):
            raise ValueError("conflict quarantine requires an anchor and discrepancy")
        return self


class JaiminiRuleInventory(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    school: Literal["nilakantha_baseline"]
    candidates: tuple[JaiminiRuleCandidate, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _coherent_inventory(self) -> "JaiminiRuleInventory":
        ids = [candidate.rule_id for candidate in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate Jaimini rule candidate")
        if any(candidate.school != self.school for candidate in self.candidates):
            raise ValueError("baseline inventory cannot blend schools")
        if any(candidate.anchor is None for candidate in self.candidates):
            raise ValueError("baseline inventory candidates require exact source anchors")
        return self

    @property
    def inventory_sha256(self) -> str:
        payload = self.model_dump(mode="json")
        payload["candidates"] = sorted(
            payload["candidates"], key=lambda candidate: candidate["rule_id"]
        )
        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


class JaiminiBaselineFragmentBinding(FrozenModel):
    """Bind a baseline candidate to text-free, content-addressed source evidence."""

    binding_id: str = Field(pattern=r"^bind_[0-9a-f]{24}$")
    fragment: FragmentRef
    rule_id: str = Field(pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+$")
    status: JaiminiRuleStatus

    @classmethod
    def create(
        cls,
        *,
        fragment: FragmentRef,
        rule_id: str,
        status: JaiminiRuleStatus,
    ) -> "JaiminiBaselineFragmentBinding":
        payload = {
            "fragment": fragment.model_dump(mode="json"),
            "rule_id": rule_id,
            "status": status.value,
        }
        return cls(binding_id=f"bind_{_hash_jaimini_payload(payload)[:24]}", **payload)

    @model_validator(mode="after")
    def _quarantined_and_content_addressed(
        self,
    ) -> "JaiminiBaselineFragmentBinding":
        if self.status not in {
            JaiminiRuleStatus.ANCHORED_UNREVIEWED,
            JaiminiRuleStatus.QUARANTINED_CONFLICT,
        }:
            raise ValueError("baseline fragment bindings must remain quarantined")
        payload = self.model_dump(mode="json", exclude={"binding_id"})
        expected = f"bind_{_hash_jaimini_payload(payload)[:24]}"
        if self.binding_id != expected:
            raise ValueError("baseline fragment binding identity is not content-addressed")
        return self


class JaiminiBaselineFragmentLedger(FrozenModel):
    """Inspection-safe evidence for the Nilakantha-mediated baseline inventory."""

    schema_version: Literal["1.0"] = "1.0"
    ledger_id: Literal["jaimini_nilakantha_mediated_baseline_fragments_v1"]
    school: Literal["nilakantha_baseline"]
    source_id: Literal["jaimini_sutras_b_suryanarain_rao_1949"]
    source_manifest_sha256: Sha256
    baseline_inventory_sha256: Sha256
    doctrine_admitted: Literal[False]
    product_rule_use_allowed: Literal[False]
    fragments: tuple[SourceFragment, ...] = Field(min_length=1)
    bindings: tuple[JaiminiBaselineFragmentBinding, ...] = Field(min_length=1)
    source_limitations: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _coherent_quarantine(self) -> "JaiminiBaselineFragmentLedger":
        fragment_ids = [fragment.fragment_id for fragment in self.fragments]
        if len(fragment_ids) != len(set(fragment_ids)):
            raise ValueError("baseline fragment IDs must be unique")
        binding_ids = [binding.binding_id for binding in self.bindings]
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError("baseline binding IDs must be unique")
        if len({binding.rule_id for binding in self.bindings}) != len(self.bindings):
            raise ValueError("baseline rule candidates require one bounded fragment each")

        references = {
            (
                fragment.fragment_id,
                fragment.revision,
                fragment.revision_sha256,
            )
            for fragment in self.fragments
        }
        for binding in self.bindings:
            reference = (
                binding.fragment.fragment_id,
                binding.fragment.revision,
                binding.fragment.revision_sha256,
            )
            if reference not in references:
                raise ValueError("baseline binding references missing fragment evidence")

        if any(
            fragment.source_id != self.source_id
            or fragment.school != self.school
            or fragment.source_manifest_sha256 != self.source_manifest_sha256
            for fragment in self.fragments
        ):
            raise ValueError("baseline fragment ledger cannot blend source identities")
        if any(
            fragment.admission_status != "quarantined"
            or fragment.excerpt_permission != "none"
            or fragment.permitted_excerpt is not None
            for fragment in self.fragments
        ):
            raise ValueError("baseline fragments must be text-free and quarantined")
        for fragment in self.fragments:
            _validate_source_fragment_identity(fragment)
        for limitation in self.source_limitations:
            _reject_private_locator(limitation)
        return self

    @property
    def ledger_sha256(self) -> str:
        payload = self.model_dump(mode="json")
        payload["fragments"] = sorted(
            payload["fragments"], key=lambda item: item["fragment_id"]
        )
        payload["bindings"] = sorted(
            payload["bindings"], key=lambda item: item["binding_id"]
        )
        payload["source_limitations"] = sorted(payload["source_limitations"])
        return _hash_jaimini_payload(payload)

    def validate_context(
        self,
        *,
        manifest: SourceManifest,
        baseline_inventory: JaiminiRuleInventory,
    ) -> None:
        if manifest.manifest_sha256 != self.source_manifest_sha256:
            raise ValueError("active source manifest does not match baseline ledger")
        if baseline_inventory.inventory_sha256 != self.baseline_inventory_sha256:
            raise ValueError("baseline inventory does not match fragment ledger")

        sources = {source.source_id: source for source in manifest.sources}
        source = sources.get(self.source_id)
        if source is None or source.school_role.value != "root_text":
            raise ValueError("baseline source is absent or incorrectly classified")
        fragments = {
            (fragment.fragment_id, fragment.revision, fragment.revision_sha256): fragment
            for fragment in self.fragments
        }
        candidates = {
            candidate.rule_id: candidate for candidate in baseline_inventory.candidates
        }
        bound_rule_ids = {binding.rule_id for binding in self.bindings}
        if bound_rule_ids != set(candidates):
            raise ValueError("baseline ledger must bind every inventory candidate")

        for fragment in self.fragments:
            if fragment.source_file_sha256 != source.sha256:
                raise ValueError("baseline fragment source bytes do not match manifest")
            if (
                fragment.page_number < 1
                or fragment.printed_page < 1
                or fragment.printed_page != fragment.page_number + source.page_offset
            ):
                raise ValueError("baseline fragment page coordinates do not match manifest")

        for binding in self.bindings:
            fragment = fragments[
                binding.fragment.fragment_id,
                binding.fragment.revision,
                binding.fragment.revision_sha256,
            ]
            candidate = candidates.get(binding.rule_id)
            if candidate is None or candidate.anchor is None:
                raise ValueError("baseline binding references an unanchored rule candidate")
            if candidate.status != binding.status:
                raise ValueError("baseline binding status differs from inventory")
            if (
                candidate.anchor.pdf_page != fragment.page_number
                or candidate.anchor.printed_page != fragment.printed_page
                or candidate.anchor.sutra != fragment.anchor_label
                or candidate.anchor.fragment_sha256
                != fragment.normalized_content_sha256
            ):
                raise ValueError("baseline inventory fragment commitment is inconsistent")


class JaiminiOverlayFragmentBinding(FrozenModel):
    """A non-quoting overlay claim bound to an inspection-safe fragment identity."""

    binding_id: str = Field(pattern=r"^bind_[0-9a-f]{24}$")
    fragment: FragmentRef
    rule_id: str = Field(pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+$")
    rule_family: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    paraphrase: str = Field(min_length=1, max_length=500)
    status: JaiminiRuleStatus
    discrepancy: str | None = Field(default=None, min_length=1, max_length=500)

    @classmethod
    def create(
        cls,
        *,
        fragment: FragmentRef,
        rule_id: str,
        rule_family: str,
        paraphrase: str,
        status: JaiminiRuleStatus,
        discrepancy: str | None = None,
    ) -> "JaiminiOverlayFragmentBinding":
        payload = {
            "fragment": fragment.model_dump(mode="json"),
            "rule_id": rule_id,
            "rule_family": rule_family,
            "paraphrase": paraphrase,
            "status": status.value,
            "discrepancy": discrepancy,
        }
        return cls(binding_id=f"bind_{_hash_jaimini_payload(payload)[:24]}", **payload)

    @model_validator(mode="after")
    def _quarantined_and_content_addressed(self) -> "JaiminiOverlayFragmentBinding":
        if self.status not in {
            JaiminiRuleStatus.ANCHORED_UNREVIEWED,
            JaiminiRuleStatus.QUARANTINED_CONFLICT,
        }:
            raise ValueError("overlay fragment bindings must remain quarantined")
        if self.status == JaiminiRuleStatus.QUARANTINED_CONFLICT:
            if self.discrepancy is None:
                raise ValueError("conflict bindings require an explicit discrepancy")
        elif self.discrepancy is not None:
            raise ValueError("unreviewed non-conflict bindings cannot claim a discrepancy")
        _reject_private_locator(self.paraphrase)
        if self.discrepancy is not None:
            _reject_private_locator(self.discrepancy)
        payload = self.model_dump(mode="json", exclude={"binding_id"})
        expected = f"bind_{_hash_jaimini_payload(payload)[:24]}"
        if self.binding_id != expected:
            raise ValueError("overlay fragment binding identity is not content-addressed")
        return self


class JaiminiUnresolvedOverlaySource(FrozenModel):
    overlay_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,95}$")
    school: str = Field(pattern=r"^[a-z][a-z0-9_]{2,95}$")
    source_id: SourceId
    blocker_code: Literal[
        "crop_aware_extraction_required", "ocr_review_pending"
    ]
    blocker: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _privacy_safe_blocker(self) -> "JaiminiUnresolvedOverlaySource":
        if self.school != self.overlay_id:
            raise ValueError("unresolved source school must match its named overlay")
        _reject_private_locator(self.blocker)
        return self


class JaiminiOverlayFragmentLedger(FrozenModel):
    """Hash-bound overlay evidence that is structurally unable to activate rules."""

    schema_version: Literal["1.0"] = "1.0"
    ledger_id: Literal[
        "jaimini_sanjay_rath_overlay_fragments_v1",
        "jaimini_kn_rao_overlay_fragments_v1",
    ]
    overlay_id: Literal["sanjay_rath", "kn_rao_practical"]
    school: Literal["sanjay_rath", "kn_rao_practical"]
    source_manifest_sha256: Sha256
    baseline_inventory_sha256: Sha256
    activation_status: Literal["unavailable"]
    doctrine_admitted: Literal[False]
    product_rule_use_allowed: Literal[False]
    fragments: tuple[SourceFragment, ...] = Field(min_length=1)
    bindings: tuple[JaiminiOverlayFragmentBinding, ...] = Field(min_length=1)
    unresolved_sources: tuple[JaiminiUnresolvedOverlaySource, ...]

    @model_validator(mode="after")
    def _coherent_quarantine(self) -> "JaiminiOverlayFragmentLedger":
        fragment_ids = [fragment.fragment_id for fragment in self.fragments]
        if len(fragment_ids) != len(set(fragment_ids)):
            raise ValueError("overlay fragment IDs must be unique")
        binding_ids = [binding.binding_id for binding in self.bindings]
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError("overlay fragment binding IDs must be unique")
        binding_keys = [
            (
                binding.fragment.fragment_id,
                binding.fragment.revision,
                binding.rule_id,
            )
            for binding in self.bindings
        ]
        if len(binding_keys) != len(set(binding_keys)):
            raise ValueError("duplicate fragment-to-rule binding")

        references = {
            (
                fragment.fragment_id,
                fragment.revision,
                fragment.revision_sha256,
            )
            for fragment in self.fragments
        }
        for binding in self.bindings:
            reference = (
                binding.fragment.fragment_id,
                binding.fragment.revision,
                binding.fragment.revision_sha256,
            )
            if reference not in references:
                raise ValueError("binding references a missing or stale source fragment")

        if any(
            fragment.source_manifest_sha256 != self.source_manifest_sha256
            for fragment in self.fragments
        ):
            raise ValueError("fragment source manifest identity does not match ledger")
        expected_ledger_ids = {
            "sanjay_rath": "jaimini_sanjay_rath_overlay_fragments_v1",
            "kn_rao_practical": "jaimini_kn_rao_overlay_fragments_v1",
        }
        expected_source_ids = {
            "sanjay_rath": {
                "jaimini_sanjay_rath_upadesa_sutras_1997",
                "jaimini_sanjay_rath_narayana_dasa_2004",
            },
            "kn_rao_practical": {
                "jaimini_kn_rao_chara_dasha_vani_scan_2010"
            },
        }
        if self.ledger_id != expected_ledger_ids[self.overlay_id]:
            raise ValueError("overlay fragment ledger identity does not match overlay")
        if self.school != self.overlay_id:
            raise ValueError("overlay fragment ledger school must match overlay")
        if {fragment.source_id for fragment in self.fragments} != expected_source_ids[
            self.overlay_id
        ]:
            raise ValueError(
                "this ledger requires exactly the declared overlay source pages"
            )
        if any(fragment.school != self.school for fragment in self.fragments):
            raise ValueError("overlay fragment ledger cannot blend schools")
        if any(
            fragment.admission_status != "quarantined"
            or fragment.excerpt_permission != "none"
            or fragment.permitted_excerpt is not None
            for fragment in self.fragments
        ):
            raise ValueError("overlay fragments must be text-free and quarantined")
        for fragment in self.fragments:
            _validate_source_fragment_identity(fragment)
        unresolved_ids = [item.source_id for item in self.unresolved_sources]
        if len(unresolved_ids) != len(set(unresolved_ids)):
            raise ValueError("unresolved overlay source IDs must be unique")
        if any(item.overlay_id != self.overlay_id for item in self.unresolved_sources):
            raise ValueError("unresolved sources must belong to the ledger overlay")
        return self

    @property
    def ledger_sha256(self) -> str:
        payload = self.model_dump(mode="json")
        payload["fragments"] = sorted(
            payload["fragments"], key=lambda item: item["fragment_id"]
        )
        payload["bindings"] = sorted(
            payload["bindings"], key=lambda item: item["binding_id"]
        )
        payload["unresolved_sources"] = sorted(
            payload["unresolved_sources"], key=lambda item: item["source_id"]
        )
        return _hash_jaimini_payload(payload)

    @property
    def activation_allowed(self) -> bool:
        return False

    def require_activation_ready(self) -> None:
        raise JaiminiOverlayFailure(
            "OVERLAY_FRAGMENT_LEDGER_QUARANTINED",
            "Overlay source fragments are quarantined and cannot activate product rules.",
        )

    def validate_context(
        self,
        *,
        manifest: SourceManifest,
        baseline_inventory: JaiminiRuleInventory,
        overlay_registry: "JaiminiOverlayRegistry",
    ) -> None:
        if (
            self.activation_status != "unavailable"
            or self.doctrine_admitted is not False
            or self.product_rule_use_allowed is not False
        ):
            raise ValueError("fragment ledger must retain its unavailable quarantine state")
        if manifest.manifest_sha256 != self.source_manifest_sha256:
            raise ValueError("active source manifest does not match fragment ledger")
        if baseline_inventory.inventory_sha256 != self.baseline_inventory_sha256:
            raise ValueError("baseline inventory does not match fragment ledger")

        sources = {source.source_id: source for source in manifest.sources}
        overlays = {overlay.overlay_id: overlay for overlay in overlay_registry.overlays}
        overlay = overlays.get(self.overlay_id)
        if overlay is None or overlay.activation_status != "unavailable":
            raise ValueError("fragment ledger requires an unavailable named overlay")
        known_rules = {candidate.rule_id for candidate in baseline_inventory.candidates}
        if any(binding.rule_id not in known_rules for binding in self.bindings):
            raise ValueError("fragment binding references an unknown baseline rule family")
        if any(
            binding.status
            not in {
                JaiminiRuleStatus.ANCHORED_UNREVIEWED,
                JaiminiRuleStatus.QUARANTINED_CONFLICT,
            }
            for binding in self.bindings
        ):
            raise ValueError("fragment bindings must remain quarantined")

        for fragment in self.fragments:
            if fragment.school != self.school:
                raise ValueError("overlay fragment ledger cannot blend schools")
            source = sources.get(fragment.source_id)
            if source is None:
                raise ValueError("fragment source is absent from active manifest")
            if source.school_role.value != "overlay":
                raise ValueError("fragment source is not classified as an overlay")
            if fragment.source_id not in overlay.source_ids:
                raise ValueError("fragment source does not belong to named overlay")
            if fragment.source_file_sha256 != source.sha256:
                raise ValueError("fragment source bytes do not match active manifest")
            if (
                fragment.page_number < 1
                or fragment.printed_page < 1
                or fragment.printed_page != fragment.page_number + source.page_offset
            ):
                raise ValueError(
                    "fragment page coordinates do not match the source page offset"
                )

        for unresolved in self.unresolved_sources:
            source = sources.get(unresolved.source_id)
            source_overlay = overlays.get(unresolved.overlay_id)
            if source is None or source_overlay is None:
                raise ValueError("unresolved source identity is unknown")
            if source_overlay.activation_status != "unavailable":
                raise ValueError("unresolved source overlay must remain unavailable")
            if unresolved.source_id not in source_overlay.source_ids:
                raise ValueError("unresolved source does not belong to named overlay")
            if source.school_role.value != "overlay":
                raise ValueError("unresolved source is not classified as an overlay")


def _hash_jaimini_payload(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _reject_private_locator(value: str) -> None:
    lowered = value.casefold()
    if any(marker in lowered for marker in ("private_sources", ".pdf", "/users/")):
        raise ValueError("tracked overlay evidence cannot contain private source locators")


def _validate_source_fragment_identity(fragment: SourceFragment) -> None:
    draft_payload = {
        "source_id": fragment.source_id,
        "source_manifest_sha256": fragment.source_manifest_sha256,
        "page_number": fragment.page_number,
        "printed_page": fragment.printed_page,
        "anchor_kind": fragment.anchor_kind,
        "anchor_label": fragment.anchor_label,
        "language": fragment.language,
        "content_role": fragment.content_role,
        "school": fragment.school,
        "scope": fragment.scope,
        "full_text_sha256": fragment.full_text_sha256,
        "normalized_content_sha256": fragment.normalized_content_sha256,
        "excerpt_permission": fragment.excerpt_permission,
        "permitted_excerpt": fragment.permitted_excerpt,
        "admission_status": fragment.admission_status,
    }
    if fragment.draft_sha256 != _hash_jaimini_payload(draft_payload):
        raise ValueError("source fragment draft identity is not content-addressed")
    stable_identity = {
        key: draft_payload[key]
        for key in (
            "source_id",
            "page_number",
            "anchor_kind",
            "anchor_label",
            "language",
            "content_role",
            "school",
            "scope",
        )
    }
    if fragment.fragment_id != f"frag_{_hash_jaimini_payload(stable_identity)[:24]}":
        raise ValueError("source fragment ID is not content-addressed")
    revision_payload = {
        "fragment_id": fragment.fragment_id,
        "revision": fragment.revision,
        "draft_sha256": fragment.draft_sha256,
        "source_file_sha256": fragment.source_file_sha256,
        **draft_payload,
    }
    if fragment.revision_sha256 != _hash_jaimini_payload(revision_payload):
        raise ValueError("source fragment revision identity is not content-addressed")


class JaiminiTopic(StrEnum):
    SELF = "self"
    CAREER = "career"
    RELATIONSHIPS = "relationships"
    TIMING = "timing"


class JaiminiTopicSignalClass(StrEnum):
    SUPPORTING = "supporting"
    CONFLICTING = "conflicting"


class JaiminiTopicSignal(FrozenModel):
    path: str
    value: str | int | float | bool | None
    topic: str
    rule_id: str
    school: str
    signal_class: JaiminiTopicSignalClass
    confidence: float = Field(ge=0.0, le=0.95)
    time_scope: str


class JaiminiTopicAnalysis(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    topic: JaiminiTopic
    graph_sha256: Sha256
    available: bool
    school_ids: tuple[str, ...]
    activated_rule_ids: tuple[str, ...]
    signals: tuple[JaiminiTopicSignal, ...]
    conflicts: tuple[tuple[str, str], ...]
    suppressed_fact_paths: tuple[str, ...]
    prohibited_topics: tuple[str, ...]
    unavailable_reasons: tuple[str, ...]


_TOPIC_LABELS: dict[JaiminiTopic, frozenset[str]] = {
    JaiminiTopic.SELF: frozenset({"self", "dharma", "education", "capability"}),
    JaiminiTopic.CAREER: frozenset({"career", "status", "activity"}),
    JaiminiTopic.RELATIONSHIPS: frozenset({"relationships", "family", "legacy"}),
    JaiminiTopic.TIMING: frozenset({"timing"}),
}

_TIME_SENSITIVE_PREFIXES: dict[JaiminiTopic, tuple[str, ...]] = {
    JaiminiTopic.SELF: (
        "jaimini.karakamsa.",
        "jaimini.svamsa.",
        "jaimini.arudha.",
        "jaimini.special_lagnas.",
    ),
    JaiminiTopic.CAREER: (
        "jaimini.arudha.",
        "jaimini.argala.",
        "jaimini.rasi_drishti.",
    ),
    JaiminiTopic.RELATIONSHIPS: (
        "jaimini.relationships.",
        "jaimini.arudha.",
        "jaimini.argala.",
        "jaimini.rasi_drishti.",
    ),
    JaiminiTopic.TIMING: (
        "jaimini.chara_dasha.",
        "jaimini.chara_antardasha.",
    ),
}


def analyze_jaimini_topic(
    graph: AnalysisGraph,
    topic: JaiminiTopic,
    *,
    birth_time_confidence: Literal["exact", "approximate"] = "exact",
) -> JaiminiTopicAnalysis:
    """Project a source-bound graph into a bounded Jaimini topic result."""

    labels = _TOPIC_LABELS[topic]
    topic_nodes = tuple(node for node in graph.topic_nodes if node.topic in labels)
    active_rules = {node.rule_id for node in topic_nodes}
    conflict_pairs = {
        tuple(sorted((node.left_rule_id, node.right_rule_id)))
        for node in graph.conflict_nodes
        if node.left_rule_id in active_rules and node.right_rule_id in active_rules
    }
    conflicting_rules = {rule_id for pair in conflict_pairs for rule_id in pair}
    fact_by_id = {node.node_id: node for node in graph.fact_nodes}
    signals: list[JaiminiTopicSignal] = []
    suppressed: set[str] = set()
    time_sensitive = _TIME_SENSITIVE_PREFIXES[topic]

    for node in sorted(topic_nodes, key=lambda item: item.rule_id):
        fact_ids = sorted(
            edge.target_id
            for edge in graph.edges
            if edge.source_id == node.node_id and edge.relation == "supported_by_fact"
        )
        for fact_id in fact_ids:
            fact = fact_by_id.get(fact_id)
            if fact is None:
                continue
            if birth_time_confidence == "approximate" and fact.path.startswith(
                time_sensitive
            ):
                suppressed.add(fact.path)
                continue
            signals.append(
                JaiminiTopicSignal(
                    path=fact.path,
                    value=fact.value,
                    topic=node.topic,
                    rule_id=node.rule_id,
                    school=node.school,
                    signal_class=(
                        JaiminiTopicSignalClass.CONFLICTING
                        if node.rule_id in conflicting_rules
                        else JaiminiTopicSignalClass.SUPPORTING
                    ),
                    confidence=node.confidence,
                    time_scope=node.time_scope,
                )
            )

    reasons: list[str] = []
    if not topic_nodes:
        reasons.append("NO_ADMITTED_TOPIC_RULES")
    if birth_time_confidence == "approximate" and suppressed:
        reasons.append("BIRTH_TIME_APPROXIMATE")
    if topic_nodes and not signals:
        reasons.append("NO_STABLE_TOPIC_SIGNALS")

    return JaiminiTopicAnalysis(
        topic=topic,
        graph_sha256=graph.graph_sha256,
        available=bool(topic_nodes and signals),
        school_ids=tuple(sorted({node.school for node in topic_nodes})),
        activated_rule_ids=tuple(sorted(active_rules)),
        signals=tuple(
            sorted(signals, key=lambda item: (item.topic, item.rule_id, item.path))
        ),
        conflicts=tuple(sorted(conflict_pairs)),
        suppressed_fact_paths=tuple(sorted(suppressed)),
        prohibited_topics=tuple(sorted(node.topic for node in graph.prohibition_nodes)),
        unavailable_reasons=tuple(reasons),
    )


def render_jaimini_topic_report(
    analysis: JaiminiTopicAnalysis,
    *,
    locale: Literal["ru", "en"],
) -> str:
    """Render only bounded graph-derived topic signals in Russian or English."""

    titles = {
        "en": {
            JaiminiTopic.SELF: "Jaimini: self and capabilities",
            JaiminiTopic.CAREER: "Jaimini career",
            JaiminiTopic.RELATIONSHIPS: "Jaimini relationships",
            JaiminiTopic.TIMING: "Jaimini timing",
        },
        "ru": {
            JaiminiTopic.SELF: "Jaimini: личность и способности",
            JaiminiTopic.CAREER: "Jaimini: карьера",
            JaiminiTopic.RELATIONSHIPS: "Jaimini: отношения",
            JaiminiTopic.TIMING: "Jaimini: периоды",
        },
    }
    admission_label = "admission not evaluated" if locale == "en" else "допуск не оценён"
    lines = [f"## {titles[locale][analysis.topic]} — {admission_label}"]
    if locale == "en":
        lines.append(f"Status: {'available' if analysis.available else 'unavailable'}")
        signal_phrase = "Source-bound symbolic signal"
        conflict_label = "Conflicting admitted rules"
        disclaimer = "This is a symbolic, source-bound interpretation, not a guaranteed event forecast."
    else:
        lines.append(f"Статус: {'доступно' if analysis.available else 'недоступно'}")
        signal_phrase = "Подтверждённый источником символический сигнал"
        conflict_label = "Конфликтующие допущенные правила"
        disclaimer = "Это символическая интерпретация с опорой на источники, а не гарантированный прогноз события."

    if analysis.school_ids:
        lines.append("School: " + ", ".join(analysis.school_ids))
    for signal in analysis.signals:
        lines.append(
            f"- {signal.topic}: {signal_phrase} "
            f"[{signal.school}; {signal.time_scope}; {signal.signal_class.value}; "
            f"confidence <= {signal.confidence:.2f}]"
        )
    if analysis.conflicts:
        lines.append(
            f"{conflict_label}: "
            + "; ".join(f"{left} <> {right}" for left, right in analysis.conflicts)
        )
    if analysis.unavailable_reasons:
        lines.append("Limitations: " + ", ".join(analysis.unavailable_reasons))
    lines.append(disclaimer)
    return "\n".join(lines) + "\n"


class JaiminiTimingFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class JaiminiTimingWindow(FrozenModel):
    sign: str = Field(min_length=1)
    start: dt.datetime
    end: dt.datetime
    boundary_stability: Literal["stable", "unstable"]
    confidence: float = Field(ge=0.0, le=0.95)
    rule_ids: tuple[str, ...] = Field(min_length=1)
    fact_paths: tuple[str, ...] = Field(min_length=4)
    source_commitments: tuple[Sha256, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _bounded_window(self) -> "JaiminiTimingWindow":
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("timing windows must be timezone-aware")
        if self.end <= self.start:
            raise ValueError("timing window end must be after start")
        return self


class JaiminiTimingAnalysis(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    graph_sha256: Sha256
    natal_topic: JaiminiTopic
    available: bool
    windows: tuple[JaiminiTimingWindow, ...]
    limitations: tuple[str, ...]


_CHARA_PERIOD_PATH = re.compile(
    r"^jaimini\.chara_dasha\.(?P<index>[1-9][0-9]*)\."
    r"(?P<field>sign|start|end|active)$"
)


def link_chara_dasha_timing(
    graph: AnalysisGraph,
    natal_analysis: JaiminiTopicAnalysis,
    *,
    birth_time_confidence: Literal["exact", "approximate"] = "exact",
    max_windows: int = 12,
) -> JaiminiTimingAnalysis:
    """Link bounded Chara Dasha periods only to an available natal topic graph."""

    if natal_analysis.graph_sha256 != graph.graph_sha256:
        raise JaiminiTimingFailure(
            "NATAL_GRAPH_SUBSTITUTED",
            "Natal topic and timing graph identities do not match.",
        )
    if not natal_analysis.available:
        return JaiminiTimingAnalysis(
            graph_sha256=graph.graph_sha256,
            natal_topic=natal_analysis.topic,
            available=False,
            windows=(),
            limitations=("NATAL_TOPIC_UNAVAILABLE",),
        )

    timing_nodes = tuple(node for node in graph.topic_nodes if node.topic == "timing")
    fact_by_id = {node.node_id: node for node in graph.fact_nodes}
    periods: dict[int, dict[str, object]] = {}
    rule_ids_by_period: dict[int, set[str]] = {}
    commitments_by_period: dict[int, set[str]] = {}
    confidence_by_period: dict[int, float] = {}

    for node in timing_nodes:
        fact_edges = tuple(
            edge
            for edge in graph.edges
            if edge.source_id == node.node_id and edge.relation == "supported_by_fact"
        )
        period_indexes: set[int] = set()
        for edge in fact_edges:
            fact = fact_by_id.get(edge.target_id)
            if fact is None:
                continue
            match = _CHARA_PERIOD_PATH.fullmatch(fact.path)
            if match is None:
                continue
            index = int(match.group("index"))
            field = match.group("field")
            periods.setdefault(index, {})[field] = fact.value
            periods[index].setdefault("fact_paths", set())
            paths = periods[index]["fact_paths"]
            if isinstance(paths, set):
                paths.add(fact.path)
            period_indexes.add(index)
            rule_ids_by_period.setdefault(index, set()).add(node.rule_id)
            confidence_by_period[index] = min(
                confidence_by_period.get(index, node.confidence), node.confidence
            )
        source_targets = {
            edge.target_id
            for edge in graph.edges
            if edge.source_id == node.node_id and edge.relation == "supported_by_source"
        }
        for index in period_indexes:
            commitments_by_period.setdefault(index, set()).update(
                hashlib.sha256(target.encode("utf-8")).hexdigest()
                for target in source_targets
            )

    windows: list[JaiminiTimingWindow] = []
    for index in sorted(periods):
        period = periods[index]
        if period.get("active") is not True:
            continue
        required = {"sign", "start", "end", "active", "fact_paths"}
        if not required <= set(period):
            raise JaiminiTimingFailure(
                "TIMING_LINEAGE_INCOMPLETE",
                "An active timing period lacks required fact lineage.",
            )
        try:
            start = dt.datetime.fromisoformat(str(period["start"]))
            end = dt.datetime.fromisoformat(str(period["end"]))
            window = JaiminiTimingWindow(
                sign=str(period["sign"]),
                start=start,
                end=end,
                boundary_stability=(
                    "stable" if birth_time_confidence == "exact" else "unstable"
                ),
                confidence=confidence_by_period[index],
                rule_ids=tuple(sorted(rule_ids_by_period[index])),
                fact_paths=tuple(sorted(period["fact_paths"])),
                source_commitments=tuple(
                    sorted(commitments_by_period.get(index, set()))
                ),
            )
        except (TypeError, ValueError) as exc:
            raise JaiminiTimingFailure(
                "TIMING_WINDOW_INVALID",
                "A timing period is not a valid bounded timezone-aware interval.",
            ) from exc
        windows.append(window)

    if len(windows) > max_windows:
        raise JaiminiTimingFailure(
            "TIMING_PAYLOAD_LIMIT", "Timing window count exceeds the configured bound."
        )
    limitations = (
        ("BIRTH_TIME_APPROXIMATE",)
        if birth_time_confidence == "approximate" and windows
        else (() if windows else ("NO_ADMITTED_TIMING_WINDOWS",))
    )
    return JaiminiTimingAnalysis(
        graph_sha256=graph.graph_sha256,
        natal_topic=natal_analysis.topic,
        available=bool(windows),
        windows=tuple(windows),
        limitations=limitations,
    )


def render_jaimini_timing_report(
    analysis: JaiminiTimingAnalysis,
    *,
    locale: Literal["ru", "en"],
) -> str:
    title = "Jaimini timing windows" if locale == "en" else "Окна периодов Jaimini"
    admission_label = "admission not evaluated" if locale == "en" else "допуск не оценён"
    lines = [f"## {title} — {admission_label}"]
    for window in analysis.windows:
        lines.append(
            f"- {window.sign}: {window.start.date().isoformat()} — "
            f"{window.end.date().isoformat()} [{window.boundary_stability}; "
            f"confidence <= {window.confidence:.2f}]"
        )
    lines.append(
        "These are bounded possibility windows, not event promises."
        if locale == "en"
        else "Это ограниченные окна возможностей, а не обещания событий."
    )
    if analysis.limitations:
        lines.append("Limitations: " + ", ".join(analysis.limitations))
    return "\n".join(lines) + "\n"


class JaiminiOverlayFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class JaiminiOverlayDefinition(FrozenModel):
    overlay_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,95}$")
    display_name: str = Field(min_length=1)
    source_ids: tuple[SourceId, ...] = ()
    activation_status: Literal["unavailable", "available"]
    missing_reason: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _activation_has_sources(self) -> "JaiminiOverlayDefinition":
        if self.activation_status == "available" and not self.source_ids:
            raise ValueError("available overlays require verified source identities")
        if self.activation_status == "unavailable" and self.missing_reason is None:
            raise ValueError("unavailable overlays require a missing reason")
        return self


class JaiminiOverlayRegistry(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    overlays: tuple[JaiminiOverlayDefinition, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_overlays(self) -> "JaiminiOverlayRegistry":
        ids = [overlay.overlay_id for overlay in self.overlays]
        if len(ids) != len(set(ids)):
            raise ValueError("overlay IDs must be unique")
        return self


_VALIDATED_OVERLAY_CONTEXT = object()


class JaiminiOverlayActivationContract:
    """Validated registry/ledger context required by the real activation path."""

    __slots__ = (
        "_ledger",
        "_registry",
        "_sealed",
        "_validation_state_sha256",
        "_validation_token",
    )

    def __init_subclass__(cls, **_kwargs: object) -> None:
        raise TypeError("JaiminiOverlayActivationContract cannot be subclassed")

    def __init__(
        self,
        *,
        ledger: JaiminiOverlayFragmentLedger,
        registry: JaiminiOverlayRegistry,
        _validation_token: object,
    ) -> None:
        if _validation_token is not _VALIDATED_OVERLAY_CONTEXT:
            raise TypeError("use load_jaimini_overlay_activation_contract")
        object.__setattr__(self, "_ledger", ledger)
        object.__setattr__(self, "_registry", registry)
        object.__setattr__(self, "_validation_token", _validation_token)
        object.__setattr__(
            self,
            "_validation_state_sha256",
            _jaimini_overlay_validation_state(ledger, registry),
        )
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, _name: str, _value: object) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("validated activation contracts are immutable")
        object.__setattr__(self, _name, _value)

    @property
    def ledger(self) -> JaiminiOverlayFragmentLedger:
        return self._ledger

    def require_activation_ready(self, overlay_id: str) -> None:
        ledger = getattr(self, "_ledger", None)
        registry = getattr(self, "_registry", None)
        if (
            type(self) is not JaiminiOverlayActivationContract
            or getattr(self, "_validation_token", None)
            is not _VALIDATED_OVERLAY_CONTEXT
            or not isinstance(ledger, JaiminiOverlayFragmentLedger)
            or not isinstance(registry, JaiminiOverlayRegistry)
            or getattr(self, "_validation_state_sha256", None)
            != _jaimini_overlay_validation_state(ledger, registry)
        ):
            raise JaiminiOverlayFailure(
                "OVERLAY_ACTIVATION_CONTEXT_INVALID",
                "Overlay activation context is absent, forged, or stale.",
            )
        overlay = next(
            (
                definition
                for definition in registry.overlays
                if definition.overlay_id == overlay_id
            ),
            None,
        )
        if overlay is None:
            raise JaiminiOverlayFailure(
                "OVERLAY_UNKNOWN", "The requested overlay is not registered."
            )
        if overlay.activation_status != "available":
            raise JaiminiOverlayFailure(
                "OVERLAY_UNAVAILABLE",
                "The requested overlay has not passed its activation gates.",
            )
        if ledger.overlay_id != overlay_id:
            raise JaiminiOverlayFailure(
                "OVERLAY_LEDGER_MISSING",
                "The requested overlay has no validated source-fragment ledger.",
            )
        ledger.require_activation_ready()


def _jaimini_overlay_validation_state(
    ledger: JaiminiOverlayFragmentLedger,
    registry: JaiminiOverlayRegistry,
) -> str:
    registry_payload = registry.model_dump(mode="json")
    registry_payload["overlays"] = sorted(
        registry_payload["overlays"], key=lambda item: item["overlay_id"]
    )
    return _hash_jaimini_payload(
        {
            "ledger_sha256": ledger.ledger_sha256,
            "registry": registry_payload,
        }
    )


def load_jaimini_overlay_activation_contract(
    *,
    ledger_path: Path,
    manifest_path: Path,
    baseline_inventory_path: Path,
    overlay_registry_path: Path,
) -> JaiminiOverlayActivationContract:
    """Load all activation inputs and return only after full context validation."""

    ledger = JaiminiOverlayFragmentLedger.model_validate(
        _load_strict_jaimini_json(ledger_path)
    )
    manifest = load_source_manifest(manifest_path)
    inventory = JaiminiRuleInventory.model_validate(
        _load_strict_jaimini_json(baseline_inventory_path)
    )
    registry = JaiminiOverlayRegistry.model_validate(
        _load_strict_jaimini_json(overlay_registry_path)
    )
    ledger.validate_context(
        manifest=manifest,
        baseline_inventory=inventory,
        overlay_registry=registry,
    )
    return JaiminiOverlayActivationContract(
        ledger=ledger,
        registry=registry,
        _validation_token=_VALIDATED_OVERLAY_CONTEXT,
    )


def _load_strict_jaimini_json(path: Path) -> object:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        return json.loads(
            Path(path).read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except OSError as exc:
        raise ValueError("Jaimini overlay context could not be loaded") from exc


class JaiminiOverlayComparison(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    topic: JaiminiTopic
    overlay_id: str
    overlay_active: bool
    baseline_graph_sha256: Sha256
    overlay_graph_sha256: Sha256 | None
    school_ids: tuple[str, ...]
    baseline_signals: tuple[JaiminiTopicSignal, ...]
    overlay_signals: tuple[JaiminiTopicSignal, ...]
    divergences: tuple[tuple[str, str], ...]


def compare_jaimini_overlays(
    baseline: JaiminiTopicAnalysis,
    overlay: JaiminiTopicAnalysis,
    *,
    overlay_id: str,
    activate: bool,
    activation_contract: JaiminiOverlayActivationContract | None = None,
) -> JaiminiOverlayComparison:
    """Compare isolated analyses; never merge overlay signals into baseline state."""

    if baseline.topic != overlay.topic:
        raise JaiminiOverlayFailure(
            "OVERLAY_TOPIC_MISMATCH", "Baseline and overlay topics do not match."
        )
    if not activate:
        return JaiminiOverlayComparison(
            topic=baseline.topic,
            overlay_id=overlay_id,
            overlay_active=False,
            baseline_graph_sha256=baseline.graph_sha256,
            overlay_graph_sha256=None,
            school_ids=baseline.school_ids,
            baseline_signals=baseline.signals,
            overlay_signals=(),
            divergences=(),
        )
    if set(baseline.school_ids) & set(overlay.school_ids):
        raise JaiminiOverlayFailure(
            "OVERLAY_SCHOOL_NOT_EXPLICIT",
            "Overlay analysis must use a school distinct from the baseline.",
        )
    if overlay_id not in overlay.school_ids:
        raise JaiminiOverlayFailure(
            "OVERLAY_ID_MISMATCH",
            "Activated overlay identity does not match its analysis school.",
        )
    if type(activation_contract) is not JaiminiOverlayActivationContract:
        raise JaiminiOverlayFailure(
            "OVERLAY_ACTIVATION_CONTEXT_REQUIRED",
            "Overlay activation requires a validated registry and source ledger.",
        )
    activation_contract.require_activation_ready(overlay_id)
    divergences = tuple(
        sorted(
            (baseline_rule, overlay_rule)
            for baseline_rule in baseline.activated_rule_ids
            for overlay_rule in overlay.activated_rule_ids
        )
    )
    return JaiminiOverlayComparison(
        topic=baseline.topic,
        overlay_id=overlay_id,
        overlay_active=True,
        baseline_graph_sha256=baseline.graph_sha256,
        overlay_graph_sha256=overlay.graph_sha256,
        school_ids=tuple(sorted(set(baseline.school_ids) | set(overlay.school_ids))),
        baseline_signals=baseline.signals,
        overlay_signals=overlay.signals,
        divergences=divergences,
    )


class JaiminiReleaseGate(FrozenModel):
    gate_id: str = Field(min_length=1)
    status: Literal["passed", "failed", "missing"]
    evidence: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _gate_evidence(self) -> "JaiminiReleaseGate":
        if self.status == "passed" and self.evidence is None:
            raise ValueError("passed release gate requires evidence")
        if self.status == "missing" and self.evidence is not None:
            raise ValueError("missing release gate cannot claim evidence")
        return self


class JaiminiPrivateSourceRef(FrozenModel):
    source_id: SourceId
    pdf_page: int = Field(ge=1)
    printed_page: int = Field(ge=1)
    anchor: str = Field(min_length=1, max_length=120)
    school: Literal["nilakantha_baseline", "sanjay_rath"]
    role: Literal["baseline", "independent_cross_check"]

    @model_validator(mode="after")
    def _school_matches_role(self) -> "JaiminiPrivateSourceRef":
        expected = {
            "baseline": (
                "nilakantha_baseline",
                "jaimini_sutras_b_suryanarain_rao_1949",
            ),
            "independent_cross_check": (
                "sanjay_rath",
                "jaimini_sanjay_rath_upadesa_sutras_1997",
            ),
        }
        if (self.school, self.source_id) != expected[self.role]:
            raise ValueError("private source role cannot silently blend schools")
        return self


class JaiminiPrivateClaim(FrozenModel):
    claim_id: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    topic: Literal["self", "career", "relationships"]
    fact_path: str = Field(pattern=r"^jaimini\.[A-Za-z0-9_.]+$")
    label_ru: str = Field(min_length=1, max_length=120)
    label_en: str = Field(min_length=1, max_length=120)
    meaning_ru: str = Field(min_length=1, max_length=300)
    meaning_en: str = Field(min_length=1, max_length=300)
    confidence: float = Field(gt=0.0, le=0.65)
    source_refs: tuple[JaiminiPrivateSourceRef, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def _requires_baseline_and_cross_check(self) -> "JaiminiPrivateClaim":
        if {ref.role for ref in self.source_refs} != {
            "baseline",
            "independent_cross_check",
        }:
            raise ValueError("each private claim needs baseline and independent context")
        return self


class JaiminiUnavailableTopic(FrozenModel):
    topic: Literal["timing"]
    reason_code: Literal["CHARA_DASHA_SCHOOL_CONFLICT"]
    reason_ru: str = Field(min_length=1, max_length=500)
    reason_en: str = Field(min_length=1, max_length=500)


class JaiminiPrivateBaselineProfile(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    profile_id: Literal["full_jaimini_private_baseline_v1"]
    admission_scope: Literal["private_experimental"]
    school: Literal["nilakantha_baseline"]
    karaka_scheme: Literal[7]
    confidence_ceiling: float = Field(gt=0.0, le=0.65)
    external_review_missing: Literal[True]
    required_source_ids: tuple[SourceId, ...]
    cross_check_policy: Literal[
        "sanjay_rath_is_independent_context_not_an_activated_overlay"
    ]
    claims: tuple[JaiminiPrivateClaim, ...] = Field(min_length=6, max_length=6)
    unavailable_topics: tuple[JaiminiUnavailableTopic, ...] = Field(
        min_length=1, max_length=1
    )
    quarantined_rule_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _conservative_complete_profile(self) -> "JaiminiPrivateBaselineProfile":
        expected_paths = {
            "jaimini.karakas.7.AK",
            "jaimini.karakamsa.sign",
            "jaimini.karakas.7.AmK",
            "jaimini.arudha.AL",
            "jaimini.karakas.7.DK",
            "jaimini.arudha.UL",
        }
        paths = [claim.fact_path for claim in self.claims]
        ids = [claim.claim_id for claim in self.claims]
        if set(paths) != expected_paths or len(paths) != len(set(paths)):
            raise ValueError("private profile must expose exactly six structural facts")
        if len(ids) != len(set(ids)):
            raise ValueError("private claim IDs must be unique")
        if {claim.topic for claim in self.claims} != {
            "self",
            "career",
            "relationships",
        }:
            raise ValueError("private profile must cover all three safe topics")
        expected_sources = {
            "jaimini_sutras_b_suryanarain_rao_1949",
            "jaimini_sanjay_rath_upadesa_sutras_1997",
        }
        if set(self.required_source_ids) != expected_sources:
            raise ValueError("private profile source set is substituted")
        if len(self.required_source_ids) != len(expected_sources):
            raise ValueError("private profile source IDs must be unique")
        if any(claim.confidence > self.confidence_ceiling for claim in self.claims):
            raise ValueError("claim confidence exceeds the profile ceiling")
        if set(self.quarantined_rule_ids) != {
            "karakas.tie_policy",
            "svamsa.d9_lagna",
            "special_lagnas.selected_rates",
            "co_lords.resolution",
            "chara_dasha.progression",
            "chara_dasha.gender_semantics",
            "time.boundaries",
        }:
            raise ValueError("private profile must preserve all material quarantines")
        if len(self.quarantined_rule_ids) != 7:
            raise ValueError("quarantined rule IDs must be unique")
        return self


_JAIMINI_DOCTRINE_ROOT = Path(__file__).resolve().parents[1] / "data/doctrine"
_JAIMINI_PRIVATE_PROFILE = (
    _JAIMINI_DOCTRINE_ROOT / "jaimini-private-baseline-profile.json"
)
_JAIMINI_SOURCE_MANIFEST = _JAIMINI_DOCTRINE_ROOT / "jaimini-sources.json"
_JAIMINI_RULE_INVENTORY = _JAIMINI_DOCTRINE_ROOT / "jaimini-rules.json"
_JAIMINI_PACKAGED_RELEASE = _JAIMINI_DOCTRINE_ROOT / "jaimini-release.json"


def load_jaimini_private_baseline_profile() -> JaiminiPrivateBaselineProfile:
    return JaiminiPrivateBaselineProfile.model_validate(
        _load_strict_jaimini_json(_JAIMINI_PRIVATE_PROFILE)
    )


def jaimini_compiled_profile_sha256() -> str:
    profile = load_jaimini_private_baseline_profile()
    return hashlib.sha256(
        canonical_json(profile.model_dump(mode="json")).encode("utf-8")
    ).hexdigest()


class JaiminiReleaseAudit(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    release_id: Literal["full_jaimini_v1"]
    corpus_manifest_sha256: Sha256
    rule_inventory_sha256: Sha256
    compiled_profile_sha256: Sha256 | None
    admission_state: Literal[
        "blocked_sources", "automated_verified", "experimental_full", "reviewed"
    ]
    gates: tuple[JaiminiReleaseGate, ...]
    blockers: tuple[str, ...]
    public_release_blockers: tuple[str, ...]
    external_review_missing: bool
    available: bool
    completed_evidence: tuple[str, ...] = Field(min_length=1)
    future_follow_up: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _honest_release_state(self) -> "JaiminiReleaseAudit":
        ids = [gate.gate_id for gate in self.gates]
        if len(ids) != len(set(ids)):
            raise ValueError("release gate IDs must be unique")
        expected_available = self.admission_state in {"experimental_full", "reviewed"}
        if self.available != expected_available:
            raise ValueError("release availability must follow admission state")
        if self.available and (self.compiled_profile_sha256 is None or self.blockers):
            raise ValueError(
                "available release requires a compiled profile and no blockers"
            )
        AdmissionEvaluator.assert_required_gates(
            gates=self.gates,
            required_gate_ids=(
                *REQUIRED_AUTOMATED_GATES,
                "source_bound_private_profile",
            ),
            available=self.available,
        )
        if (
            self.compiled_profile_sha256 is None
            and self.admission_state != "blocked_sources"
        ):
            raise ValueError("missing compiled profile is a source-blocked release")
        if self.external_review_missing and not self.public_release_blockers:
            raise ValueError("missing external review must remain a public blocker")
        statuses = {gate.gate_id: gate.status for gate in self.gates}
        if "specialist_review" not in statuses:
            raise ValueError("release audit must declare the specialist gate")
        if self.external_review_missing != (
            statuses.get("specialist_review") != "passed"
        ):
            raise ValueError("external review flag must follow the specialist gate")
        if not any(
            blocker.startswith("timing:") for blocker in self.public_release_blockers
        ):
            raise ValueError("school-conflicted timing must remain a public blocker")
        return self


def load_jaimini_release_audit(
    *, verify_source_bytes: bool = True
) -> JaiminiReleaseAudit:
    """Verify the restricted private profile without activating any overlay."""

    audit = JaiminiReleaseAudit.model_validate(
        _load_strict_jaimini_json(_JAIMINI_PACKAGED_RELEASE)
    )
    manifest = load_source_manifest(_JAIMINI_SOURCE_MANIFEST)
    inventory = JaiminiRuleInventory.model_validate(
        _load_strict_jaimini_json(_JAIMINI_RULE_INVENTORY)
    )
    if audit.corpus_manifest_sha256 != manifest.manifest_sha256:
        raise ValueError("JAIMINI_SOURCE_MANIFEST_SUBSTITUTED")
    if audit.rule_inventory_sha256 != inventory.inventory_sha256:
        raise ValueError("JAIMINI_RULE_INVENTORY_SUBSTITUTED")
    if audit.compiled_profile_sha256 != jaimini_compiled_profile_sha256():
        raise ValueError("JAIMINI_COMPILED_PROFILE_SUBSTITUTED")
    if audit.available and verify_source_bytes:
        profile = load_jaimini_private_baseline_profile()
        required_ids = set(profile.required_source_ids)
        runtime_sources = tuple(
            source for source in manifest.sources if source.source_id in required_ids
        )
        if {source.source_id for source in runtime_sources} != required_ids:
            raise ValueError("JAIMINI_PRIVATE_SOURCE_MISSING")
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
            raise ValueError("JAIMINI_SOURCE_BYTES_UNVERIFIED")
    return audit
