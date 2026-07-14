from __future__ import annotations

import copy
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

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


def test_domain_artifact_cache_mutations_and_recency_reads_hold_one_lock(monkeypatch):
    lock = threading.RLock()

    class GuardedCache(OrderedDict):
        def _guard(self):
            assert lock._is_owned(), "domain artifact cache accessed without its lock"

        def __setitem__(self, key, value):
            self._guard()
            return super().__setitem__(key, value)

        def get(self, key, default=None):
            self._guard()
            return super().get(key, default)

        def move_to_end(self, key, last=True):
            self._guard()
            return super().move_to_end(key, last)

        def __len__(self):
            self._guard()
            return super().__len__()

        def popitem(self, last=True):
            self._guard()
            return super().popitem(last)

    monkeypatch.setattr(signing, "_DOMAIN_ARTIFACT_CACHE_LOCK", lock, raising=False)
    monkeypatch.setattr(signing, "_DOMAIN_ARTIFACT_CACHE", GuardedCache())
    artifact = signing.cache_domain_artifact(_artifact_payload())
    assert signing.get_cached_domain_artifact(artifact["artifact_token"]) == artifact


def test_domain_artifact_cache_concurrent_get_put_evict_is_bounded_and_valid(monkeypatch):
    monkeypatch.setattr(signing, "_DOMAIN_ARTIFACT_CACHE", OrderedDict())
    monkeypatch.setattr(signing, "_DOMAIN_ARTIFACT_CACHE_MAX", 16)
    barrier = threading.Barrier(12)

    def churn(worker: int):
        barrier.wait()
        artifacts = []
        for index in range(40):
            payload = _artifact_payload()
            payload["normalized_anchor_sha256"] = f"{worker * 40 + index:064x}"
            artifact = signing.cache_domain_artifact(payload)
            artifacts.append(artifact)
            cached = signing.get_cached_domain_artifact(artifact["artifact_token"])
            assert cached is None or signing.verify_domain_artifact(cached)
        return artifacts[-1]

    with ThreadPoolExecutor(max_workers=12) as pool:
        newest = list(pool.map(churn, range(12)))
    assert len(signing._DOMAIN_ARTIFACT_CACHE) <= 16
    assert all(signing.verify_domain_artifact(artifact) for artifact in newest)


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


def test_jaimini_atomizer_rejects_duplicate_fact_ids():
    with pytest.raises(ValueError, match="DUPLICATE_JAIMINI_FACT_ID"):
        interpretations.iter_jaimini_fact_atoms(
            [
                {"fact_id": "jaimini.karakas.7.AK", "value": "Sun"},
                {"fact_id": "jaimini.karakas.7.AK", "value": "Moon"},
            ]
        )


def test_checker_does_not_trust_approved_provenance_or_arbitrary_prose(monkeypatch):
    payload = _artifact_payload()
    payload["provenance"]["source_review_status"] = "approved"
    payload["source_admission_sha256"] = "a" * 64
    artifact = signing.cache_domain_artifact(payload)

    assert interpretations.validate_jaimini_answer(
        [{"path": "jaimini.karakas.AK", "value": "Saturn"}],
        artifact["artifact_token"],
        interpretation_requested=True,
        summary="You are destined to succeed.",
    ) == ["INTERPRETATION_SOURCE_UNAVAILABLE"]
    assert interpretations.validate_jaimini_answer(
        [{"path": "jaimini.karakas.AK", "value": "Saturn"}],
        artifact["artifact_token"],
        summary="You are destined to succeed.",
    ) == ["INTERPRETATION_SOURCE_UNAVAILABLE"]

    monkeypatch.setattr(
        "jyotish_agent.interpretations.jaimini_source_admission_evidence",
        lambda: {"verified": True, "sha256": "a" * 64, "rule_sources": {}},
        raising=False,
    )
    assert interpretations.validate_jaimini_answer(
        [{"path": "jaimini.karakas.AK", "value": "Saturn"}],
        artifact["artifact_token"],
        interpretation_requested=True,
        summary="You are destined to succeed.",
    ) == ["INTERPRETATION_RENDERER_UNAVAILABLE"]


def test_source_admission_requires_governed_fragment_checksum_verification():
    assert hasattr(rule_profiles, "jaimini_source_admission_verified")
    # The current Jaimini source map is deliberately pending and the governed
    # corpus contains no admitted Jaimini rule pack.
    assert rule_profiles.jaimini_source_admission_verified() is False
    evidence = rule_profiles.jaimini_source_admission_evidence()
    assert evidence["verified"] is False
    assert len(evidence["sha256"]) == 64
    assert evidence["rule_sources"] == {}


def test_future_source_admission_hash_binds_rights_review_and_rule_mapping(monkeypatch):
    checksum = "7" * 64
    source_map = SimpleNamespace(
        interpretation_status="available",
        review=SimpleNamespace(
            status="approved", reviewer="qualified-person", reviewer_role="source-reviewer"
        ),
        rules=(SimpleNamespace(
            rule_id="karakas.scheme", source_status="approved",
            fragment_id="sf_jaimini_1", fragment_sha256=checksum,
        ),),
    )
    manifest = {"sources": [{
        "source_version_id": "sv_jaimini_1877",
        "manifest_checksum": "8" * 64,
        "rights_note": "Verified public-domain Sanskrit root edition.",
        "provenance_url": "https://example.invalid/scan",
        "review": {"status": "approved", "reviewer": "qualified-person"},
        "fragments": [{"fragment_id": "sf_jaimini_1", "checksum": checksum}],
    }]}
    monkeypatch.setattr(rule_profiles, "load_jaimini_source_map", lambda: source_map)
    monkeypatch.setattr(rule_profiles, "load_builtin_manifest", lambda: manifest)
    evidence = rule_profiles.jaimini_source_admission_evidence()
    assert evidence["verified"] is True
    bound = evidence["rule_sources"]["karakas.scheme"]
    assert bound["source_version_id"] == "sv_jaimini_1877"
    assert bound["manifest_checksum"] == "8" * 64
    assert bound["source_reviewer"] == "qualified-person"
    assert len(bound["rights_note_sha256"]) == 64
