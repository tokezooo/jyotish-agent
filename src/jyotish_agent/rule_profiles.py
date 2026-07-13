"""Validated access to immutable Jaimini Phase 0 package data."""

from __future__ import annotations

import json
from importlib import resources

from pydantic import TypeAdapter

from .jaimini_models import JaiminiFixture, JaiminiRuleProfile, JaiminiSourceMap

_DATA = resources.files("jyotish_agent").joinpath("data/jaimini")


def _json(name: str):
    return json.loads(_DATA.joinpath(name).read_text("utf-8"))


def load_jaimini_rule_profile() -> JaiminiRuleProfile:
    return JaiminiRuleProfile.model_validate(_json("jaimini_core_v1.json"))


def load_jaimini_source_map() -> JaiminiSourceMap:
    return JaiminiSourceMap.model_validate(_json("jaimini_core_v1_sources.json"))


def load_jaimini_adjudication_fixtures() -> tuple[JaiminiFixture, ...]:
    return TypeAdapter(tuple[JaiminiFixture, ...]).validate_python(
        _json("adjudication_fixtures_v1.json")
    )
