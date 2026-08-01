from __future__ import annotations

import json
from pathlib import Path

import pytest

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
        "chara_dasha.gender_semantics",
        "chara_dasha.progression",
        "co_lords.resolution",
        "karakamsa.d9_atmakaraka",
        "karakas.rahu_reversal",
        "karakas.scheme",
        "karakas.tie_policy",
        "rasi_drishti.modal_sign_aspects",
        "special_lagnas.selected_rates",
        "svamsa.d9_lagna",
        "time.boundaries",
    }
    assert {
        rule_id
        for rule_id, candidate in anchored.items()
        if candidate.status == JaiminiRuleStatus.QUARANTINED_CONFLICT
    } == {
        "chara_dasha.gender_semantics",
        "chara_dasha.progression",
        "co_lords.resolution",
        "karakas.tie_policy",
        "special_lagnas.selected_rates",
        "svamsa.d9_lagna",
        "time.boundaries",
    }
    assert all(
        candidate.source_id == "jaimini_sutras_b_suryanarain_rao_1949"
        for candidate in anchored.values()
    )


def test_every_candidate_is_anchored_and_conflicts_are_explicit() -> None:
    inventory = _inventory()
    unanchored = [item for item in inventory.candidates if item.anchor is None]

    assert unanchored == []
    assert all(item.anchor is not None for item in inventory.candidates)
    assert all(
        item.status != JaiminiRuleStatus.QUARANTINED_MISSING_ANCHOR
        for item in inventory.candidates
    )
    discrepancy_audit = json.loads(DISCREPANCIES_PATH.read_text(encoding="utf-8"))
    assert discrepancy_audit["inventory_sha256"] == inventory.inventory_sha256
    assert discrepancy_audit["admitted_rule_count"] == 0
    conflicts = [
        item
        for item in inventory.candidates
        if item.status == JaiminiRuleStatus.QUARANTINED_CONFLICT
    ]
    assert discrepancy_audit["anchored_rule_count"] == len(inventory.candidates)
    assert discrepancy_audit["unanchored_rule_count"] == 0
    assert discrepancy_audit["quarantined_rule_count"] == len(conflicts)
    assert {item["rule_id"] for item in discrepancy_audit["discrepancies"]} == {
        item.rule_id for item in conflicts
    }
    assert all(item["visual_reviewed"] for item in discrepancy_audit["manual_spot_checks"])


def test_baseline_inventory_rejects_a_candidate_without_an_anchor() -> None:
    payload = _inventory().model_dump(mode="json")
    payload["candidates"][0]["anchor"] = None
    payload["candidates"][0]["status"] = "quarantined_missing_anchor"
    payload["candidates"][0]["discrepancy"] = "Anchor intentionally removed."

    with pytest.raises(ValueError, match="require exact source anchors"):
        JaiminiRuleInventory.model_validate(payload)


def test_inventory_identity_is_deterministic_and_order_independent() -> None:
    inventory = _inventory()
    payload = inventory.model_dump(mode="json")
    payload["candidates"] = list(reversed(payload["candidates"]))
    reordered = JaiminiRuleInventory.model_validate(payload)

    assert inventory.inventory_sha256 == reordered.inventory_sha256
