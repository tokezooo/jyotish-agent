from __future__ import annotations

import json
from pathlib import Path

import pytest

from jyotish_agent.doctrine.jaimini_pack import (
    JaiminiBaselineFragmentLedger,
    JaiminiRuleInventory,
    JaiminiRuleStatus,
)
from jyotish_agent.doctrine.sources import load_source_manifest


ROOT = Path(__file__).parents[2]
AUDIT_PATH = ROOT / "docs/evidence/doctrine/jaimini-baseline-reassessment.json"
LEDGER_PATH = (
    ROOT / "src/jyotish_agent/data/doctrine/jaimini-baseline-fragments.json"
)
INVENTORY_PATH = ROOT / "src/jyotish_agent/data/doctrine/jaimini-rules.json"
MANIFEST_PATH = ROOT / "src/jyotish_agent/data/doctrine/jaimini-sources.json"
SOURCE_ID = "jaimini_sutras_b_suryanarain_rao_1949"


def _ledger() -> JaiminiBaselineFragmentLedger:
    return JaiminiBaselineFragmentLedger.model_validate_json(
        LEDGER_PATH.read_text(encoding="utf-8")
    )


def _inventory() -> JaiminiRuleInventory:
    return JaiminiRuleInventory.model_validate_json(
        INVENTORY_PATH.read_text(encoding="utf-8")
    )


def test_reassessment_closes_acquisition_without_claiming_a_standalone_edition() -> None:
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))

    assert audit["source_id"] == SOURCE_ID
    assert audit["source_file_sha256"] == (
        "06953f710d7a52e548fd7b7badeeef0c163debd02b8b08178c3833905aaa76ce"
    )
    assert audit["edition"] == "Third edition, Raman Publications, 1949"
    assert audit["baseline_disposition"] == "nilakantha_mediated_translation"
    assert audit["standalone_subodhini_edition_acquired"] is False
    assert audit["corpus_acquisition_ready"] is True
    assert audit["release_promoted"] is False
    assert {item["pdf_page"] for item in audit["identity_page_commitments"]} == {
        1,
        2,
        6,
        7,
        56,
    }
    assert all(
        len(item["normalized_page_sha256"]) == 64
        and item["visual_reviewed"] is True
        for item in audit["identity_page_commitments"]
    )
    assert len(audit["limitations"]) >= 3
    rendered = json.dumps(audit, sort_keys=True).casefold()
    assert "private_sources" not in rendered
    assert ".pdf" not in rendered
    assert "/users/" not in rendered


def test_baseline_fragment_ledger_is_hash_bound_text_free_and_context_valid() -> None:
    ledger = _ledger()
    inventory = _inventory()
    manifest = load_source_manifest(MANIFEST_PATH)
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))

    ledger.validate_context(manifest=manifest, baseline_inventory=inventory)
    assert audit["baseline_fragment_ledger_sha256"] == ledger.ledger_sha256
    assert audit["baseline_inventory_sha256"] == inventory.inventory_sha256
    assert audit["source_manifest_sha256"] == manifest.manifest_sha256
    assert ledger.ledger_id == "jaimini_nilakantha_mediated_baseline_fragments_v1"
    assert ledger.school == "nilakantha_baseline"
    assert ledger.source_id == SOURCE_ID
    assert ledger.doctrine_admitted is False
    assert ledger.product_rule_use_allowed is False
    assert len(ledger.fragments) == 12
    assert len(ledger.bindings) == 12
    assert all(fragment.admission_status == "quarantined" for fragment in ledger.fragments)
    assert all(fragment.excerpt_permission == "none" for fragment in ledger.fragments)
    assert all(fragment.permitted_excerpt is None for fragment in ledger.fragments)
    assert all(
        binding.status != JaiminiRuleStatus.ADMITTED
        for binding in ledger.bindings
    )


def test_baseline_fragment_identity_and_inventory_binding_fail_closed() -> None:
    payload = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    payload["fragments"][0]["normalized_content_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="fragment draft identity"):
        JaiminiBaselineFragmentLedger.model_validate(payload)

    ledger = _ledger()
    manifest = load_source_manifest(MANIFEST_PATH)
    inventory_payload = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    candidate = next(
        item for item in inventory_payload["candidates"] if item["anchor"] is not None
    )
    candidate["anchor"]["fragment_sha256"] = "0" * 64
    substituted = JaiminiRuleInventory.model_validate(inventory_payload)
    ledger = ledger.model_copy(
        update={"baseline_inventory_sha256": substituted.inventory_sha256}
    )
    with pytest.raises(ValueError, match="fragment commitment"):
        ledger.validate_context(
            manifest=manifest,
            baseline_inventory=substituted,
        )
