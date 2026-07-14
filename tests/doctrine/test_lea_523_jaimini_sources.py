from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jyotish_agent.doctrine.jaimini_pack import (
    JaiminiCorpusCatalog,
    JaiminiCorpusRequirement,
    build_jaimini_corpus_coverage,
    render_jaimini_corpus_coverage,
)
from jyotish_agent.doctrine.sources import SourceVerifier, load_source_manifest


ROOT = Path(__file__).parents[2]
MANIFEST = ROOT / "src/jyotish_agent/data/doctrine/jaimini-sources.json"
CATALOG = ROOT / "src/jyotish_agent/data/doctrine/jaimini-corpus.json"


def _materialize_manifest(tmp_path: Path) -> tuple[object, Path]:
    manifest = load_source_manifest(MANIFEST)
    private_root = tmp_path / "private_sources"
    for source in manifest.sources:
        candidate = private_root / source.local_file
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(f"fixture:{source.source_id}".encode())
    return manifest, private_root


def _manifest_with_fixture_hashes(manifest: object, root: Path) -> object:
    payload = manifest.model_dump(mode="json")
    for source in payload["sources"]:
        path = root / source["local_file"]
        source["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return type(manifest).model_validate(payload)


def test_catalog_declares_every_required_role_and_topic_without_false_acquisition() -> (
    None
):
    catalog = JaiminiCorpusCatalog.model_validate_json(
        CATALOG.read_text(encoding="utf-8")
    )

    assert {item.requirement for item in catalog.requirements} == set(
        JaiminiCorpusRequirement
    )
    assert catalog.required_worked_chart_count == 20
    assert {
        "karaka",
        "karakamsa",
        "arudha",
        "argala",
        "rasi_drishti",
        "chara_dasha",
    } <= set(catalog.required_topics)
    missing = {item.requirement for item in catalog.requirements if not item.source_ids}
    assert JaiminiCorpusRequirement.NILAKANTHA_SUBODHINI_TRANSLATION in missing
    assert JaiminiCorpusRequirement.SANJAY_RATH_OVERLAY in missing
    assert JaiminiCorpusRequirement.KN_RAO_OVERLAY in missing


def test_coverage_requires_verified_bytes_and_does_not_count_missing_books(
    tmp_path: Path,
) -> None:
    manifest, private_root = _materialize_manifest(tmp_path)
    manifest = _manifest_with_fixture_hashes(manifest, private_root)
    verification = SourceVerifier.verify(manifest, private_root)
    catalog = JaiminiCorpusCatalog.model_validate_json(
        CATALOG.read_text(encoding="utf-8")
    )

    report = build_jaimini_corpus_coverage(manifest, verification, catalog)

    assert report.verified_source_ids == tuple(
        sorted(source.source_id for source in manifest.sources)
    )
    assert report.ready is False
    assert (
        JaiminiCorpusRequirement.SANSKRIT_UPADESA_SUTRAS in report.covered_requirements
    )
    assert (
        JaiminiCorpusRequirement.INDEPENDENT_TRANSLATION in report.covered_requirements
    )
    assert (
        JaiminiCorpusRequirement.NILAKANTHA_SUBODHINI_TRANSLATION
        in report.missing_requirements
    )
    assert report.verified_worked_chart_count == 0
    assert report.missing_worked_chart_count == 20


def test_hash_mismatch_and_low_quality_are_explicit_and_page_offsets_are_tested(
    tmp_path: Path,
) -> None:
    manifest, private_root = _materialize_manifest(tmp_path)
    verification = SourceVerifier.verify(manifest, private_root)
    catalog = JaiminiCorpusCatalog.model_validate_json(
        CATALOG.read_text(encoding="utf-8")
    )

    report = build_jaimini_corpus_coverage(manifest, verification, catalog)

    assert report.verified_source_ids == ()
    assert set(report.unverified_source_ids) == {
        source.source_id for source in manifest.sources
    }
    assert report.low_quality_source_ids == ("jaimini_sutras_b_suryanarain_rao_1949",)
    by_id = {source.source_id: source for source in manifest.sources}
    assert by_id["jaimini_sutras_b_suryanarain_rao_1949"].page_offset == -17
    assert by_id["jaimini_sutras_vimala_achyutananda_jha_1943"].page_offset == -3


def test_coverage_projection_is_deterministic_private_and_matches_tracked_audit(
    tmp_path: Path,
) -> None:
    manifest, private_root = _materialize_manifest(tmp_path)
    catalog = JaiminiCorpusCatalog.model_validate_json(
        CATALOG.read_text(encoding="utf-8")
    )
    verification = SourceVerifier.verify(manifest, private_root)
    report = build_jaimini_corpus_coverage(manifest, verification, catalog)

    first = render_jaimini_corpus_coverage(report)
    second = render_jaimini_corpus_coverage(report)
    assert first == second
    rendered = json.dumps(first, sort_keys=True)
    assert str(private_root) not in rendered
    assert ".pdf" not in rendered

    tracked = json.loads(
        (ROOT / "docs/evidence/doctrine/jaimini-corpus-coverage.json").read_text(
            encoding="utf-8"
        )
    )
    assert tracked["ready"] is False
    assert "nilakantha_subodhini_translation" in tracked["missing_requirements"]
    assert tracked["acquisition_blockers"]


def test_real_private_sources_verify_when_available() -> None:
    manifest = load_source_manifest(MANIFEST)
    private_root = ROOT / "private_sources"
    if not all(
        (private_root / source.local_file).exists() for source in manifest.sources
    ):
        return

    report = SourceVerifier.verify(manifest, private_root)
    assert report.ok, report.findings
