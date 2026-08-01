from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from jyotish_agent.doctrine.muhurta_pack import (
    MuhurtaModernOverlayLedger,
    load_muhurta_modern_overlay_ledger,
)


ROOT = Path(__file__).parents[2]
LEDGER_PATH = (
    ROOT
    / "src/jyotish_agent/data/doctrine/muhurta-modern-overlay-fragments.json"
)


def test_bv_raman_overlay_is_page_mapped_but_structurally_quarantined() -> None:
    ledger = load_muhurta_modern_overlay_ledger()
    fragment = ledger.fragments[0]
    comparison = ledger.comparisons[0]
    gap = ledger.coverage_gaps[0]

    assert ledger.ledger_sha256 == (
        "b4e90857fb0bc6401fa8eb9519220da14408e095d9d6979dc27e6174496f8c0e"
    )
    assert fragment.source_id == "bv_raman_muhurtha_1969"
    assert (fragment.page_number, fragment.printed_page) == (182, 178)
    assert fragment.anchor_label == "Rahukalam"
    assert fragment.admission_status == "quarantined"
    assert fragment.excerpt_permission == "none"
    assert fragment.permitted_excerpt is None
    assert comparison.baseline_rule_id == "muhurta.interval.rahu_kala"
    assert comparison.relation == "agrees_with"
    assert comparison.review_status == "anchored_unreviewed"
    assert gap.baseline_rule_id == "muhurta.interval.yamaganda"
    assert gap.blocker_code == "overlay_page_not_located"
    assert ledger.specialist_review_status == "missing"
    assert ledger.activation_allowed is False
    assert ledger.doctrine_admitted is False
    assert ledger.product_rule_use_allowed is False


def test_overlay_ledger_exports_only_hashes_locators_and_safe_paraphrase() -> None:
    rendered = LEDGER_PATH.read_text(encoding="utf-8")

    assert "private_sources" not in rendered
    assert "/Users/" not in rendered
    assert ".pdf" not in rendered
    assert "Rahukalam" in rendered
    assert "4-30" not in rendered
    assert "7-30" not in rendered


def test_overlay_ledger_rejects_coordinated_binding_or_page_substitution() -> None:
    payload = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    payload["comparisons"][0]["paraphrase"] = "Substituted comparison."
    with pytest.raises(ValidationError, match="not content-addressed"):
        MuhurtaModernOverlayLedger.model_validate(payload)

    payload = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    payload["fragments"][0]["page_number"] = 181
    with pytest.raises(ValidationError, match="reviewed Raman page"):
        MuhurtaModernOverlayLedger.model_validate(payload)
