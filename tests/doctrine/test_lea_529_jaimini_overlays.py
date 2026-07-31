from __future__ import annotations

import json
from pathlib import Path

import pytest

from jaimini_helpers import build_jaimini_graph
from jyotish_agent.doctrine.jaimini_pack import (
    JaiminiOverlayFailure,
    JaiminiOverlayRegistry,
    JaiminiTopic,
    analyze_jaimini_topic,
    compare_jaimini_overlays,
    load_jaimini_overlay_activation_contract,
)


ROOT = Path(__file__).parents[2]
REGISTRY = ROOT / "src/jyotish_agent/data/doctrine/jaimini-overlays.json"
LEDGER = ROOT / "src/jyotish_agent/data/doctrine/jaimini-overlay-fragments.json"
MANIFEST = ROOT / "src/jyotish_agent/data/doctrine/jaimini-sources.json"
INVENTORY = ROOT / "src/jyotish_agent/data/doctrine/jaimini-rules.json"


def _activation_contract():
    return load_jaimini_overlay_activation_contract(
        ledger_path=LEDGER,
        manifest_path=MANIFEST,
        baseline_inventory_path=INVENTORY,
        overlay_registry_path=REGISTRY,
    )


def _analysis(school: str, rule_id: str):
    graph = build_jaimini_graph(
        facts={"jaimini.karakas.7.AK": "Mercury"},
        rules=[
            {
                "rule_id": rule_id,
                "topic": "self",
                "premises": [
                    {
                        "path": "jaimini.karakas.7.AK",
                        "operator": "exists",
                        "value": None,
                    }
                ],
            }
        ],
        school=school,
        artifact_id=f"dom_{school}",
    )
    return analyze_jaimini_topic(graph, JaiminiTopic.SELF)


def test_overlay_registry_names_acquired_sources_and_keeps_unreviewed_profiles_disabled() -> (
    None
):
    registry = JaiminiOverlayRegistry.model_validate_json(
        REGISTRY.read_text(encoding="utf-8")
    )

    assert {item.overlay_id for item in registry.overlays} == {
        "sanjay_rath",
        "kn_rao_practical",
    }
    assert all(item.activation_status == "unavailable" for item in registry.overlays)
    by_id = {item.overlay_id: item for item in registry.overlays}
    assert by_id["sanjay_rath"].source_ids == (
        "jaimini_sanjay_rath_upadesa_sutras_1997",
        "jaimini_sanjay_rath_narayana_dasa_2004",
    )
    assert by_id["kn_rao_practical"].source_ids == (
        "jaimini_kn_rao_chara_dasha_vani_scan_2010",
    )


def test_overlay_requires_explicit_activation_and_preserves_baseline_identity() -> None:
    baseline = _analysis("nilakantha_baseline", "self.baseline")
    overlay = _analysis("sanjay_rath", "self.rath")
    baseline_before = baseline.model_dump_json()

    inactive = compare_jaimini_overlays(
        baseline, overlay, overlay_id="sanjay_rath", activate=False
    )
    assert inactive.overlay_active is False
    assert inactive.overlay_signals == ()
    assert baseline.model_dump_json() == baseline_before

    with pytest.raises(JaiminiOverlayFailure) as missing_context:
        compare_jaimini_overlays(
            baseline, overlay, overlay_id="sanjay_rath", activate=True
        )
    assert missing_context.value.code == "OVERLAY_ACTIVATION_CONTEXT_REQUIRED"

    with pytest.raises(JaiminiOverlayFailure) as unavailable:
        compare_jaimini_overlays(
            baseline,
            overlay,
            overlay_id="sanjay_rath",
            activate=True,
            activation_contract=_activation_contract(),
        )
    assert unavailable.value.code == "OVERLAY_UNAVAILABLE"
    assert baseline.model_dump_json() == baseline_before


def test_unavailable_kn_rao_overlay_cannot_activate_even_with_valid_context() -> None:
    baseline = _analysis("nilakantha_baseline", "self.baseline")
    overlay = _analysis("kn_rao_practical", "self.kn_rao")
    contract = _activation_contract()

    for _ in range(2):
        with pytest.raises(JaiminiOverlayFailure) as unavailable:
            compare_jaimini_overlays(
                baseline,
                overlay,
                overlay_id="kn_rao_practical",
                activate=True,
                activation_contract=contract,
            )
        assert unavailable.value.code == "OVERLAY_UNAVAILABLE"


def test_duck_typed_activation_context_cannot_bypass_validated_loader() -> None:
    baseline = _analysis("nilakantha_baseline", "self.baseline")
    overlay = _analysis("sanjay_rath", "self.rath")

    class FakeContract:
        def require_activation_ready(self, _overlay_id: str) -> None:
            return None

    with pytest.raises(JaiminiOverlayFailure) as missing_context:
        compare_jaimini_overlays(
            baseline,
            overlay,
            overlay_id="sanjay_rath",
            activate=True,
            activation_contract=FakeContract(),  # type: ignore[arg-type]
        )
    assert missing_context.value.code == "OVERLAY_ACTIVATION_CONTEXT_REQUIRED"


def test_hidden_school_blending_is_rejected() -> None:
    baseline = _analysis("nilakantha_baseline", "self.baseline")
    disguised = _analysis("nilakantha_baseline", "self.hidden_overlay")

    with pytest.raises(JaiminiOverlayFailure) as hidden:
        compare_jaimini_overlays(
            baseline, disguised, overlay_id="sanjay_rath", activate=True
        )
    assert hidden.value.code == "OVERLAY_SCHOOL_NOT_EXPLICIT"


def test_registry_file_contains_no_rules_or_copyrighted_text() -> None:
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert all("rules" not in item for item in payload["overlays"])
    assert all("text" not in item for item in payload["overlays"])
