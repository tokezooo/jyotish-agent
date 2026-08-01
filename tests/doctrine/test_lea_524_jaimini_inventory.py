from __future__ import annotations

import json
from pathlib import Path

from jyotish_agent.doctrine.jaimini_pack import (
    JaiminiRuleInventory,
    JaiminiRuleStatus,
)


ROOT = Path(__file__).parents[2]
INVENTORY_PATH = ROOT / "src/jyotish_agent/data/doctrine/jaimini-rules.json"
SOURCE_MAP_PATH = ROOT / "src/jyotish_agent/data/jaimini/jaimini_core_v1_sources.json"
DISCREPANCIES_PATH = ROOT / "docs/evidence/doctrine/jaimini-rule-discrepancies.json"


def _inventory() -> JaiminiRuleInventory:
    return JaiminiRuleInventory.model_validate_json(
        INVENTORY_PATH.read_text(encoding="utf-8")
    )


def test_inventory_covers_every_existing_jaimini_fact_rule_family() -> None:
    inventory = _inventory()
    existing = json.loads(SOURCE_MAP_PATH.read_text(encoding="utf-8"))
    expected_rule_ids = {rule["rule_id"] for rule in existing["rules"]}

    assert {
        candidate.rule_id for candidate in inventory.candidates
    } == expected_rule_ids
    assert all(candidate.fact_families for candidate in inventory.candidates)
    assert all(candidate.source_id for candidate in inventory.candidates)


def test_baseline_inventory_has_no_hidden_overlay_or_unsupported_admission() -> None:
    inventory = _inventory()

    assert inventory.school == "nilakantha_baseline"
    assert all(
        candidate.school == inventory.school for candidate in inventory.candidates
    )
    assert all(
        candidate.status != JaiminiRuleStatus.ADMITTED
        for candidate in inventory.candidates
    )
    rendered = INVENTORY_PATH.read_text(encoding="utf-8").casefold()
    assert "sanjay_rath" not in rendered
    assert "kn_rao" not in rendered


def test_anchored_candidate_has_exact_page_sutra_and_content_commitment() -> None:
    inventory = _inventory()
    candidate = next(
        item
        for item in inventory.candidates
        if item.rule_id == "rasi_drishti.modal_sign_aspects"
    )

    assert candidate.status == JaiminiRuleStatus.ANCHORED_UNREVIEWED
    assert candidate.anchor is not None
    assert candidate.anchor.pdf_page == 20
    assert candidate.anchor.printed_page == 3
    assert candidate.anchor.sutra == "1.1.2-1.1.4"
    assert len(candidate.anchor.fragment_sha256) == 64
    assert candidate.ambiguity is not None


def test_existing_nilakantha_mediated_volume_anchors_bounded_rule_families() -> None:
    inventory = _inventory()
    anchored = {item.rule_id: item for item in inventory.candidates if item.anchor}

    assert set(anchored) == {
        "argala.count_obstruction",
        "argala.houses",
        "arudha.exception",
        "chara_dasha.antardasha",
        "chara_dasha.duration",
        "co_lords.resolution",
        "karakamsa.d9_atmakaraka",
        "karakas.rahu_reversal",
        "karakas.scheme",
        "karakas.tie_policy",
        "rasi_drishti.modal_sign_aspects",
        "special_lagnas.selected_rates",
    }
    assert {
        rule_id
        for rule_id, candidate in anchored.items()
        if candidate.status == JaiminiRuleStatus.QUARANTINED_CONFLICT
    } == {
        "co_lords.resolution",
        "karakas.tie_policy",
        "special_lagnas.selected_rates",
    }
    assert all(
        candidate.source_id == "jaimini_sutras_b_suryanarain_rao_1949"
        for candidate in anchored.values()
    )


def test_unanchored_candidates_are_quarantined_with_explicit_discrepancies() -> None:
    inventory = _inventory()
    unanchored = [item for item in inventory.candidates if item.anchor is None]

    assert unanchored
    assert all(
        item.status == JaiminiRuleStatus.QUARANTINED_MISSING_ANCHOR and item.discrepancy
        for item in unanchored
    )
    discrepancy_audit = json.loads(DISCREPANCIES_PATH.read_text(encoding="utf-8"))
    assert discrepancy_audit["inventory_sha256"] == inventory.inventory_sha256
    assert discrepancy_audit["admitted_rule_count"] == 0
    conflicts = [
        item
        for item in inventory.candidates
        if item.status == JaiminiRuleStatus.QUARANTINED_CONFLICT
    ]
    assert discrepancy_audit["quarantined_rule_count"] == len(unanchored) + len(
        conflicts
    )
    assert {item["rule_id"] for item in discrepancy_audit["discrepancies"]} == {
        item.rule_id for item in unanchored
    } | {item.rule_id for item in conflicts}


def test_inventory_identity_is_deterministic_and_order_independent() -> None:
    inventory = _inventory()
    payload = inventory.model_dump(mode="json")
    payload["candidates"] = list(reversed(payload["candidates"]))
    reordered = JaiminiRuleInventory.model_validate(payload)

    assert inventory.inventory_sha256 == reordered.inventory_sha256
