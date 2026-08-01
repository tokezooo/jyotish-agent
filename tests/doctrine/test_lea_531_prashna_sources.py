from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jyotish_agent.doctrine.prashna_pack import (
    PrashnaCaseCatalog,
    PrashnaCorpusCatalog,
    PrashnaCorpusRequirement,
    build_prashna_corpus_coverage,
    render_prashna_corpus_coverage,
)
from jyotish_agent.doctrine.sources import SourceVerifier, load_source_manifest


ROOT = Path(__file__).parents[2]
MANIFEST = ROOT / "src/jyotish_agent/data/doctrine/prashna-sources.json"
CATALOG = ROOT / "src/jyotish_agent/data/doctrine/prashna-corpus.json"
CASES = ROOT / "src/jyotish_agent/data/doctrine/prashna-cases.json"


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


def test_catalog_separates_baseline_tajika_and_published_cases() -> None:
    catalog = PrashnaCorpusCatalog.model_validate_json(CATALOG.read_text())
    assert {item.requirement for item in catalog.requirements} == set(
        PrashnaCorpusRequirement
    )
    baseline = catalog.requirement(PrashnaCorpusRequirement.PRASNA_MARGA_BASELINE)
    overlay = catalog.requirement(PrashnaCorpusRequirement.TAJIKA_ASPECT_OVERLAY)
    assert baseline.school == "prasna_marga_baseline"
    assert overlay.school == "tajika_nilakanthi_overlay"
    assert set(baseline.source_ids).isdisjoint(overlay.source_ids)
    assert catalog.required_published_case_count == 2


def test_case_metadata_is_traceable_and_high_stakes_cases_are_excluded() -> None:
    cases = PrashnaCaseCatalog.model_validate_json(CASES.read_text())
    by_id = {case.case_id: case for case in cases.cases}

    marriage = by_id["raman_1983_marriage_alliance_broke_off"]
    assert marriage.question_at == "1983-03-31T18:30:00+05:30"
    assert marriage.place_label == "Bangalore, India"
    assert marriage.source_pdf_pages == (22, 23)
    assert marriage.judgment == "negative"
    assert marriage.observed_outcome == "alliance_broke_off"
    assert marriage.admissibility == "excluded_high_stakes"

    teaching = by_id["saxena_2019_teaching_session_interrupted"]
    assert teaching.question_at == "2019-12-15T13:30:00+05:30"
    assert teaching.place_label == "Delhi, India"
    assert teaching.question_class == "work_project_status"
    assert teaching.source_pdf_pages == (2, 3)
    assert teaching.source_printed_pages == (2, 3)
    assert teaching.judgment == "mixed"
    assert (
        teaching.observed_outcome
        == "teaching_continued_until_2020_03_08_then_classes_suspended"
    )
    assert teaching.admissibility == "admitted_safe"
    assert cases.verified_outcome_count == 2


def test_verified_bytes_and_two_traceable_cases_complete_acquisition(
    tmp_path: Path,
) -> None:
    manifest, verification = _fixture_verification(tmp_path)
    catalog = PrashnaCorpusCatalog.model_validate_json(CATALOG.read_text())
    cases = PrashnaCaseCatalog.model_validate_json(CASES.read_text())
    report = build_prashna_corpus_coverage(manifest, verification, catalog, cases)

    assert report.ready
    assert report.verified_source_ids == tuple(
        sorted(source.source_id for source in manifest.sources)
    )
    assert report.verified_published_case_count == 2
    assert report.missing_published_case_count == 0
    assert "published_cases" in report.covered_requirements
    assert "published_cases" not in report.missing_requirements
    assert "relationship_marriage" in report.unsupported_question_classes
    assert "medical" in report.unsupported_question_classes


def test_page_offsets_copyright_locality_and_private_projection() -> None:
    manifest = load_source_manifest(MANIFEST)
    by_id = {source.source_id: source for source in manifest.sources}
    assert by_id["prasna_marga_bv_raman_part_1_1991"].page_offset == 0
    assert by_id["prasna_marga_bv_raman_part_2_1992"].page_offset == -16
    assert by_id["satpancasika_sanskritdocuments_2016"].page_offset == -2
    assert by_id["tajika_nilakanthi_1893"].page_offset == -11
    assert (
        by_id["prasna_marga_bv_raman_part_1_1991"].license_class.value
        == "copyrighted_local"
    )

    catalog = PrashnaCorpusCatalog.model_validate_json(CATALOG.read_text())
    cases = PrashnaCaseCatalog.model_validate_json(CASES.read_text())
    report = build_prashna_corpus_coverage(
        manifest,
        SourceVerifier.verify(manifest, ROOT / "private_sources"),
        catalog,
        cases,
    )
    projection = render_prashna_corpus_coverage(report)
    rendered = json.dumps(projection, sort_keys=True)
    assert "private_sources" not in rendered
    assert ".pdf" not in rendered
    assert projection == json.loads(
        (ROOT / "docs/evidence/doctrine/prashna-corpus-coverage.json").read_text()
    )


def test_real_private_sources_verify_when_available() -> None:
    manifest = load_source_manifest(MANIFEST)
    private_root = ROOT / "private_sources"
    if not all(
        (private_root / source.local_file).exists() for source in manifest.sources
    ):
        return
    verification = SourceVerifier.verify(manifest, private_root)
    assert verification.ok, verification.findings
