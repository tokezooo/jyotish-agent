from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from jyotish_agent.doctrine.ingestion import PyPdfExtractor, _extract_anchors, _normalize_text
from jyotish_agent.doctrine.jaimini_pack import (
    JaiminiOverlayFailure,
    JaiminiOverlayFragmentLedger,
    JaiminiOverlayRegistry,
    JaiminiRuleInventory,
    JaiminiRuleStatus,
)
from jyotish_agent.doctrine.sources import load_source_manifest
from jyotish_agent.research_store import canonical_json


ROOT = Path(__file__).parents[2]
LEDGER_PATH = (
    ROOT / "src/jyotish_agent/data/doctrine/jaimini-overlay-fragments.json"
)
AUDIT_PATH = ROOT / "docs/evidence/doctrine/jaimini-overlay-fragments.json"
MANIFEST_PATH = ROOT / "src/jyotish_agent/data/doctrine/jaimini-sources.json"
INVENTORY_PATH = ROOT / "src/jyotish_agent/data/doctrine/jaimini-rules.json"
OVERLAYS_PATH = ROOT / "src/jyotish_agent/data/doctrine/jaimini-overlays.json"
CORE_PATH = ROOT / "src/jyotish_agent/data/jaimini/jaimini_core_v1.json"
UPADESA_SOURCE_ID = "jaimini_sanjay_rath_upadesa_sutras_1997"


def _ledger() -> JaiminiOverlayFragmentLedger:
    ledger = JaiminiOverlayFragmentLedger.model_validate_json(
        LEDGER_PATH.read_text(encoding="utf-8")
    )
    ledger.validate_context(
        manifest=load_source_manifest(MANIFEST_PATH),
        baseline_inventory=JaiminiRuleInventory.model_validate_json(
            INVENTORY_PATH.read_text(encoding="utf-8")
        ),
        overlay_registry=JaiminiOverlayRegistry.model_validate_json(
            OVERLAYS_PATH.read_text(encoding="utf-8")
        ),
    )
    return ledger


def test_overlay_fragment_ledger_is_hash_bound_and_context_valid() -> None:
    ledger = _ledger()

    assert ledger.overlay_id == "sanjay_rath"
    assert ledger.school == "sanjay_rath"
    assert ledger.activation_status == "unavailable"
    assert ledger.doctrine_admitted is False
    assert ledger.product_rule_use_allowed is False
    assert len(ledger.fragments) >= 8
    assert len(ledger.bindings) >= 10
    assert {fragment.source_id for fragment in ledger.fragments} == {
        UPADESA_SOURCE_ID
    }
    assert all(fragment.admission_status == "quarantined" for fragment in ledger.fragments)
    assert all(fragment.excerpt_permission == "none" for fragment in ledger.fragments)
    assert all(fragment.permitted_excerpt is None for fragment in ledger.fragments)


def test_overlay_bindings_cover_bounded_families_and_make_conflicts_explicit() -> None:
    ledger = _ledger()
    by_rule: dict[str, list[object]] = {}
    for binding in ledger.bindings:
        by_rule.setdefault(binding.rule_id, []).append(binding)

    assert {
        "rasi_drishti.modal_sign_aspects",
        "argala.houses",
        "argala.count_obstruction",
        "karakas.scheme",
        "karakas.rahu_reversal",
        "arudha.exception",
        "svamsa.d9_lagna",
        "karakamsa.d9_atmakaraka",
        "co_lords.resolution",
        "chara_dasha.progression",
        "chara_dasha.duration",
    } <= set(by_rule)
    assert all(
        binding.status == JaiminiRuleStatus.QUARANTINED_CONFLICT
        and binding.discrepancy
        for rule_id in (
            "co_lords.resolution",
            "chara_dasha.progression",
            "chara_dasha.duration",
        )
        for binding in by_rule[rule_id]
    )
    assert all(
        binding.status != JaiminiRuleStatus.ADMITTED
        for binding in ledger.bindings
    )


def test_quarantined_ledger_cannot_activate_or_compile_overlay() -> None:
    ledger = _ledger()

    assert ledger.activation_allowed is False
    with pytest.raises(JaiminiOverlayFailure) as raised:
        ledger.require_activation_ready()
    assert raised.value.code == "OVERLAY_FRAGMENT_LEDGER_QUARANTINED"


def test_tracked_projection_contains_no_source_text_or_private_locator() -> None:
    ledger_payload = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    audit_payload = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    rendered = json.dumps(
        {"ledger": ledger_payload, "audit": audit_payload}, sort_keys=True
    ).casefold()

    assert "private_sources" not in rendered
    assert "/users/" not in rendered
    assert ".pdf" not in rendered
    assert "local_file" not in rendered
    assert "permitted_excerpt" in ledger_payload["fragments"][0]
    assert all(
        fragment["permitted_excerpt"] is None for fragment in ledger_payload["fragments"]
    )
    assert "text" not in ledger_payload


def test_unresolved_sources_are_explicit_and_do_not_enter_fragment_evidence() -> None:
    ledger = _ledger()
    unresolved = {item.source_id: item for item in ledger.unresolved_sources}

    assert set(unresolved) == {
        "jaimini_sanjay_rath_narayana_dasa_2004",
        "jaimini_kn_rao_chara_dasha_vani_scan_2010",
    }
    assert unresolved[
        "jaimini_sanjay_rath_narayana_dasa_2004"
    ].blocker_code == "crop_aware_extraction_required"
    assert unresolved[
        "jaimini_kn_rao_chara_dasha_vani_scan_2010"
    ].blocker_code == "ocr_review_pending"


def test_baseline_inventory_and_frozen_core_are_unchanged_from_merge_base() -> None:
    # Exact identities captured before the overlay-fragment slice began.
    assert hashlib.sha256(INVENTORY_PATH.read_bytes()).hexdigest() == (
        "54d90c69b18878d3b7276007a2ff44500ae73eb6f811b4fe6c9ce08ab2df05f1"
    )
    assert hashlib.sha256(CORE_PATH.read_bytes()).hexdigest() == (
        "8a97c43e8438351ae73a59fed731cf5e48ef3c25c347ddf3570dea5818696b58"
    )


def test_private_upadesa_pages_match_tracked_normalized_page_commitments() -> None:
    manifest = load_source_manifest(MANIFEST_PATH)
    source = next(
        item for item in manifest.sources if item.source_id == UPADESA_SOURCE_ID
    )
    private_path = ROOT / "private_sources" / source.local_file
    if not private_path.is_file():
        pytest.skip("private Upadesa source is unavailable in this checkout")

    extracted = PyPdfExtractor().extract(private_path)
    ledger = _ledger()
    for fragment in ledger.fragments:
        text = _normalize_text(extracted[fragment.page_number - 1].text)
        anchors = _extract_anchors(text)
        page_payload = {
            "page_number": fragment.page_number,
            "printed_page": fragment.printed_page,
            "language": fragment.language,
            "text": text,
            "source_method": "embedded_text",
            "confidence": 1.0,
            "admission_status": "admitted",
            "anchors": [anchor.model_dump(mode="json") for anchor in anchors],
        }
        assert hashlib.sha256(text.encode("utf-8")).hexdigest() == (
            fragment.full_text_sha256
        )
        assert hashlib.sha256(canonical_json(page_payload).encode("utf-8")).hexdigest() == (
            fragment.normalized_content_sha256
        )


def test_privacy_safe_audit_is_bound_to_ledger_and_preserves_release_blockers() -> None:
    ledger = _ledger()
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))

    assert audit["ledger_sha256"] == ledger.ledger_sha256
    assert audit["fragment_count"] == len(ledger.fragments)
    assert audit["binding_count"] == len(ledger.bindings)
    assert audit["admitted_binding_count"] == 0
    assert audit["conflict_binding_count"] >= 3
    assert audit["release_promoted"] is False
    assert audit["overlay_activated"] is False
    assert {
        "nilakantha_subodhini_translation",
        "specialist_review",
        "hand_worked_cases",
        "deep_conversational_e2e",
    } <= set(audit["preserved_release_blockers"])
