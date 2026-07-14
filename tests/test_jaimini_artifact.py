from __future__ import annotations

import copy

from jyotish_agent import signing
from jyotish_agent import interpretations
from jyotish_agent import rule_profiles


def _artifact_payload() -> dict:
    return {
        "mode": "jaimini",
        "normalized_anchor_sha256": "1" * 64,
        "profile_sha256": "2" * 64,
        "config_sha256": "3" * 64,
        "rule_profile_sha256": "4" * 64,
        "source_map_sha256": "5" * 64,
        "facts": [{"fact_id": "jaimini.karakas.AK", "value": "Saturn"}],
        "provenance": {"engine": "fixture", "engine_version": "1"},
    }


def test_signed_domain_artifact_binds_every_trust_boundary_field():
    assert hasattr(signing, "cache_domain_artifact")
    artifact = signing.cache_domain_artifact(_artifact_payload())
    assert artifact["artifact_id"].startswith("jya_")
    assert len(artifact["artifact_sha256"]) == 64
    assert signing.verify_domain_artifact(artifact)
    assert signing.get_cached_domain_artifact(artifact["artifact_token"]) == artifact

    for field in (
        "normalized_anchor_sha256",
        "profile_sha256",
        "config_sha256",
        "rule_profile_sha256",
        "source_map_sha256",
        "facts",
        "provenance",
    ):
        changed = copy.deepcopy(artifact)
        changed[field] = [] if field == "facts" else {"changed": True} if field == "provenance" else "0" * 64
        assert signing.verify_domain_artifact(changed) is False


def test_domain_artifact_is_deterministic_and_cache_is_defensive():
    assert hasattr(signing, "cache_domain_artifact")
    first = signing.cache_domain_artifact(_artifact_payload())
    second = signing.cache_domain_artifact(copy.deepcopy(_artifact_payload()))
    assert first == second
    first["facts"][0]["value"] = "tampered outside cache"
    assert signing.get_cached_domain_artifact(second["artifact_token"])["facts"][0]["value"] == "Saturn"


def test_jaimini_atomizer_and_checker_use_only_signed_citable_facts():
    assert hasattr(interpretations, "iter_jaimini_fact_atoms")
    assert hasattr(interpretations, "validate_jaimini_answer")
    payload = _artifact_payload()
    payload["provenance"]["source_review_status"] = "pending"
    artifact = signing.cache_domain_artifact(payload)

    assert interpretations.iter_jaimini_fact_atoms(payload["facts"]) == {
        "jaimini.karakas.AK": "Saturn"
    }
    assert interpretations.validate_jaimini_answer(
        [{"path": "jaimini.karakas.AK", "value": "Saturn"}],
        artifact["artifact_token"],
    ) == []
    assert interpretations.validate_jaimini_answer(
        [{"path": "jaimini.karakas.AK", "value": "Sun"}],
        artifact["artifact_token"],
    ) == ["FACT_VALUE_MISMATCH:jaimini.karakas.AK"]
    assert interpretations.validate_jaimini_answer(
        [{"path": "jaimini.fiction", "value": "yes"}],
        artifact["artifact_token"],
    ) == ["FACT_NOT_IN_ARTIFACT:jaimini.fiction"]


def test_jaimini_interpretation_checker_fails_closed_without_source_admission():
    payload = _artifact_payload()
    payload["provenance"]["source_review_status"] = "pending"
    artifact = signing.cache_domain_artifact(payload)
    assert interpretations.validate_jaimini_answer(
        [{"path": "jaimini.karakas.AK", "value": "Saturn"}],
        artifact["artifact_token"],
        interpretation_requested=True,
    ) == ["INTERPRETATION_SOURCE_UNAVAILABLE"]
    assert interpretations.validate_jaimini_answer([], "invalid") == [
        "ARTIFACT_NOT_FOUND"
    ]


def test_source_admission_requires_governed_fragment_checksum_verification():
    assert hasattr(rule_profiles, "jaimini_source_admission_verified")
    # The current Jaimini source map is deliberately pending and the governed
    # corpus contains no admitted Jaimini rule pack.
    assert rule_profiles.jaimini_source_admission_verified() is False
