from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jyotish_agent import rule_profiles
from jyotish_agent.corpus import load_builtin_manifest


ROOT = Path(__file__).parents[2]
DATA = ROOT / "src/jyotish_agent/data"
ADMISSION = DATA / "doctrine/jaimini-special-lagnas-admission-v1.json"
INVENTORY = DATA / "doctrine/jaimini-rules.json"
BASELINE_FRAGMENTS = DATA / "doctrine/jaimini-baseline-fragments.json"
PROFILE = DATA / "jaimini/jaimini_core_v1.json"
SOURCE_MAP = DATA / "jaimini/jaimini_core_v1_sources.json"
ADJUDICATION = DATA / "jaimini/adjudication_fixtures_v1.json"
GEOMETRY = ROOT / "eval/jaimini/geometry-held-out-v1.json"
GEOMETRY_CHECKSUMS = ROOT / "eval/jaimini/geometry-held-out-v1-checksums.json"
HAND_WORKED = ROOT / "eval/jaimini/hand-worked-v1.json"
HAND_WORKED_CHECKSUMS = ROOT / "eval/jaimini/hand-worked-v1-checksums.json"

APPROVED_RULES = {
    "special_lagnas.regular_anchor_policy",
    "special_lagnas.regular_rates",
    "special_lagnas.regular_savayava_separation",
    "special_lagnas.sun_epoch",
    "special_lagnas.sunrise_definition",
}


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_admission_is_narrow_page_bound_and_text_free() -> None:
    admission = _json(ADMISSION)
    manifest = load_builtin_manifest()
    source_map = _json(SOURCE_MAP)

    assert admission["review"] == {
        "status": "approved",
        "reviewer": "Codex evidence review",
        "reviewer_role": "source_governance_reviewer",
        "reviewed_at": "2026-08-02",
        "note": (
            "Approval is limited to five regular BL/HL/GL calculation rules. "
            "It does not approve interpretation, other Jaimini rules, or a full "
            "renderer."
        ),
    }
    assert set(admission["approved_rule_ids"]) == APPROVED_RULES
    assert admission["interpretation_admitted"] is False
    assert admission["renderer_admitted"] is False

    page_commitments = {
        fragment["fragment_id"]: (
            fragment["pdf_page"],
            fragment["printed_page"],
            fragment["page_text_sha256"],
        )
        for fragment in admission["fragments"]
    }
    assert page_commitments == {
        "sf_pvr2010_special_lagna_anchor": (
            57,
            45,
            "46e0ca586c0c8f4974137c01d57ebc12b791b63b839bc806754cf09357156911",
        ),
        "sf_pvr2010_pre_sunrise_case": (
            59,
            47,
            "5daaf95836c983cafc7dd0d0eb1c3186c6bc529c1ed439094a1cf977056ee21c",
        ),
        "sf_pvr2010_upper_limb": (
            60,
            48,
            "4050c636e04d7fd849e930293cf9a1022c52c75f4afd651a0760e7744081f762",
        ),
        "sf_sr2009_regular_rates": (
            452,
            452,
            "3254523748b57687e7a383cb0e31dcfaaec2e12246280e86dbbe10cc2fa6dc27",
        ),
        "sf_sr2009_regular_savayava_split": (
            422,
            422,
            "05a6f2c747a2027e7ccbd056651fdbf3c9db319c74e532e60d93c7c6e4879e17",
        ),
    }
    assert all(
        fragment["excerpt_permission"] == "none"
        and fragment["permitted_excerpt"] is None
        and fragment["admission_status"] == "admitted"
        and len(fragment["page_text_sha256"]) == 64
        for fragment in admission["fragments"]
    )
    assert {
        rule_id
        for fragment in admission["fragments"]
        for rule_id in fragment["claim_scope"]
    } == APPROVED_RULES

    governed_sources = {
        source["source_version_id"]: source
        for source in manifest["sources"]
        if source["source_version_id"]
        in {
            "sv_pvr_vedic_astrology_integrated_2010",
            "sv_sanjay_rath_course_jaimini_2009",
        }
    }
    assert set(governed_sources) == {
        "sv_pvr_vedic_astrology_integrated_2010",
        "sv_sanjay_rath_course_jaimini_2009",
    }
    governed_fragments = {
        fragment["fragment_id"]: fragment
        for source in governed_sources.values()
        for fragment in source["fragments"]
    }
    mapped = {
        rule["rule_id"]: rule
        for rule in source_map["rules"]
        if rule["source_status"] == "approved"
    }
    assert set(mapped) == APPROVED_RULES
    for rule in mapped.values():
        fragment = governed_fragments[rule["fragment_id"]]
        assert fragment["checksum"] == rule["fragment_sha256"]
        assert fragment["text"].startswith("Governed abstract:")
        assert "p." in fragment["locator"]
    assert all(
        source["review"]["status"] == "approved"
        and source["review"]["reviewer"] == "Codex evidence review"
        and "no copyrighted page text is reproduced" in source["rights_note"]
        and source["provenance_url"].startswith("https://")
        for source in governed_sources.values()
    )


def test_partial_admission_does_not_open_global_interpretation_gate() -> None:
    source_map = _json(SOURCE_MAP)
    assert source_map["review"]["status"] == "pending"
    assert source_map["interpretation_status"] == "unavailable"
    assert "special_lagnas.selected_rates" not in {
        rule["rule_id"] for rule in source_map["rules"]
    }
    assert all(
        rule["source_status"] == "pending"
        and rule["fragment_id"] is None
        and rule["fragment_sha256"] is None
        for rule in source_map["rules"]
        if rule["rule_id"] not in APPROVED_RULES
    )
    evidence = rule_profiles.jaimini_source_admission_evidence()
    assert evidence["verified"] is False
    assert evidence["rule_sources"] == {}


def test_engineering_policies_are_not_admitted_as_doctrine() -> None:
    admission = _json(ADMISSION)
    policies = admission["calculation_policies"]
    assert {policy["policy_id"] for policy in policies} == {
        "special_lagnas.elapsed_utc_instants",
        "special_lagnas.exact_sunrise_boundary",
        "special_lagnas.polar_no_adjacent_sunrise",
    }
    assert all(
        policy["classification"] == "engineering_inference"
        and policy["status"] == "documented_not_doctrine"
        and policy["policy_id"] not in APPROVED_RULES
        for policy in policies
    )


def test_nilakantha_conflict_was_split_without_baseline_admission() -> None:
    inventory = _json(INVENTORY)
    ledger = _json(BASELINE_FRAGMENTS)
    candidates = {
        candidate["rule_id"]: candidate
        for candidate in inventory["candidates"]
        if candidate["rule_id"].startswith("special_lagnas.")
    }
    assert set(candidates) == APPROVED_RULES
    assert all(
        candidate["status"] == "quarantined_conflict"
        and candidate["anchor"]["pdf_page"] == 52
        and candidate["anchor"]["printed_page"] == 35
        for candidate in candidates.values()
    )
    bindings = {
        binding["rule_id"]: binding
        for binding in ledger["bindings"]
        if binding["rule_id"].startswith("special_lagnas.")
    }
    assert set(bindings) == APPROVED_RULES
    assert all(
        binding["status"] == "quarantined_conflict"
        for binding in bindings.values()
    )


def test_profile_bound_fixture_checksums_were_mechanically_resealed() -> None:
    profile_sha256 = _sha256(PROFILE)
    source_map_sha256 = _sha256(SOURCE_MAP)
    assert profile_sha256 == (
        "ea5aea06b15b98df63ca32c290f4ebc7ae1d2d494171aa4730bb25c467dda5bb"
    )
    assert _json(SOURCE_MAP)["rule_profile_sha256"] == profile_sha256

    geometry = _json(GEOMETRY)
    assert geometry["rule_profile_sha256"] == profile_sha256
    assert all(
        case["rule_profile_sha256"] == profile_sha256
        for case in geometry["cases"]
    )
    assert _json(GEOMETRY_CHECKSUMS)["files"][GEOMETRY.name] == _sha256(GEOMETRY)

    hand_worked = _json(HAND_WORKED)
    assert hand_worked["rule_profile_sha256"] == profile_sha256
    assert hand_worked["source_map_sha256"] == source_map_sha256
    assert _json(HAND_WORKED_CHECKSUMS)["files"][HAND_WORKED.name] == _sha256(
        HAND_WORKED
    )

    adjudication = _json(ADJUDICATION)
    assert all(
        fixture["rule_profile_sha256"] == profile_sha256
        and fixture["source_map_sha256"] == source_map_sha256
        for fixture in adjudication
    )
