from __future__ import annotations

import json
from pathlib import Path

from jyotish_agent.doctrine.muhurta_pack import (
    MuhurtaCorpusCatalog,
    MuhurtaCorpusRequirement,
)


ROOT = Path(__file__).parents[2]
AUDIT_PATH = (
    ROOT / "docs/evidence/doctrine/muhurta-modern-overlay-acquisition.json"
)
CATALOG_PATH = ROOT / "src/jyotish_agent/data/doctrine/muhurta-corpus.json"
COVERAGE_PATH = ROOT / "docs/evidence/doctrine/muhurta-corpus-coverage.json"
RELEASE_PATH = ROOT / "docs/evidence/doctrine/muhurta-release.json"


def test_muhurta_overlay_target_is_exact_and_lawful_gap_is_explicit() -> None:
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))

    assert audit["preferred_target_edition"] == {
        "title": "Muhurtha (Electional Astrology)",
        "author": "B. V. Raman",
        "publisher": "Motilal Banarsidass Publishing House",
        "year": 2026,
        "edition": "1st MLBD edition",
        "pages": 227,
        "language": "en",
        "binding": "paperback",
        "isbn_10": "9359662925",
        "isbn_13": "9789359662923",
    }
    assert audit["accepted_alternate_edition"] == {
        "title": "Muhurtha (Electional Astrology)",
        "author": "B. V. Raman",
        "publisher": "UBS Publishers Distributors",
        "year": 1993,
        "pages": 181,
        "language": "en",
        "isbn_10": "818567468X",
        "isbn_13": "9788185674681",
        "oclc": "314072888",
        "open_library_id": "OL9860226M",
    }
    assert audit["local_overlay_match_count"] == 0
    assert audit["acquisition_state"] == "missing_licensed_bytes"
    assert audit["unlicensed_download_attempted"] is False
    assert audit["source_admitted"] is False
    assert audit["overlay_enabled"] is False
    assert audit["baseline_release_affected"] is False
    assert audit["high_stakes_profiles_remain_blocked"] is True

    rendered = json.dumps(audit, sort_keys=True)
    assert "private_sources" not in rendered
    assert "/Users/" not in rendered


def test_corpus_and_release_name_the_exact_optional_overlay_blocker() -> None:
    catalog = MuhurtaCorpusCatalog.model_validate_json(CATALOG_PATH.read_text())
    modern = catalog.requirement(MuhurtaCorpusRequirement.MODERN_OVERLAY)
    coverage = json.loads(COVERAGE_PATH.read_text(encoding="utf-8"))
    release = json.loads(RELEASE_PATH.read_text(encoding="utf-8"))
    gate = next(item for item in release["gates"] if item["gate_id"] == "modern_overlay")

    assert modern.source_ids == ()
    assert "B. V. Raman" in modern.acquisition_blocker
    assert "9789359662923" in modern.acquisition_blocker
    assert coverage["acquisition_blockers"] == [
        f"modern_overlay: {modern.acquisition_blocker}"
    ]
    assert gate["status"] == "optional_missing"
    assert gate["evidence"] is None
    assert any("9789359662923" in item for item in release["future_follow_up"])
    assert any("9789359662923" in item for item in release["public_release_blockers"])
    assert release["admission_state"] == "private_experimental"
    assert release["available"] is True
