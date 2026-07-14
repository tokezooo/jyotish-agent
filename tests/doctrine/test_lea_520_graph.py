from __future__ import annotations

import concurrent.futures
import hashlib

import pytest
from pydantic import ValidationError

from jyotish_agent.doctrine.dsl import (
    DoctrineCompiler,
    ProfileDefinition,
    RuleDefinition,
)
from jyotish_agent.doctrine.evidence import EvidenceStore, FragmentDraft, FragmentRef
from jyotish_agent.doctrine.graph import (
    DoctrineGraphBuilder,
    GraphFailure,
    SignedFactProjection,
)
from jyotish_agent.doctrine.sources import SourceManifest
from jyotish_agent.signing import cache_domain_artifact


def _fixture() -> tuple[EvidenceStore, object, FragmentDraft]:
    manifest = SourceManifest.model_validate(
        {
            "schema_version": "1.0",
            "sources": [
                {
                    "source_id": "graph_source_v1",
                    "title": "Graph fixture",
                    "author_or_commentator": "Fixture author",
                    "translator_editor": None,
                    "edition": "Fixture edition",
                    "publisher": None,
                    "year": 2026,
                    "isbn": None,
                    "languages": ["en"],
                    "domain": "jaimini",
                    "school_role": "baseline",
                    "license_class": "public_domain",
                    "local_file": "jaimini/graph/source.pdf",
                    "sha256": hashlib.sha256(b"source").hexdigest(),
                    "page_offset": 0,
                    "scan_quality": "born_digital",
                    "ocr_required": False,
                    "ocr_status": "not_required",
                }
            ],
        }
    )
    store = EvidenceStore(manifest)
    text = "Permitted symbolic career source."
    draft = FragmentDraft(
        source_id="graph_source_v1",
        source_manifest_sha256=manifest.manifest_sha256,
        page_number=1,
        printed_page=1,
        anchor_kind="sutra",
        anchor_label="1.1",
        language="en",
        content_role="root_text",
        school="baseline_school",
        scope="career",
        full_text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        normalized_content_sha256=hashlib.sha256(text.encode()).hexdigest(),
        excerpt_permission="public_domain",
        permitted_excerpt=text,
        admission_status="admitted",
    )
    reference = FragmentRef.from_fragment(store.append(draft))
    profile = ProfileDefinition(
        profile_id="graph_baseline_v1",
        version="1.0.0",
        school="baseline_school",
        profile_kind="baseline",
        base_profile_sha256=None,
    )

    def rule(rule_id: str, path: str, value: str, **updates: object) -> RuleDefinition:
        payload: dict[str, object] = {
            "rule_id": rule_id,
            "version": "1.0.0",
            "profile_id": profile.profile_id,
            "school": profile.school,
            "topic": "career",
            "premises": [{"path": path, "operator": "equals", "value": value}],
            "exclusions": [],
            "depends_on": [],
            "conflicts_with": [],
            "supersedes": [],
            "conclusion_template": f"{rule_id} symbolic synthesis input.",
            "modality": "symbolic",
            "confidence_ceiling": 0.65,
            "time_scope": "natal",
            "safety_class": "safe_symbolic",
            "source_refs": [reference.model_dump(mode="json")],
        }
        payload.update(updates)
        return RuleDefinition.model_validate(payload)

    first = rule(
        "graph.rule.first",
        "jaimini.karakas.AmK.planet",
        "Mercury",
        conflicts_with=["graph.rule.alternative"],
    )
    alternative = rule(
        "graph.rule.alternative",
        "jaimini.arudha.AL.sign",
        "Leo",
        school="baseline_school",
        conflicts_with=["graph.rule.first"],
    )
    dependent = rule(
        "graph.rule.dependent",
        "jaimini.dasha.active.sign",
        "Gemini",
        depends_on=["graph.rule.first"],
        time_scope="period",
        confidence_ceiling=0.60,
    )
    compiled = DoctrineCompiler(store).compile(
        profile,
        [dependent, alternative, first],
        fact_catalog=frozenset(
            {
                "jaimini.karakas.AmK.planet",
                "jaimini.arudha.AL.sign",
                "jaimini.dasha.active.sign",
            }
        ),
    )
    return store, compiled, draft


def _facts(**updates: object) -> SignedFactProjection:
    facts: dict[str, object] = {
        "jaimini.karakas.AmK.planet": "Mercury",
        "jaimini.arudha.AL.sign": "Leo",
        "jaimini.dasha.active.sign": "Gemini",
    }
    facts.update(updates)
    artifact = cache_domain_artifact(
        {
            "mode": "test",
            "facts": facts,
            "provenance_sha256": hashlib.sha256(b"provenance").hexdigest(),
        }
    )
    return SignedFactProjection.from_artifact_token(
        artifact_token=artifact["artifact_token"],
        allowed_fact_paths=tuple(facts),
    )


def test_same_inputs_are_order_independent_and_every_conclusion_has_complete_edges() -> (
    None
):
    store, compiled, _ = _fixture()
    builder = DoctrineGraphBuilder(store)
    first = builder.build(compiled, _facts(), prohibited_topics=("medical",))
    reverse_values = dict(reversed(list(_facts().facts.items())))
    reverse_artifact = cache_domain_artifact(
        {
            "mode": "test",
            "facts": reverse_values,
            "provenance_sha256": hashlib.sha256(b"provenance").hexdigest(),
        }
    )
    reverse = SignedFactProjection.from_artifact_token(
        artifact_token=reverse_artifact["artifact_token"],
        allowed_fact_paths=tuple(reverse_values),
    )
    second = builder.build(compiled, reverse, prohibited_topics=("medical",))

    assert first == second
    assert first.graph_sha256 == second.graph_sha256
    assert {node.topic for node in first.topic_nodes} == {"career"}
    assert len(first.prohibition_nodes) == 1
    for node in first.topic_nodes:
        edge_types = {
            edge.relation for edge in first.edges if edge.source_id == node.node_id
        }
        assert {
            "activated_by",
            "supported_by_fact",
            "supported_by_source",
            "scoped_to",
        } <= edge_types


def test_dependency_activation_and_absent_facts_never_create_stale_citations() -> None:
    store, compiled, _ = _fixture()
    facts = _facts(**{"jaimini.karakas.AmK.planet": "Venus"})
    graph = DoctrineGraphBuilder(store).build(compiled, facts)

    statuses = {node.rule_id: node.status for node in graph.rule_nodes}
    assert statuses["graph.rule.first"] == "inactive_premise"
    assert statuses["graph.rule.dependent"] == "inactive_dependency"
    assert "jaimini.karakas.AmK.planet" not in {node.path for node in graph.fact_nodes}
    assert not any(
        node.rule_id in {"graph.rule.first", "graph.rule.dependent"}
        for node in graph.topic_nodes
    )


def test_conflicts_and_school_variants_are_explicit() -> None:
    store, compiled, _ = _fixture()
    graph = DoctrineGraphBuilder(store).build(compiled, _facts())
    assert len(graph.conflict_nodes) == 1
    conflict = graph.conflict_nodes[0]
    assert {conflict.left_rule_id, conflict.right_rule_id} == {
        "graph.rule.first",
        "graph.rule.alternative",
    }
    assert {node.school for node in graph.topic_nodes} == {"baseline_school"}


def test_substituted_fact_profile_and_stale_source_fail_closed() -> None:
    store, compiled, draft = _fixture()
    builder = DoctrineGraphBuilder(store)
    facts = _facts()
    with pytest.raises(GraphFailure) as bad_facts:
        builder.build(
            compiled,
            facts.model_copy(update={"facts": {**facts.facts, "invented": True}}),
        )
    assert bad_facts.value.code == "FACT_ARTIFACT_SUBSTITUTED"

    forged = facts.model_copy(
        update={
            "facts": {**facts.facts, "jaimini.karakas.AmK.planet": "Jupiter"},
            "artifact_sha256": hashlib.sha256(b"self-hashed-forgery").hexdigest(),
        }
    )
    with pytest.raises(GraphFailure) as forged_facts:
        builder.build(compiled, forged)
    assert forged_facts.value.code == "FACT_ARTIFACT_SUBSTITUTED"

    with pytest.raises(GraphFailure) as bad_profile:
        builder.build(
            compiled.model_copy(update={"compiled_profile_sha256": "f" * 64}),
            facts,
        )
    assert bad_profile.value.code == "COMPILED_PROFILE_SUBSTITUTED"

    store.append(
        draft.model_copy(
            update={
                "full_text_sha256": hashlib.sha256(b"changed").hexdigest(),
                "normalized_content_sha256": hashlib.sha256(b"changed").hexdigest(),
                "permitted_excerpt": "Changed permitted source.",
            }
        )
    )
    with pytest.raises(GraphFailure) as stale:
        builder.build(compiled, facts)
    assert stale.value.code == "SOURCE_FRAGMENT_STALE"


def test_graph_is_frozen_bounded_and_stably_serialized() -> None:
    store, compiled, _ = _fixture()
    builder = DoctrineGraphBuilder(store)
    graph = builder.build(compiled, _facts())
    with pytest.raises(ValidationError):
        graph.graph_sha256 = "f" * 64  # type: ignore[misc]
    assert len(graph.model_dump_json()) < 64_000
    with pytest.raises(GraphFailure) as nodes:
        builder.build(compiled, _facts(), max_nodes=2)
    assert nodes.value.code == "GRAPH_PAYLOAD_LIMIT"
    with pytest.raises(GraphFailure) as payload:
        builder.build(compiled, _facts(), max_bytes=100)
    assert payload.value.code == "GRAPH_PAYLOAD_LIMIT"


def test_concurrent_graph_construction_is_identical() -> None:
    store, compiled, _ = _fixture()
    builder = DoctrineGraphBuilder(store)
    facts = _facts()
    expected = builder.build(compiled, facts)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: builder.build(compiled, facts), range(32)))
    assert all(result == expected for result in results)
