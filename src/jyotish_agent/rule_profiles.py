"""Validated access to immutable Jaimini Phase 0 package data."""

from __future__ import annotations

import hashlib
import json
from importlib import resources

from pydantic import TypeAdapter

from .jaimini_models import JaiminiFixture, JaiminiRuleProfile, JaiminiSourceMap

_DATA = resources.files("jyotish_agent").joinpath("data/jaimini")


def _bytes(name: str) -> bytes:
    return _DATA.joinpath(name).read_bytes()


def _json(name: str):
    return json.loads(_bytes(name))


def _sha256(name: str) -> str:
    return hashlib.sha256(_bytes(name)).hexdigest()


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
