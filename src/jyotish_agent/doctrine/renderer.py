"""Constrained graph renderer and fail-closed structured-claim firewall."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from typing import Literal

from pydantic import Field

from .evidence import EvidenceStore, FragmentRef
from .graph import AnalysisGraph, TopicNode
from .models import FrozenModel
from .sources import Sha256


class StructuredClaim(FrozenModel):
    claim_id: str = Field(pattern=r"^claim_[0-9a-f]{24}$")
    graph_sha256: Sha256
    topic_node_id: str
    topic: str
    text: str = Field(min_length=1, max_length=2_000)
    fact_refs: tuple[str, ...]
    doctrine_refs: tuple[str, ...]
    source_refs: tuple[str, ...]
    school: str
    confidence: float = Field(ge=0.0, le=1.0)
    time_scope: str
    safety_class: str


class CandidateReport(FrozenModel):
    graph_sha256: Sha256
    claims: tuple[StructuredClaim, ...]


class FirewallViolation(FrozenModel):
    claim_id: str | None
    code: str
    message: str


class FirewallResult(FrozenModel):
    valid_claims: tuple[StructuredClaim, ...]
    violations: tuple[FirewallViolation, ...]


class RenderedReport(FrozenModel):
    locale: Literal["ru", "en"]
    admission_status: Literal["not_evaluated"] = "not_evaluated"
    claims: tuple[StructuredClaim, ...]
    violations: tuple[FirewallViolation, ...]
    repairs_attempted: int = Field(ge=0, le=2)
    markdown: str
    markdown_sha256: Sha256


Producer = Callable[[int, tuple[FirewallViolation, ...]], CandidateReport]


class ConstrainedRenderer:
    def __init__(self, evidence: EvidenceStore) -> None:
        self.evidence = evidence

    def candidate_from_graph(self, graph: AnalysisGraph) -> CandidateReport:
        rule_by_node = {node.node_id: node.rule_id for node in graph.rule_nodes}
        claims: list[StructuredClaim] = []
        for topic in graph.topic_nodes:
            edges = [edge for edge in graph.edges if edge.source_id == topic.node_id]
            fact_refs = tuple(
                sorted(edge.target_id for edge in edges if edge.relation == "supported_by_fact")
            )
            doctrine_refs = tuple(
                sorted(
                    rule_by_node[edge.target_id]
                    for edge in edges
                    if edge.relation == "activated_by"
                )
            )
            source_refs = tuple(
                sorted(edge.target_id for edge in edges if edge.relation == "supported_by_source")
            )
            payload = {
                "graph_sha256": graph.graph_sha256,
                "topic_node_id": topic.node_id,
                "topic": topic.topic,
                "text": topic.conclusion_template,
                "fact_refs": fact_refs,
                "doctrine_refs": doctrine_refs,
                "source_refs": source_refs,
                "school": topic.school,
                "confidence": topic.confidence,
                "time_scope": topic.time_scope,
                "safety_class": topic.safety_class,
            }
            claims.append(
                StructuredClaim(
                    claim_id=f"claim_{_hash_payload(payload)[:24]}", **payload
                )
            )
        return CandidateReport(
            graph_sha256=graph.graph_sha256,
            claims=tuple(sorted(claims, key=lambda item: item.claim_id)),
        )

    def validate(self, candidate: CandidateReport, graph: AnalysisGraph) -> FirewallResult:
        violations: list[FirewallViolation] = []
        report_substituted = candidate.graph_sha256 != graph.graph_sha256
        if report_substituted:
            violations.append(
                FirewallViolation(
                    claim_id=None,
                    code="REPORT_GRAPH_SUBSTITUTED",
                    message="Candidate report graph identity does not match the analysis graph.",
                )
            )
        if len({claim.claim_id for claim in candidate.claims}) != len(candidate.claims):
            violations.append(
                FirewallViolation(
                    claim_id=None,
                    code="CLAIM_ID_DUPLICATE",
                    message="Candidate report contains duplicate claim identities.",
                )
            )
        topic_by_id = {node.node_id: node for node in graph.topic_nodes}
        rule_by_node = {node.node_id: node.rule_id for node in graph.rule_nodes}
        prohibited = {node.topic for node in graph.prohibition_nodes}
        invalid_ids: set[str] = set()
        for claim in candidate.claims:
            claim_violations: list[tuple[str, str]] = []
            topic = topic_by_id.get(claim.topic_node_id)
            if claim.graph_sha256 != graph.graph_sha256:
                claim_violations.append(
                    ("CLAIM_GRAPH_SUBSTITUTED", "Claim graph identity is invalid.")
                )
            if topic is None:
                claim_violations.append(
                    ("CLAIM_TOPIC_REF_FORGED", "Claim topic node does not exist.")
                )
            else:
                expected = self._expected_refs(topic, graph, rule_by_node)
                comparisons = (
                    (claim.text, topic.conclusion_template, "CLAIM_TEXT_UNSUPPORTED"),
                    (claim.topic, topic.topic, "CLAIM_TOPIC_MISMATCH"),
                    (claim.school, topic.school, "CLAIM_SCHOOL_MISMATCH"),
                    (claim.time_scope, topic.time_scope, "CLAIM_TIME_SCOPE_MISMATCH"),
                    (claim.safety_class, topic.safety_class, "CLAIM_SAFETY_CLASS_MISMATCH"),
                )
                for actual, wanted, code in comparisons:
                    if actual != wanted:
                        claim_violations.append((code, "Claim field is not graph-bound."))
                if claim.confidence > topic.confidence:
                    claim_violations.append(
                        ("CLAIM_CONFIDENCE_INFLATED", "Claim confidence exceeds the graph ceiling.")
                    )
                for actual, wanted, code in (
                    (claim.fact_refs, expected[0], "CLAIM_FACT_REF_FORGED"),
                    (claim.doctrine_refs, expected[1], "CLAIM_RULE_REF_FORGED"),
                    (claim.source_refs, expected[2], "CLAIM_SOURCE_REF_FORGED"),
                ):
                    if tuple(sorted(actual)) != wanted:
                        claim_violations.append((code, "Claim references do not match graph edges."))
            if claim.topic in prohibited:
                claim_violations.append(
                    ("CLAIM_TOPIC_PROHIBITED", "Claim topic is prohibited by the graph.")
                )
            if _PROMPT_INJECTION.search(claim.text):
                claim_violations.append(
                    ("CLAIM_PROMPT_INJECTION", "Claim contains instruction-channel language.")
                )
            if _PRIVATE_DATA.search(claim.text):
                claim_violations.append(
                    ("CLAIM_PRIVATE_DATA", "Claim contains private or internal data patterns.")
                )
            if _HIGH_STAKES.search(claim.text):
                claim_violations.append(
                    ("CLAIM_HIGH_STAKES", "Claim contains prohibited high-stakes language.")
                )
            if report_substituted or claim_violations:
                invalid_ids.add(claim.claim_id)
            violations.extend(
                FirewallViolation(claim_id=claim.claim_id, code=code, message=message)
                for code, message in claim_violations
            )
        if any(item.claim_id is None for item in violations):
            invalid_ids.update(claim.claim_id for claim in candidate.claims)
        valid = tuple(
            claim for claim in candidate.claims if claim.claim_id not in invalid_ids
        )
        return FirewallResult(valid_claims=valid, violations=tuple(violations))

    @staticmethod
    def _expected_refs(
        topic: TopicNode,
        graph: AnalysisGraph,
        rule_by_node: dict[str, str],
    ) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        edges = [edge for edge in graph.edges if edge.source_id == topic.node_id]
        facts = tuple(sorted(edge.target_id for edge in edges if edge.relation == "supported_by_fact"))
        rules = tuple(
            sorted(
                rule_by_node[edge.target_id]
                for edge in edges
                if edge.relation == "activated_by" and edge.target_id in rule_by_node
            )
        )
        sources = tuple(
            sorted(edge.target_id for edge in edges if edge.relation == "supported_by_source")
        )
        return facts, rules, sources

    def render(
        self,
        graph: AnalysisGraph,
        *,
        locale: Literal["ru", "en"],
        include_evidence: bool,
    ) -> RenderedReport:
        result = self.validate(self.candidate_from_graph(graph), graph)
        return self._render_result(
            graph,
            locale=locale,
            claims=result.valid_claims,
            violations=result.violations,
            repairs_attempted=0,
            include_evidence=include_evidence,
        )

    def render_with_repairs(
        self,
        graph: AnalysisGraph,
        producer: Producer,
        *,
        locale: Literal["ru", "en"],
        include_evidence: bool = False,
    ) -> RenderedReport:
        violations: tuple[FirewallViolation, ...] = ()
        result: FirewallResult | None = None
        repairs = 0
        for attempt in range(3):
            candidate = producer(attempt, violations)
            result = self.validate(candidate, graph)
            violations = result.violations
            if not violations:
                repairs = attempt
                break
            repairs = min(attempt, 2)
        assert result is not None
        return self._render_result(
            graph,
            locale=locale,
            claims=result.valid_claims,
            violations=result.violations,
            repairs_attempted=repairs,
            include_evidence=include_evidence,
        )

    def _render_result(
        self,
        graph: AnalysisGraph,
        *,
        locale: Literal["ru", "en"],
        claims: tuple[StructuredClaim, ...],
        violations: tuple[FirewallViolation, ...],
        repairs_attempted: int,
        include_evidence: bool,
    ) -> RenderedReport:
        if locale == "ru":
            lines = [
                "# Доктринальный анализ",
                "",
                "Статус допуска здесь не оценивается; его определяет вызывающий release-аудит.",
                "",
            ]
            empty = "Проверенных утверждений не осталось."
            uncertainty = "Неопределённость: выводы символические и ограничены указанной школой и источниками."
            evidence_title = "## Источники"
        else:
            lines = [
                "# Doctrine analysis",
                "",
                "Admission is not evaluated here; the calling release audit decides eligibility.",
                "",
            ]
            empty = "No validated claims remain."
            uncertainty = "Uncertainty: conclusions are symbolic and bounded by the named school and sources."
            evidence_title = "## Evidence"
        if claims:
            lines.extend(claim.text for claim in claims)
        else:
            lines.append(empty)
        lines.extend(["", uncertainty])
        if include_evidence:
            locators = self._public_locators(claims)
            if locators:
                lines.extend(["", evidence_title, ""])
                lines.extend(f"- {locator}" for locator in locators)
        markdown = "\n".join(lines).rstrip() + "\n"
        return RenderedReport(
            locale=locale,
            claims=claims,
            violations=violations,
            repairs_attempted=repairs_attempted,
            markdown=markdown,
            markdown_sha256=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
        )

    def _public_locators(self, claims: tuple[StructuredClaim, ...]) -> tuple[str, ...]:
        locators: set[str] = set()
        for claim in claims:
            for encoded in claim.source_refs:
                reference = _parse_source_target(encoded)
                fragment = self.evidence.resolve(reference, require_current=True)
                locators.add(
                    f"{fragment.source_id}, p. {fragment.printed_page}, {fragment.anchor_label}"
                )
        return tuple(sorted(locators))


_PROMPT_INJECTION = re.compile(
    r"ignore\s+(?:previous|system)|system\s+instructions|developer\s+message|prompt\s+injection",
    re.IGNORECASE,
)
_PRIVATE_DATA = re.compile(
    r"private_sources|source:frag_|\bfrag_[0-9a-f]+|anchor_token|facts_token|token\s*=|/Users/|\\Users\\",
    re.IGNORECASE,
)
_HIGH_STAKES = re.compile(
    r"\b(?:guarantee(?:d)?|death|longevity|diagnos(?:is|e)|medical procedure|legal advice|investment instruction|fertility diagnosis|remed(?:y|ies))\b",
    re.IGNORECASE,
)


def _parse_source_target(value: str) -> FragmentRef:
    try:
        prefix, fragment_id, revision, revision_sha256 = value.split(":", 3)
        if prefix != "source":
            raise ValueError
        return FragmentRef(
            fragment_id=fragment_id,
            revision=int(revision),
            revision_sha256=revision_sha256,
        )
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid internal source reference") from exc


def _hash_payload(payload: object) -> str:
    from ..research_store import canonical_json

    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
