from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path
from typing import get_args
from zipfile import ZipFile

import pytest
from pydantic import TypeAdapter, ValidationError

from jyotish_agent.error_registry import ERROR_REGISTRY, error_record
from jyotish_agent.jaimini_models import (
    AnalysisScope,
    JaiminiInput,
    JaiminiResult,
    JaiminiRuleProfileId,
    JaiminiSourceMap,
    ReviewMetadata,
    RuleSourceMapping,
)
from jyotish_agent import rule_profiles
from jyotish_agent.rule_profiles import (
    load_jaimini_adjudication_fixtures,
    load_jaimini_rule_profile,
    load_jaimini_source_map,
)


def _place() -> dict:
    return {
        "name": "Synthetic Meridian",
        "latitude": 12.5,
        "longitude": 77.25,
        "timezone": "Asia/Kolkata",
    }


def _result_common(
    *, interpretation_status: str = "unavailable", source_review_status: str = "pending"
) -> dict:
    return {
        "request_id": "jq_public-safe",
        "mode": "jaimini",
        "rule_profile": "jaimini_core_v1",
        "warnings": [],
        "limitations": [
            {"code": "SOURCE_GATE_PENDING", "message": "Interpretation is unavailable."}
        ],
        "interpretation_status": interpretation_status,
        "provenance": {
            "rule_profile_version": "1.0.0",
            "rule_profile_sha256": "a" * 64,
            "source_map_sha256": "b" * 64,
            "source_review_status": source_review_status,
        },
    }


def test_exact_and_approximate_birth_inputs_are_discriminated_and_strict():
    exact = JaiminiInput.model_validate(
        {
            "profile": "synthetic-example",
            "birth": {
                "confidence": "exact",
                "date": "1990-01-15",
                "time": "10:30:00",
                "place": _place(),
            },
            "rule_profile": "jaimini_core_v1",
            "analysis_scope": "core_with_chara_dasha",
            "gender": "female",
            "reference_date": "2026-07-13",
        }
    )
    assert exact.birth.confidence == "exact"
    assert exact.reference_date == dt.date(2026, 7, 13)

    approximate = JaiminiInput.model_validate(
        {
            "profile": "synthetic-example",
            "birth": {
                "confidence": "approximate",
                "date": "1990-01-15",
                "earliest_time": "09:30:00",
                "latest_time": "11:30:00",
                "place": _place(),
            },
            "rule_profile": "jaimini_core_v1",
            "analysis_scope": "core",
        }
    )
    assert approximate.birth.sensitivity_step_minutes == 5
    assert approximate.birth.sample_count == 25

    with pytest.raises(ValidationError, match="extra_forbidden"):
        JaiminiInput.model_validate(
            {
                **exact.model_dump(mode="json"),
                "birth": {**exact.birth.model_dump(mode="json"), "unknown": "private"},
            }
        )


@pytest.mark.parametrize(
    "birth",
    [
        {"confidence": "unknown", "date": "1990-01-15", "place": _place()},
        {
            "confidence": "approximate",
            "date": "1990-01-15",
            "earliest_time": "10:00:00",
            "latest_time": "12:05:00",
            "place": _place(),
        },
        {
            "confidence": "approximate",
            "date": "1990-01-15",
            "earliest_time": "11:00:00",
            "latest_time": "10:00:00",
            "place": _place(),
        },
    ],
)
def test_unknown_or_invalid_approximate_birth_time_is_rejected(birth):
    with pytest.raises(ValidationError):
        JaiminiInput.model_validate(
            {
                "profile": "synthetic-example",
                "birth": birth,
                "rule_profile": "jaimini_core_v1",
                "analysis_scope": "core",
            }
        )


def test_rule_profile_and_analysis_scope_are_closed_contracts():
    assert get_args(JaiminiRuleProfileId) == ("jaimini_core_v1",)
    assert set(get_args(AnalysisScope)) == {"core", "core_with_chara_dasha"}

    schema = JaiminiInput.model_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["properties"]["rule_profile"]["const"] == "jaimini_core_v1"
    assert schema["properties"]["birth"]["discriminator"]["propertyName"] == "confidence"


def test_result_union_has_four_discriminated_privacy_safe_statuses():
    adapter = TypeAdapter(JaiminiResult)
    common = _result_common()
    completed = adapter.validate_python(
        {
            **common,
            "status": "completed",
            "profile_name": "synthetic-example",
            "anchor_summary": "exact birth anchor",
            "sections": [{"section_id": "karakas", "facts": []}],
            "truncation": {"truncated": False, "total_count": 0, "returned_count": 0},
        }
    )
    assert completed.status == "completed"

    for status, next_action in (
        ("needs_input", "provide_birth_range"),
        ("unavailable", "inspect_source_status"),
        ("incomplete", "retry_calculation"),
    ):
        result = adapter.validate_python(
            {**common, "status": status, "next_action": next_action}
        )
        assert result.status == status


@pytest.mark.parametrize("status,next_action", [("unavailable", "inspect_source_status"), ("needs_input", "provide_birth_range"), ("incomplete", "retry_calculation")])
def test_non_completed_results_cannot_claim_available_interpretation(status, next_action):
    with pytest.raises(ValidationError, match="interpretation"):
        TypeAdapter(JaiminiResult).validate_python(
            {
                **_result_common(
                    interpretation_status="available", source_review_status="approved"
                ),
                "status": status,
                "next_action": next_action,
            }
        )


def test_completed_result_requires_approved_sources_for_available_interpretation():
    completed = {
        "status": "completed",
        "profile_name": "synthetic-example",
        "anchor_summary": "exact birth anchor",
        "sections": [],
        "truncation": {"truncated": False, "total_count": 0, "returned_count": 0},
    }
    with pytest.raises(ValidationError, match="approved"):
        TypeAdapter(JaiminiResult).validate_python(
            {
                **_result_common(
                    interpretation_status="available", source_review_status="pending"
                ),
                **completed,
            }
        )

    result = TypeAdapter(JaiminiResult).validate_python(
        {
            **_result_common(
                interpretation_status="available", source_review_status="approved"
            ),
            **completed,
        }
    )
    assert result.interpretation_status == "available"


def test_frozen_profile_encodes_every_doctrinal_and_time_choice():
    profile = load_jaimini_rule_profile()
    assert profile.profile_id == "jaimini_core_v1"
    assert profile.version == "1.0.0"
    assert profile.model_config["frozen"] is True
    assert profile.karakas.schemes == (7, 8)
    assert profile.karakas.eight_karaka_addition == "PiK"
    assert profile.karakas.rahu_treatment == "reverse_within_sign"
    assert profile.karakas.longitude_precision_arcseconds == 1
    assert profile.karakas.exact_tie_policy == "error_requires_adjudication"
    assert profile.karakas.near_tie_threshold_arcseconds == 60
    assert profile.arudha.exception == "same_or_seventh_moves_to_tenth"
    assert profile.rasi_drishti.variant == "modal_sign_aspects"
    assert profile.argala.obstruction_rule == "count_comparison"
    assert profile.argala.obstruction_pairs == ((2, 12), (4, 10), (11, 3), (5, 9))
    assert profile.svamsa.svamsa == "d9_lagna_sign"
    assert profile.svamsa.karakamsa == "d9_atmakaraka_sign"
    assert profile.special_lagnas.rates_minutes_per_sign.model_dump() == {
        "bhava_lagna": 120,
        "hora_lagna": 60,
        "ghati_lagna": 24,
    }
    assert profile.co_lords.scorpio == ("Mars", "Ketu")
    assert profile.co_lords.aquarius == ("Saturn", "Rahu")
    assert profile.co_lords.resolution == "greater_rashi_duration_then_degree_then_fixed_order"
    assert profile.chara_dasha.progression == "odd_forward_even_reverse"
    assert profile.chara_dasha.duration == "inclusive_count_to_lord_minus_one_minimum_one"
    assert profile.chara_dasha.antardasha == "same_direction_from_next_sign"
    assert profile.chara_dasha.gender_semantics == "required_binary_for_progression_seed"
    assert profile.time.year_length_days == 365.2425
    assert profile.time.rounding == "microsecond_half_even"
    assert profile.time.interval_bounds == "[start,end)"


def test_source_map_checksums_profile_and_fails_interpretation_closed():
    profile_resource = resources.files("jyotish_agent").joinpath(
        "data/jaimini/jaimini_core_v1.json"
    )
    source_map = load_jaimini_source_map()
    profile_bytes = profile_resource.read_bytes()

    assert source_map.rule_profile_sha256 == hashlib.sha256(profile_bytes).hexdigest()
    assert source_map.review.status == "pending"
    assert source_map.review.reviewer is None
    assert source_map.calculation_status == "available"
    assert source_map.interpretation_status == "unavailable"
    assert source_map.rules
    assert all(rule.source_status == "pending" for rule in source_map.rules)
    assert all(rule.fragment_id is None for rule in source_map.rules)


@pytest.mark.parametrize(
    "tampered_name",
    ["jaimini_core_v1.json", "jaimini_core_v1_sources.json"],
)
def test_fixture_loader_rejects_stale_profile_or_source_map_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tampered_name: str
):
    source = Path(resources.files("jyotish_agent").joinpath("data/jaimini"))
    copied = tmp_path / "jaimini"
    shutil.copytree(source, copied)
    target = copied / tampered_name
    target.write_bytes(target.read_bytes() + b"\n")
    monkeypatch.setattr(rule_profiles, "_DATA", copied)

    with pytest.raises(ValueError, match="SHA-256"):
        load_jaimini_adjudication_fixtures()


def test_approved_source_gate_requires_reviewer_role_and_bound_approved_rules():
    review = load_jaimini_source_map().review.model_dump()
    review.update(status="approved", reviewer="qualified-reviewer", reviewer_role=None)
    with pytest.raises(ValidationError, match="role"):
        ReviewMetadata.model_validate(review)

    with pytest.raises(ValidationError):
        RuleSourceMapping.model_validate(
            {
                "rule_id": "karakas.scheme",
                "school": "project-canonical-jaimini-v1",
                "fragment_id": "not-an-admitted-fragment",
                "fragment_sha256": "short",
                "source_status": "approved",
            }
        )

    source_map = load_jaimini_source_map().model_dump()
    source_map["review"].update(
        status="approved",
        reviewer="qualified-reviewer",
        reviewer_role="Jaimini source and calculation reviewer",
    )
    source_map["rules"] = [
        {
            **rule,
            "source_status": "approved",
            "fragment_id": f"sf_jaimini_v1_{index}",
            "fragment_sha256": f"{index + 1:064x}",
        }
        for index, rule in enumerate(source_map["rules"])
    ]
    source_map["interpretation_status"] = "available"
    approved = JaiminiSourceMap.model_validate(source_map)
    assert approved.interpretation_status == "available"

    source_map["rules"][0]["source_status"] = "pending"
    source_map["rules"][0]["fragment_id"] = None
    source_map["rules"][0]["fragment_sha256"] = None
    with pytest.raises(ValidationError, match="every rule"):
        JaiminiSourceMap.model_validate(source_map)


def test_five_public_safe_fixtures_validate_inputs_provenance_and_review_state():
    fixtures = load_jaimini_adjudication_fixtures()
    assert {fixture.coverage for fixture in fixtures} >= {
        "karaka_tie",
        "arudha_exception",
        "co_lord_case",
        "exact_dasha_boundary",
        "approximate_time_sensitivity",
    }
    assert len(fixtures) >= 5
    assert all(fixture.public_safe and fixture.synthetic for fixture in fixtures)
    assert all(fixture.review.status == "pending" for fixture in fixtures)
    assert all(fixture.review.reviewer is None for fixture in fixtures)
    assert all(fixture.expected_calculation_status == "pending_independent_implementation" for fixture in fixtures)
    assert all(fixture.input.rule_profile == "jaimini_core_v1" for fixture in fixtures)


def test_jaimini_package_data_is_present_and_json_schema_validates():
    data_root = resources.files("jyotish_agent").joinpath("data/jaimini")
    names = {item.name for item in data_root.iterdir()}
    assert {
        "jaimini_core_v1.json",
        "jaimini_core_v1_sources.json",
        "adjudication_fixtures_v1.json",
    } <= names
    for name in names:
        if name.endswith(".json"):
            assert json.loads(data_root.joinpath(name).read_text("utf-8"))


def test_built_wheel_contains_installed_jaimini_package_data(tmp_path: Path):
    output = tmp_path / "dist"
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(output)],
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(output.glob("*.whl"))
    with ZipFile(wheel) as archive:
        installed_names = set(archive.namelist())
        for relative in (
            "jaimini_core_v1.json",
            "jaimini_core_v1_sources.json",
            "adjudication_fixtures_v1.json",
        ):
            member = f"jyotish_agent/data/jaimini/{relative}"
            assert member in installed_names
            assert json.loads(archive.read(member))

    venv = tmp_path / "venv"
    subprocess.run(
        ["uv", "venv", "--python", sys.executable, str(venv)],
        check=True,
        capture_output=True,
        text=True,
    )
    installed_python = venv / "bin/python"
    subprocess.run(
        [
            "uv", "pip", "install", "--python", str(installed_python),
            "--no-deps", str(wheel),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    probe = subprocess.run(
        [
            str(installed_python),
            "-c",
            (
                "import json; from importlib import resources; "
                "root=resources.files('jyotish_agent').joinpath('data/jaimini'); "
                "assert json.loads(root.joinpath('jaimini_core_v1.json').read_text('utf-8')); "
                "assert json.loads(root.joinpath('jaimini_core_v1_sources.json').read_text('utf-8')); "
                "assert json.loads(root.joinpath('adjudication_fixtures_v1.json').read_text('utf-8'))"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0, probe.stderr


@pytest.mark.parametrize("timezone", ["Not/A_Real_Zone", "UTC+05:30", ""])
def test_jaimini_place_rejects_non_iana_timezones(timezone: str):
    request = {
        "profile": "synthetic-example",
        "birth": {
            "confidence": "exact",
            "date": "1990-01-15",
            "time": "10:30:00",
            "place": {**_place(), "timezone": timezone},
        },
        "rule_profile": "jaimini_core_v1",
        "analysis_scope": "core",
    }
    with pytest.raises(ValidationError, match="IANA"):
        JaiminiInput.model_validate(request)


def test_domain_error_registry_is_uppercase_actionable_and_legacy_shape_is_stable():
    expected = {
        "EVENT_TIME_REQUIRED": "confirm_anchor",
        "EVENT_PLACE_REQUIRED": "provide_event_place",
        "ANCHOR_MISMATCH": "create_new_anchor",
        "SEARCH_RANGE_TOO_LARGE": "narrow_search_range",
        "RULE_PROFILE_UNSUPPORTED": "select_supported_rule_profile",
        "ENGINE_CROSSCHECK_FAILED": "retry_calculation",
        "BIRTH_TIME_RANGE_REQUIRED": "provide_birth_range",
    }
    assert expected.keys() <= ERROR_REGISTRY.keys()
    assert all(code == code.upper() for code in ERROR_REGISTRY)
    assert {code: ERROR_REGISTRY[code]["next_action"] for code in expected} == expected

    legacy = error_record("SQLITE_BUSY", run_id="rr_public", stage="persist")
    assert set(legacy) == {
        "error_code", "run_id", "stage", "retryable", "problem", "cause", "fix"
    }

    domain = error_record(
        "RULE_PROFILE_UNSUPPORTED",
        run_id=None,
        stage="validate",
        request_id="jq_public",
        mode="jaimini",
        supported_values=["jaimini_core_v1"],
        invalid_fields=["rule_profile"],
    )
    assert domain["next_action"] == "select_supported_rule_profile"
    assert domain["request_id"] == "jq_public"
    assert domain["mode"] == "jaimini"
    assert domain["supported_values"] == ["jaimini_core_v1"]
    assert domain["invalid_fields"] == ["rule_profile"]
    assert "private" not in json.dumps(domain).lower()


def test_phase_zero_documentation_states_gate_is_not_approved():
    text = Path("docs/jaimini-phase-0.md").read_text("utf-8")
    assert "interpretation_status: unavailable" in text
    assert "review status: pending" in text
    assert "No Jaimini geometry" in text
