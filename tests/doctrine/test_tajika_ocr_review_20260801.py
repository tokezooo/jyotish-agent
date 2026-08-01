from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pypdf import PdfReader

from jyotish_agent.doctrine.sources import load_source_manifest


ROOT = Path(__file__).parents[2]
MANIFEST_PATH = ROOT / "src/jyotish_agent/data/doctrine/prashna-sources.json"
AUDIT_PATH = ROOT / "docs/evidence/doctrine/prashna-tajika-ocr-review.json"
RELEASE_PATH = ROOT / "docs/evidence/doctrine/prashna-release.json"
SOURCE_ID = "tajika_nilakanthi_1893"


def _audit() -> dict[str, object]:
    return json.loads(AUDIT_PATH.read_text(encoding="utf-8"))


def test_bounded_tajika_ocr_is_hash_bound_but_not_doctrine_admission() -> None:
    manifest = load_source_manifest(MANIFEST_PATH)
    source = next(item for item in manifest.sources if item.source_id == SOURCE_ID)
    audit = _audit()

    assert audit["source_id"] == SOURCE_ID
    assert audit["source_file_sha256"] == source.sha256
    assert audit["source_manifest_sha256"] == manifest.manifest_sha256
    assert audit["review_scope"] == (
        "Bounded candidate-page localization and technical OCR only; no "
        "translation, doctrine admission, or product activation."
    )
    assert audit["ocr"] == {
        "extractor": "pypdf raw /DCTDecode image stream",
        "name": "tesseract",
        "version": "5.5.2",
        "languages": ["san", "hin"],
        "psm": 6,
    }

    pages = audit["candidate_pages"]
    assert [page["pdf_page"] for page in pages] == [45, 46, 47]
    assert [(page["printed_page"], page["page_region"]) for page in pages] == [
        (19, "lower"),
        (20, "upper"),
        (20, "lower"),
    ]
    assert [page["topic"] for page in pages] == [
        "itthasala_definition_and_application_state",
        "itthasala_temporal_interpretation",
        "isarapha_separation_definition",
    ]
    assert all(page["source_page_image_sha256"] for page in pages)
    assert all(page["ocr_text_sha256"] for page in pages)
    assert all(0.0 < page["mean_word_confidence"] < 0.70 for page in pages)
    assert all(page["agent_visual_localization_review"] == "passed" for page in pages)
    assert all(
        page["transcription_review"] == "pending_specialist"
        for page in pages
    )
    assert all(
        page["disposition"] == "quarantined_translation_review"
        for page in pages
    )

    assert audit["source_ocr_status_after_review"] == "required"
    assert audit["doctrine_admitted"] is False
    assert audit["product_rule_use_allowed"] is False
    assert audit["tracked_source_text"] is False
    assert audit["translation_review_missing"] is True
    assert audit["specialist_review_missing"] is True
    assert source.ocr_status == "required"


def test_private_tajika_scan_replays_candidate_page_image_hashes() -> None:
    manifest = load_source_manifest(MANIFEST_PATH)
    source = next(item for item in manifest.sources if item.source_id == SOURCE_ID)
    private_path = ROOT / "private_sources" / source.local_file
    if not private_path.is_file():
        pytest.skip("private Tajika source is unavailable in this checkout")

    assert hashlib.sha256(private_path.read_bytes()).hexdigest() == source.sha256
    reader = PdfReader(private_path)
    for candidate in _audit()["candidate_pages"]:
        page = reader.pages[candidate["pdf_page"] - 1]
        xobjects = page["/Resources"]["/XObject"].get_object()
        image_streams = [
            ref.get_object()
            for ref in xobjects.values()
            if ref.get_object().get("/Subtype") == "/Image"
        ]
        assert len(image_streams) == 1
        assert hashlib.sha256(image_streams[0].get_data()).hexdigest() == (
            candidate["source_page_image_sha256"]
        )


def test_prashna_release_names_bounded_tajika_progress_without_passing_gate() -> None:
    release = json.loads(RELEASE_PATH.read_text(encoding="utf-8"))
    gate = next(
        item for item in release["gates"] if item["gate_id"] == "tajika_source_admission"
    )

    assert gate["status"] == "failed"
    assert "PDF pages 45-47" in gate["evidence"]
    assert "quarantined" in gate["evidence"]
    assert release["available"] is True
    assert release["admission_state"] == "experimental_full"
    assert next(
        item
        for item in release["gates"]
        if item["gate_id"] == "baseline_geometry_admission"
    )["status"] == "passed"
