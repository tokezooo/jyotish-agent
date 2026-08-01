from __future__ import annotations

import json
from pathlib import Path

from jyotish_agent.doctrine.sources import load_source_manifest


ROOT = Path(__file__).parents[2]
AUDIT_PATH = ROOT / "docs/evidence/doctrine/prashna-tajika-translation-acquisition.json"
MANIFEST_PATH = ROOT / "src/jyotish_agent/data/doctrine/prashna-sources.json"
RELEASE_PATH = ROOT / "docs/evidence/doctrine/prashna-release.json"


def test_tajika_translation_target_is_exact_and_local_gap_is_explicit() -> None:
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    target = audit["target_edition"]

    assert target == {
        "title": "Tajik Nilkanthi = Tajika Nilakanthi",
        "author": "Nilakantha",
        "translator_commentator": "D. P. Saxena",
        "publisher": "Ranjan Publications",
        "publication_place": "New Delhi",
        "year": 2001,
        "edition": "1st edition",
        "pages": 334,
        "languages": ["en", "sa"],
        "lccn": "2001361798",
        "oclc": "48507695",
        "open_library_id": "OL4006298M",
    }
    assert audit["local_translation_match_count"] == 0
    assert audit["acquisition_state"] == "missing_licensed_bytes"
    assert audit["unlicensed_download_attempted"] is False
    assert audit["source_admitted"] is False
    assert audit["product_rule_use_allowed"] is False
    assert {item["catalog"] for item in audit["catalog_evidence"]} == {
        "New York Public Library",
        "Open Library",
    }

    rendered = json.dumps(audit, sort_keys=True)
    assert "private_sources" not in rendered
    assert "/Users/" not in rendered


def test_existing_sanskrit_scan_is_not_mislabeled_as_the_missing_translation() -> None:
    manifest = load_source_manifest(MANIFEST_PATH)
    source = next(
        item for item in manifest.sources if item.source_id == "tajika_nilakanthi_1893"
    )
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    release = json.loads(RELEASE_PATH.read_text(encoding="utf-8"))
    gate = next(
        item for item in release["gates"] if item["gate_id"] == "tajika_source_admission"
    )

    assert source.languages == ("sa",)
    assert source.translator_editor is None
    assert audit["existing_sanskrit_source_sha256"] == source.sha256
    assert gate["status"] == "failed"
    assert "D. P. Saxena" in gate["evidence"]
    assert "LCCN 2001361798" in gate["evidence"]
    assert release["available"] is True
    assert release["admission_state"] == "experimental_full"
    assert next(
        item
        for item in release["gates"]
        if item["gate_id"] == "baseline_geometry_admission"
    )["status"] == "passed"
