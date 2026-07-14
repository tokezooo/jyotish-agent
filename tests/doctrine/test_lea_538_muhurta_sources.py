from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jyotish_agent.doctrine.muhurta_pack import (
    MuhurtaCorpusCatalog,
    MuhurtaCorpusRequirement,
    MuhurtaWorkedExampleCatalog,
    build_muhurta_corpus_coverage,
    render_muhurta_corpus_coverage,
)
from jyotish_agent.doctrine.sources import SourceVerifier, load_source_manifest


ROOT = Path(__file__).parents[2]
MANIFEST = ROOT / "src/jyotish_agent/data/doctrine/muhurta-sources.json"
CATALOG = ROOT / "src/jyotish_agent/data/doctrine/muhurta-corpus.json"
EXAMPLES = ROOT / "src/jyotish_agent/data/doctrine/muhurta-examples.json"


def _fixture_verification(tmp_path: Path):
    manifest = load_source_manifest(MANIFEST)
    private_root = tmp_path / "private_sources"
    payload = manifest.model_dump(mode="json")
    for source in payload["sources"]:
        candidate = private_root / source["local_file"]
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(f"fixture:{source['source_id']}".encode())
        source["sha256"] = hashlib.sha256(candidate.read_bytes()).hexdigest()
    fixture_manifest = type(manifest).model_validate(payload)
    return fixture_manifest, SourceVerifier.verify(fixture_manifest, private_root)


def test_catalog_declares_every_required_layer_without_blending() -> None:
    catalog = MuhurtaCorpusCatalog.model_validate_json(CATALOG.read_text())
    assert {item.requirement for item in catalog.requirements} == set(
        MuhurtaCorpusRequirement
    )
    assert catalog.requirement(
        MuhurtaCorpusRequirement.MUHURTA_CINTAMANI
    ).school_role == "baseline"
    assert catalog.requirement(
        MuhurtaCorpusRequirement.KALAPRAKASIKA
    ).school_role == "commentary"
    modern = catalog.requirement(MuhurtaCorpusRequirement.MODERN_OVERLAY)
    assert modern.school_role == "overlay"
    assert modern.source_ids == ()
    assert modern.acquisition_blocker is not None


def test_published_examples_are_traceable_and_not_outcome_claims() -> None:
    examples = MuhurtaWorkedExampleCatalog.model_validate_json(EXAMPLES.read_text())
    assert len(examples.examples) == 2
    assert examples.examples[0].source_printed_pages == (146,)
    assert examples.examples[1].source_printed_pages == (169, 170)
    assert all(item.example_kind == "worked_rule_illustration" for item in examples.examples)
    assert all(not item.observed_outcome_claimed for item in examples.examples)


def test_verified_public_domain_bytes_leave_only_modern_overlay_blocked(
    tmp_path: Path,
) -> None:
    manifest, verification = _fixture_verification(tmp_path)
    catalog = MuhurtaCorpusCatalog.model_validate_json(CATALOG.read_text())
    examples = MuhurtaWorkedExampleCatalog.model_validate_json(EXAMPLES.read_text())
    report = build_muhurta_corpus_coverage(manifest, verification, catalog, examples)

    assert not report.ready
    assert report.missing_requirements == (MuhurtaCorpusRequirement.MODERN_OVERLAY,)
    assert report.verified_worked_example_count == 2
    assert "medical" in report.unsupported_high_stakes_profiles
    assert "marriage" in report.unsupported_high_stakes_profiles
    assert set(report.covered_safe_profiles) == set(catalog.safe_profiles)


def test_offsets_rights_locality_and_private_projection() -> None:
    manifest = load_source_manifest(MANIFEST)
    by_id = {source.source_id: source for source in manifest.sources}
    assert by_id["muhurta_cintamani_1907"].page_offset == -4
    assert by_id["kalaprakasika_1982"].page_offset == -32
    assert by_id["muhurta_martanda_1819"].page_offset == -5
    assert all(source.license_class.value == "public_domain" for source in manifest.sources)

    catalog = MuhurtaCorpusCatalog.model_validate_json(CATALOG.read_text())
    examples = MuhurtaWorkedExampleCatalog.model_validate_json(EXAMPLES.read_text())
    report = build_muhurta_corpus_coverage(
        manifest,
        SourceVerifier.verify(manifest, ROOT / "private_sources"),
        catalog,
        examples,
    )
    projection = render_muhurta_corpus_coverage(report)
    rendered = json.dumps(projection, sort_keys=True)
    assert "private_sources" not in rendered
    assert ".pdf" not in rendered
    assert projection == json.loads(
        (ROOT / "docs/evidence/doctrine/muhurta-corpus-coverage.json").read_text()
    )


def test_real_private_sources_verify_when_available() -> None:
    manifest = load_source_manifest(MANIFEST)
    private_root = ROOT / "private_sources"
    if not all((private_root / source.local_file).exists() for source in manifest.sources):
        return
    verification = SourceVerifier.verify(manifest, private_root)
    assert verification.ok, verification.findings
