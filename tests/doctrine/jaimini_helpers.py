from __future__ import annotations

import hashlib
from collections.abc import Iterable

from jyotish_agent.doctrine.dsl import (
    DoctrineCompiler,
    ProfileDefinition,
    RuleDefinition,
)
from jyotish_agent.doctrine.evidence import EvidenceStore, FragmentDraft, FragmentRef
from jyotish_agent.doctrine.graph import (
    AnalysisGraph,
    DoctrineGraphBuilder,
    SignedFactProjection,
)
from jyotish_agent.doctrine.sources import SourceManifest
from jyotish_agent.signing import cache_domain_artifact


def build_jaimini_graph(
    *,
    facts: dict[str, object],
    rules: Iterable[dict[str, object]],
    school: str = "nilakantha_baseline",
    artifact_id: str = "dom_jaimini_topic_fixture",
) -> AnalysisGraph:
    manifest = SourceManifest.model_validate(
        {
            "schema_version": "1.0",
            "sources": [
                {
                    "source_id": "jaimini_topic_fixture",
                    "title": "Public Jaimini topic fixture",
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
                    "local_file": "jaimini/fixture.pdf",
                    "sha256": hashlib.sha256(b"source").hexdigest(),
                    "page_offset": 0,
                    "scan_quality": "born_digital",
                    "ocr_required": False,
                    "ocr_status": "not_required",
                }
            ],
        }
    )
    evidence = EvidenceStore(manifest)
    text = "Public fixture evidence for bounded symbolic Jaimini testing."
    fragment = evidence.append(
        FragmentDraft(
            source_id="jaimini_topic_fixture",
            source_manifest_sha256=manifest.manifest_sha256,
            page_number=1,
            printed_page=1,
            anchor_kind="sutra",
            anchor_label="fixture.1",
            language="en",
            content_role="root_text",
            school=school,
            scope="jaimini_topic_fixture",
            full_text_sha256=hashlib.sha256(text.encode()).hexdigest(),
            normalized_content_sha256=hashlib.sha256(text.encode()).hexdigest(),
            excerpt_permission="public_domain",
            permitted_excerpt=text,
            admission_status="admitted",
        )
    )
    reference = FragmentRef.from_fragment(fragment)
    profile = ProfileDefinition(
        profile_id="jaimini_topic_fixture_v1",
        version="1.0.0",
        school=school,
        profile_kind="baseline",
    )
    definitions: list[RuleDefinition] = []
    for raw in rules:
        payload = {
            "version": "1.0.0",
            "profile_id": profile.profile_id,
            "school": school,
            "exclusions": [],
            "depends_on": [],
            "conflicts_with": [],
            "supersedes": [],
            "conclusion_template": "A bounded symbolic signal is supported.",
            "modality": "symbolic",
            "confidence_ceiling": 0.65,
            "time_scope": "natal",
            "safety_class": "safe_symbolic",
            "source_refs": [reference.model_dump(mode="json")],
            **raw,
        }
        definitions.append(RuleDefinition.model_validate(payload))
    compiled = DoctrineCompiler(evidence).compile(
        profile,
        definitions,
        fact_catalog=frozenset(facts),
    )
    artifact = cache_domain_artifact(
        {
            "mode": "test",
            "fixture_artifact_id": artifact_id,
            "facts": facts,
            "provenance_sha256": hashlib.sha256(b"fixture-provenance").hexdigest(),
        }
    )
    projection = SignedFactProjection.from_artifact_token(
        artifact_token=artifact["artifact_token"],
        allowed_fact_paths=tuple(facts),
    )
    return DoctrineGraphBuilder(evidence).build(
        compiled,
        projection,
        prohibited_topics=(
            "medical",
            "longevity",
            "death",
            "fertility",
            "guaranteed_marriage",
        ),
    )
