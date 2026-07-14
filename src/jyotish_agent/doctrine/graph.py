"""Immutable deterministic analysis graph over signed facts and compiled doctrine."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import Field

from ..research_store import canonical_json
from .dsl import CompiledProfile, CompiledRule
from .evidence import EvidenceFailure, EvidenceStore, FragmentRef
from .models import FrozenModel
from .sources import Sha256


FactValue = str | int | float | bool | None


class GraphFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class SignedFactProjection(FrozenModel):
    artifact_id: str = Field(min_length=3, max_length=120)
    facts: dict[str, FactValue]
    provenance_sha256: Sha256
    artifact_sha256: Sha256

    @classmethod
    def create(
        cls,
        *,
        artifact_id: str,
        facts: dict[str, FactValue],
        provenance_sha256: str,
    ) -> "SignedFactProjection":
        payload = {
            "artifact_id": artifact_id,
            "facts": dict(facts),
            "provenance_sha256": provenance_sha256,
        }
        return cls(**payload, artifact_sha256=_hash_payload(payload))

    def identity_is_valid(self) -> bool:
        payload = self.model_dump(mode="json", exclude={"artifact_sha256"})
        return _hash_payload(payload) == self.artifact_sha256


class FactNode(FrozenModel):
    node_id: str
    path: str
    value: FactValue
    value_sha256: Sha256


class RuleNode(FrozenModel):
    node_id: str
    rule_id: str
    school: str
    status: Literal["activated", "inactive_premise", "inactive_dependency"]
    rule_sha256: Sha256


class TopicNode(FrozenModel):
    node_id: str
    rule_id: str
    topic: str
    school: str
    conclusion_template: str
    modality: str
    confidence: float
    time_scope: str
    safety_class: str


class ConflictNode(FrozenModel):
    node_id: str
    left_rule_id: str
    right_rule_id: str
    topic: str


class TimingNode(FrozenModel):
    node_id: str
    time_scope: str


class ProhibitionNode(FrozenModel):
    node_id: str
    topic: str
    reason_code: Literal["TOPIC_PROHIBITED"] = "TOPIC_PROHIBITED"


class GraphEdge(FrozenModel):
    source_id: str
    target_id: str
    relation: Literal[
        "activated_by", "supported_by_fact", "supported_by_source", "scoped_to", "conflicts_with"
    ]


class AnalysisGraph(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    fact_artifact_id: str
    fact_artifact_sha256: Sha256
    compiled_profile_sha256: Sha256
    evidence_store_sha256: Sha256
    fact_nodes: tuple[FactNode, ...]
    rule_nodes: tuple[RuleNode, ...]
    topic_nodes: tuple[TopicNode, ...]
    conflict_nodes: tuple[ConflictNode, ...]
    timing_nodes: tuple[TimingNode, ...]
    prohibition_nodes: tuple[ProhibitionNode, ...]
    edges: tuple[GraphEdge, ...]
    graph_sha256: Sha256


class DoctrineGraphBuilder:
    def __init__(self, evidence: EvidenceStore) -> None:
        self.evidence = evidence

    def build(
        self,
        profile: CompiledProfile,
        fact_projection: SignedFactProjection,
        *,
        prohibited_topics: tuple[str, ...] = (),
        max_nodes: int = 5_000,
        max_bytes: int = 512 * 1024,
    ) -> AnalysisGraph:
        if max_nodes < 1 or max_bytes < 1:
            raise ValueError("graph bounds must be positive")
        if not fact_projection.identity_is_valid():
            raise GraphFailure(
                "FACT_ARTIFACT_SUBSTITUTED", "Signed fact projection identity is invalid."
            )
        profile_payload = profile.model_dump(
            mode="json", exclude={"compiled_profile_sha256"}
        )
        if _hash_payload(profile_payload) != profile.compiled_profile_sha256:
            raise GraphFailure(
                "COMPILED_PROFILE_SUBSTITUTED", "Compiled doctrine profile identity is invalid."
            )
        for rule in profile.rules:
            for reference in rule.source_refs:
                try:
                    self.evidence.resolve(reference, require_current=True)
                except EvidenceFailure as exc:
                    raise GraphFailure(exc.code, str(exc)) from exc
        if profile.evidence_store_sha256 != self.evidence.store_sha256:
            raise GraphFailure(
                "EVIDENCE_STORE_SUBSTITUTED", "Compiled profile evidence store is no longer current."
            )

        rules = {rule.rule_id: rule for rule in profile.executable_rules}
        statuses = self._evaluate_statuses(rules, fact_projection.facts)
        active = {rule_id for rule_id, status in statuses.items() if status == "activated"}

        rule_nodes = tuple(
            RuleNode(
                node_id=_node_id("rule", rule.rule_id, rule.rule_sha256),
                rule_id=rule.rule_id,
                school=rule.school,
                status=statuses[rule.rule_id],
                rule_sha256=rule.rule_sha256,
            )
            for rule in sorted(rules.values(), key=lambda item: item.rule_id)
        )
        rule_node_by_id = {node.rule_id: node for node in rule_nodes}
        fact_paths = sorted(
            {
                premise.path
                for rule_id in active
                for premise in rules[rule_id].premises
                if premise.path in fact_projection.facts
            }
        )
        fact_nodes = tuple(
            FactNode(
                node_id=_node_id("fact", path, _hash_payload(fact_projection.facts[path])),
                path=path,
                value=fact_projection.facts[path],
                value_sha256=_hash_payload(fact_projection.facts[path]),
            )
            for path in fact_paths
        )
        fact_node_by_path = {node.path: node for node in fact_nodes}
        timing_scopes = sorted({rules[rule_id].time_scope for rule_id in active})
        timing_nodes = tuple(
            TimingNode(node_id=_node_id("timing", scope), time_scope=scope)
            for scope in timing_scopes
        )
        timing_by_scope = {node.time_scope: node for node in timing_nodes}
        topic_nodes = tuple(
            self._topic_node(rules[rule_id]) for rule_id in sorted(active)
        )
        topic_by_rule = {node.rule_id: node for node in topic_nodes}
        conflict_nodes = self._conflicts(rules, active)
        prohibition_nodes = tuple(
            ProhibitionNode(node_id=_node_id("prohibition", topic), topic=topic)
            for topic in sorted(set(prohibited_topics))
        )

        edges: list[GraphEdge] = []
        for rule_id in sorted(active):
            rule = rules[rule_id]
            topic_node = topic_by_rule[rule_id]
            edges.append(
                GraphEdge(
                    source_id=topic_node.node_id,
                    target_id=rule_node_by_id[rule_id].node_id,
                    relation="activated_by",
                )
            )
            for premise in rule.premises:
                if premise.path in fact_node_by_path:
                    edges.append(
                        GraphEdge(
                            source_id=topic_node.node_id,
                            target_id=fact_node_by_path[premise.path].node_id,
                            relation="supported_by_fact",
                        )
                    )
            for reference in rule.source_refs:
                edges.append(
                    GraphEdge(
                        source_id=topic_node.node_id,
                        target_id=_source_target(reference),
                        relation="supported_by_source",
                    )
                )
            edges.append(
                GraphEdge(
                    source_id=topic_node.node_id,
                    target_id=timing_by_scope[rule.time_scope].node_id,
                    relation="scoped_to",
                )
            )
        for conflict in conflict_nodes:
            edges.extend(
                [
                    GraphEdge(
                        source_id=conflict.node_id,
                        target_id=topic_by_rule[conflict.left_rule_id].node_id,
                        relation="conflicts_with",
                    ),
                    GraphEdge(
                        source_id=conflict.node_id,
                        target_id=topic_by_rule[conflict.right_rule_id].node_id,
                        relation="conflicts_with",
                    ),
                ]
            )
        edge_tuple = tuple(
            sorted(edges, key=lambda item: (item.source_id, item.relation, item.target_id))
        )
        payload = {
            "schema_version": "1.0",
            "fact_artifact_id": fact_projection.artifact_id,
            "fact_artifact_sha256": fact_projection.artifact_sha256,
            "compiled_profile_sha256": profile.compiled_profile_sha256,
            "evidence_store_sha256": self.evidence.store_sha256,
            "fact_nodes": [item.model_dump(mode="json") for item in fact_nodes],
            "rule_nodes": [item.model_dump(mode="json") for item in rule_nodes],
            "topic_nodes": [item.model_dump(mode="json") for item in topic_nodes],
            "conflict_nodes": [item.model_dump(mode="json") for item in conflict_nodes],
            "timing_nodes": [item.model_dump(mode="json") for item in timing_nodes],
            "prohibition_nodes": [item.model_dump(mode="json") for item in prohibition_nodes],
            "edges": [item.model_dump(mode="json") for item in edge_tuple],
        }
        node_count = sum(
            len(payload[key])
            for key in (
                "fact_nodes", "rule_nodes", "topic_nodes", "conflict_nodes",
                "timing_nodes", "prohibition_nodes",
            )
        )
        encoded = canonical_json(payload)
        if node_count > max_nodes or len(encoded.encode("utf-8")) > max_bytes:
            raise GraphFailure("GRAPH_PAYLOAD_LIMIT", "Analysis graph exceeds configured bounds.")
        return AnalysisGraph(**payload, graph_sha256=_hash_payload(payload))

    @staticmethod
    def _evaluate_statuses(
        rules: dict[str, CompiledRule], facts: dict[str, FactValue]
    ) -> dict[str, Literal["activated", "inactive_premise", "inactive_dependency"]]:
        pending = set(rules)
        statuses: dict[
            str, Literal["activated", "inactive_premise", "inactive_dependency"]
        ] = {}
        while pending:
            progressed = False
            for rule_id in sorted(tuple(pending)):
                rule = rules[rule_id]
                if any(dependency not in statuses for dependency in rule.depends_on):
                    continue
                if any(statuses[dependency] != "activated" for dependency in rule.depends_on):
                    status = "inactive_dependency"
                else:
                    status = "activated" if rule.matches(facts) else "inactive_premise"
                statuses[rule_id] = status
                pending.remove(rule_id)
                progressed = True
            if not progressed:  # compiler should make this unreachable
                raise GraphFailure("RULE_DEPENDENCY_CYCLE", "Compiled rule graph is not executable.")
        return statuses

    @staticmethod
    def _topic_node(rule: CompiledRule) -> TopicNode:
        payload = {
            "rule_id": rule.rule_id,
            "topic": rule.topic,
            "school": rule.school,
            "conclusion_template": rule.conclusion_template,
            "modality": rule.modality,
            "confidence": rule.confidence_ceiling,
            "time_scope": rule.time_scope,
            "safety_class": rule.safety_class,
        }
        return TopicNode(node_id=_node_id("topic", rule.rule_sha256), **payload)

    @staticmethod
    def _conflicts(
        rules: dict[str, CompiledRule], active: set[str]
    ) -> tuple[ConflictNode, ...]:
        pairs: set[tuple[str, str]] = set()
        for rule_id in active:
            for other in rules[rule_id].conflicts_with:
                if other in active:
                    pairs.add(tuple(sorted((rule_id, other))))
        return tuple(
            ConflictNode(
                node_id=_node_id("conflict", left, right),
                left_rule_id=left,
                right_rule_id=right,
                topic=rules[left].topic,
            )
            for left, right in sorted(pairs)
        )


def _source_target(reference: FragmentRef) -> str:
    return f"source:{reference.fragment_id}:{reference.revision}:{reference.revision_sha256}"


def _node_id(kind: str, *parts: str) -> str:
    return f"{kind}_{_hash_payload(parts)[:24]}"


def _hash_payload(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
