"""Source-bound Full Jaimini release orchestration.

The first slice is deliberately an acquisition ledger rather than a doctrine
shortcut: an absent book can never become coverage merely because its title is
known. Later Jaimini slices consume this same verified corpus identity.
"""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from ..research_store import canonical_json
from .graph import AnalysisGraph
from .models import FrozenModel, ScanQuality
from .sources import Sha256, SourceId, SourceManifest, SourceVerificationReport


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
                raise ValueError("missing-anchor quarantine requires only a discrepancy")
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
        return self

    @property
    def inventory_sha256(self) -> str:
        payload = self.model_dump(mode="json")
        payload["candidates"] = sorted(
            payload["candidates"], key=lambda candidate: candidate["rule_id"]
        )
        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


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
    JaiminiTopic.RELATIONSHIPS: frozenset(
        {"relationships", "family", "legacy"}
    ),
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
        prohibited_topics=tuple(
            sorted(node.topic for node in graph.prohibition_nodes)
        ),
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
    lines = [f"## {titles[locale][analysis.topic]} — experimental_full"]
    if locale == "en":
        lines.append(f"Status: {'available' if analysis.available else 'unavailable'}")
        signal_phrase = "Source-bound symbolic signal"
        conflict_label = "Conflicting admitted rules"
        disclaimer = (
            "This is a symbolic, source-bound interpretation, not a guaranteed event forecast."
        )
    else:
        lines.append(f"Статус: {'доступно' if analysis.available else 'недоступно'}")
        signal_phrase = "Подтверждённый источником символический сигнал"
        conflict_label = "Конфликтующие допущенные правила"
        disclaimer = (
            "Это символическая интерпретация с опорой на источники, а не гарантированный прогноз события."
        )

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
