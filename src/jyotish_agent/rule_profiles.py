"""Validated access to immutable Jaimini Phase 0 package data."""

from __future__ import annotations

import hashlib
import json
from importlib import resources

from pydantic import TypeAdapter

from .corpus import load_builtin_manifest
from .jaimini_models import JaiminiFixture, JaiminiRuleProfile, JaiminiSourceMap

_DATA = resources.files("jyotish_agent").joinpath("data/jaimini")


def _bytes(name: str) -> bytes:
    return _DATA.joinpath(name).read_bytes()


def _json(name: str):
    return json.loads(_bytes(name))


def _sha256(name: str) -> str:
    return hashlib.sha256(_bytes(name)).hexdigest()


def jaimini_rule_profile_sha256() -> str:
    return _sha256("jaimini_core_v1.json")


def jaimini_source_map_sha256() -> str:
    return _sha256("jaimini_core_v1_sources.json")


def jaimini_source_admission_verified() -> bool:
    """Return true only when every approved mapping resolves in governed corpus data."""
    return bool(jaimini_source_admission_evidence()["verified"])


def jaimini_source_admission_evidence() -> dict:
    """Return a canonical, hash-bound projection of governed Jaimini rule sources."""
    source_map = load_jaimini_source_map()
    gate_metadata_valid = (
        source_map.interpretation_status != "available"
        or source_map.review.status != "approved"
        or not source_map.review.reviewer
        or not source_map.review.reviewer_role
    ) is False
    admitted: dict[str, dict[str, str]] = {}
    for source in load_builtin_manifest()["sources"]:
        if source.get("review", {}).get("status") != "approved":
            continue
        if not source.get("rights_note") or not source.get("provenance_url"):
            continue
        source_review = source.get("review", {})
        for fragment in source.get("fragments", []):
            admitted[fragment["fragment_id"]] = {
                "fragment_sha256": fragment["checksum"],
                "source_version_id": source["source_version_id"],
                "manifest_checksum": source["manifest_checksum"],
                "rights_note_sha256": hashlib.sha256(
                    source["rights_note"].encode("utf-8")
                ).hexdigest(),
                "provenance_url": source["provenance_url"],
                "source_reviewer": source_review.get("reviewer", ""),
            }
    verified = gate_metadata_valid and bool(source_map.rules) and all(
        rule.source_status == "approved"
        and rule.fragment_id in admitted
        and admitted[rule.fragment_id]["fragment_sha256"] == rule.fragment_sha256
        for rule in source_map.rules
    )
    rule_sources = (
        {
            rule.rule_id: {
                "fragment_id": rule.fragment_id,
                "fragment_sha256": rule.fragment_sha256,
                **admitted[rule.fragment_id],
            }
            for rule in source_map.rules
        }
        if verified
        else {}
    )
    payload = {
        "verified": verified,
        "source_map_sha256": jaimini_source_map_sha256(),
        "rule_sources": rule_sources,
    }
    payload["sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload


def load_jaimini_rule_profile() -> JaiminiRuleProfile:
    return JaiminiRuleProfile.model_validate(_json("jaimini_core_v1.json"))


def load_jaimini_source_map() -> JaiminiSourceMap:
    source_map = JaiminiSourceMap.model_validate(_json("jaimini_core_v1_sources.json"))
    actual_profile_hash = _sha256("jaimini_core_v1.json")
    if source_map.rule_profile_sha256 != actual_profile_hash:
        raise ValueError("Jaimini rule profile SHA-256 does not match the source map")
    return source_map


def load_jaimini_adjudication_fixtures() -> tuple[JaiminiFixture, ...]:
    source_map = load_jaimini_source_map()
    fixtures = TypeAdapter(tuple[JaiminiFixture, ...]).validate_python(
        _json("adjudication_fixtures_v1.json")
    )
    profile_hash = _sha256("jaimini_core_v1.json")
    source_map_hash = _sha256("jaimini_core_v1_sources.json")
    for fixture in fixtures:
        if fixture.rule_profile_sha256 != profile_hash:
            raise ValueError(f"Fixture {fixture.fixture_id} rule profile SHA-256 mismatch")
        if fixture.source_map_sha256 != source_map_hash:
            raise ValueError(f"Fixture {fixture.fixture_id} source map SHA-256 mismatch")
        if fixture.input.rule_profile != source_map.rule_profile_id:
            raise ValueError(f"Fixture {fixture.fixture_id} rule profile ID mismatch")
    return fixtures
