"""Checksum-bound access to immutable Praśna package data."""

from __future__ import annotations

import hashlib
import json
from importlib import resources

_DATA = resources.files("jyotish_agent").joinpath("data/prashna")


def _bytes(name: str) -> bytes:
    return _DATA.joinpath(name).read_bytes()


def load_prashna_rule_profile() -> dict:
    return json.loads(_bytes("prashna_work_v1.json"))


def load_prashna_source_map() -> dict:
    value = json.loads(_bytes("prashna_work_v1_sources.json"))
    if value.get("profile_id") != "prashna_work_v1":
        raise ValueError("Praśna source map profile ID mismatch")
    if value.get("rule_profile_sha256") != prashna_rule_profile_sha256():
        raise ValueError("Praśna rule profile SHA-256 does not match the source map")
    return value


def load_prashna_adjudication_fixtures() -> dict:
    value = json.loads(_bytes("adjudication_fixtures_v1.json"))
    if len(value.get("cases", ())) != 5:
        raise ValueError("Praśna feasibility data must contain exactly five cases")
    if value.get("gate_status") == "approved" and not (
        value.get("reviewer") and value.get("reviewer_role")
    ):
        raise ValueError("approved Praśna fixtures require a named qualified reviewer")
    return value


def prashna_rule_profile_sha256() -> str:
    return hashlib.sha256(_bytes("prashna_work_v1.json")).hexdigest()


def prashna_source_map_sha256() -> str:
    return hashlib.sha256(_bytes("prashna_work_v1_sources.json")).hexdigest()


def prashna_source_admission_evidence() -> dict:
    source_map = load_prashna_source_map()
    verified = bool(
        source_map.get("interpretation_status") == "available"
        and source_map.get("review", {}).get("status") == "approved"
        and source_map.get("review", {}).get("reviewer")
        and source_map.get("review", {}).get("reviewer_role")
        and source_map.get("rules")
    )
    payload = {
        "verified": verified,
        "source_map_sha256": prashna_source_map_sha256(),
        "rule_sources": {} if not verified else source_map["rules"],
    }
    payload["sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return payload
