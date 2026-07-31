from __future__ import annotations

import json
from pathlib import Path

from jyotish_agent.doctrine.sources import SourceVerifier, load_source_manifest


ROOT = Path(__file__).parents[2]
AUDIT = ROOT / "docs/evidence/doctrine/jaimini-acquisition-2026-07-31.json"
MANIFEST = ROOT / "src/jyotish_agent/data/doctrine/jaimini-sources.json"


def test_acquisition_audit_is_hash_bound_private_and_does_not_claim_admission() -> None:
    payload = json.loads(AUDIT.read_text(encoding="utf-8"))

    assert {item["source_id"] for item in payload["verified_sources"]} == {
        "jaimini_sanjay_rath_upadesa_sutras_1997",
        "jaimini_sanjay_rath_narayana_dasa_2004",
        "jaimini_kn_rao_chara_dasha_vani_scan_2010",
    }
    normalization = payload["normalizations"][0]
    assert normalization["input_page_count"] == 97
    assert normalization["output_page_count"] == 194
    assert normalization["visual_checks"] == [1, 2, 193, 194]
    review = payload["worked_chart_review"]
    assert review["reviewed_count"] == 20
    assert len(review["page_anchors"]) == 20
    assert [item["chart_number"] for item in review["page_anchors"]] == list(
        range(21, 41)
    )
    assert all(
        item["printed_page"] == item["pdf_page"] - 13
        for item in review["page_anchors"]
    )
    assert review["independent_held_out_result_count"] == 0
    assert review["doctrine_admitted"] is False
    assert review["product_rule_use_allowed"] is False
    assert payload["remaining_acquisition_requirements"] == [
        "nilakantha_subodhini_translation"
    ]
    assert payload["release_promoted"] is False

    rendered = json.dumps(payload, sort_keys=True)
    assert "private_sources" not in rendered
    assert ".pdf" not in rendered
    assert "/Users/" not in rendered


def test_new_active_source_bytes_verify_when_private_files_are_present() -> None:
    manifest = load_source_manifest(MANIFEST)
    report = SourceVerifier.verify(manifest, ROOT / "private_sources")
    assert report.ok, report.findings
    assert {
        "jaimini_sanjay_rath_upadesa_sutras_1997",
        "jaimini_sanjay_rath_narayana_dasa_2004",
        "jaimini_kn_rao_chara_dasha_vani_scan_2010",
    } <= set(report.verified_source_ids)
