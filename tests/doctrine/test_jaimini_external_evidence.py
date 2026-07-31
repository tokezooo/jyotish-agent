from __future__ import annotations

import json
from pathlib import Path

from jyotish_agent.doctrine.jaimini_pack import (
    JaiminiCorpusCatalog,
    JaiminiCorpusRequirement,
    build_jaimini_corpus_coverage,
)
from jyotish_agent.doctrine.sources import SourceVerifier, load_source_manifest


ROOT = Path(__file__).parents[2]
MANIFEST = ROOT / "src/jyotish_agent/data/doctrine/jaimini-sources.json"
CATALOG = ROOT / "src/jyotish_agent/data/doctrine/jaimini-corpus.json"
AUDIT = ROOT / "docs/evidence/doctrine/jaimini-external-evidence.json"


def test_telegram_bundle_audit_is_hash_bound_private_and_honest() -> None:
    payload = json.loads(AUDIT.read_text(encoding="utf-8"))

    assert payload["archive_sha256"] == {
        "jaimini_part1_books_core": "e68f9a0a03cc317bc37c8129c92de64e7a89dda66b95c00e6aed98d90128d897",
        "jaimini_part2_jathakarajam": "3e96f2f185b88124b89407732b8aa50aef21f7b468d8aa5afe73ad1c50789387",
        "jaimini_part3_charts_pages": "022d28c1081e3f98d94b956fc26468a476d81db42fc59e5e315a28963bc54f82",
    }
    assert payload["pdf_count"] == 7
    assert payload["procurement_reference_count"] == 7
    assert payload["chart_candidates"]["supplied_count"] == 20
    assert payload["chart_candidates"]["adjudicated_worked_chart_count"] == 0
    assert payload["chart_candidates"]["independent_held_out_result_count"] == 0
    assert payload["duplicate_sources"] == [
        {
            "bundle_evidence_id": "bundle_pdf_02",
            "existing_source_id": "jaimini_sutras_vimala_achyutananda_jha_1943",
            "reason": "title-page and byte hash identify Vimala commentary, not Nilakantha Subodhini",
        }
    ]
    assert payload["activated_supplemental_source_ids"] == [
        "jaimini_jyotish_pradipika_chapter1_medavarapu_2016",
        "jaimini_jyotish_pradipika_corrections_medavarapu_2016",
        "jaimini_astro_databank_20_chart_candidates_2026",
    ]
    assert len(payload["page_commitments"]) == 8
    assert all(
        set(item) == {
            "source_id",
            "page_number",
            "printed_page",
            "normalized_sha256",
        }
        for item in payload["page_commitments"]
    )
    assert set(payload["remaining_requirements"]) == {
        "nilakantha_subodhini_translation",
        "practical_chara_dasha",
        "published_worked_charts",
        "sanjay_rath_overlay",
        "kn_rao_overlay",
    }
    rendered = json.dumps(payload, sort_keys=True)
    assert "private_sources" not in rendered
    assert ".pdf" not in rendered
    assert "/Users/" not in rendered


def test_verified_acquisitions_close_book_gaps_without_promoting_release() -> None:
    manifest = load_source_manifest(MANIFEST)
    catalog = JaiminiCorpusCatalog.model_validate_json(
        CATALOG.read_text(encoding="utf-8")
    )
    verification = SourceVerifier.verify(manifest, ROOT / "private_sources")
    assert verification.ok, verification.findings
    assert {
        "jaimini_jyotish_pradipika_chapter1_medavarapu_2016",
        "jaimini_jyotish_pradipika_corrections_medavarapu_2016",
        "jaimini_astro_databank_20_chart_candidates_2026",
    } <= set(verification.verified_source_ids)

    coverage = build_jaimini_corpus_coverage(manifest, verification, catalog)
    assert coverage.ready is False
    assert coverage.verified_worked_chart_count == 20
    assert coverage.missing_worked_chart_count == 0
    assert set(coverage.missing_requirements) == {
        JaiminiCorpusRequirement.NILAKANTHA_SUBODHINI_TRANSLATION,
    }
