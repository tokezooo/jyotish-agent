from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from jyotish_agent.doctrine.prashna_pack import (
    PrashnaBaselineRulePack,
    build_prashna_baseline_testimonies,
    classify_prashna_question,
    evaluate_prashna_baseline_geometry,
    load_prashna_baseline_rule_pack,
    prashna_compiled_profile_sha256,
)
from jyotish_agent.prashna_models import PrashnaFact


ROOT = Path(__file__).parents[2]
PROFILE = ROOT / "src/jyotish_agent/data/doctrine/prashna-baseline-profile.json"


def _facts() -> tuple[PrashnaFact, ...]:
    return (
        PrashnaFact(fact_id="prashna.topic.primary_lord", value="Mercury"),
        PrashnaFact(fact_id="prashna.topic.primary_lord_house", value=10),
        PrashnaFact(fact_id="prashna.graha_drishti.Mercury.houses", value="4"),
        PrashnaFact(fact_id="prashna.planets.Jupiter.house", value=11),
        PrashnaFact(fact_id="prashna.planets.Venus.house", value=12),
        PrashnaFact(fact_id="prashna.planets.Mars.house", value=9),
        PrashnaFact(fact_id="prashna.planets.Saturn.house", value=7),
    )


def test_pack_is_complete_content_addressed_and_tajika_free() -> None:
    pack = load_prashna_baseline_rule_pack()
    assert {rule.rule_id for rule in pack.rules} == {
        "primary_house_lord_connection",
        "relative_benefic_support",
        "relative_malefic_obstacle",
    }
    assert len(prashna_compiled_profile_sha256()) == 64
    rendered = pack.model_dump_json().casefold()
    assert "tajika" not in rendered
    assert "saxena" not in rendered
    assert all(
        ref.source_ref.startswith("daivajna_vallabha_2003_scan:pdf:2:sha256:")
        for ref in pack.rules
    )


def test_house_lord_geometry_and_relative_testimonies_are_fact_bound() -> None:
    route = classify_prashna_question("What blocks this work project?")
    geometry = evaluate_prashna_baseline_geometry(_facts(), route)
    assert geometry.state == "connected"
    assert geometry.connection == "associated"
    assert geometry.fact_refs
    testimonies = build_prashna_baseline_testimonies(_facts(), route, geometry)
    assert {item.polarity for item in testimonies} == {"assistance", "obstacle"}
    assert all(item.fact_refs and item.source_refs for item in testimonies)

    missing = evaluate_prashna_baseline_geometry(_facts()[:1], route)
    assert missing.state == "unavailable"
    assert missing.reason_code == "PRIMARY_LORD_FACTS_MISSING"


def test_pack_rejects_rule_substitution_or_hidden_layer() -> None:
    payload = json.loads(PROFILE.read_text(encoding="utf-8"))
    payload["rules"][0]["rule_id"] = "relative_benefic_support"
    with pytest.raises((ValidationError, ValueError), match="incomplete|blended"):
        PrashnaBaselineRulePack.model_validate(payload)

    payload = json.loads(PROFILE.read_text(encoding="utf-8"))
    payload["school"] = "tajika_nilakanthi_overlay"
    with pytest.raises(ValidationError, match="school"):
        PrashnaBaselineRulePack.model_validate(payload)
