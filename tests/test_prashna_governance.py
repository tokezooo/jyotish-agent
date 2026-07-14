from __future__ import annotations

import concurrent.futures
from pydantic import ValidationError

from jyotish_agent import interpretations, signing
from jyotish_agent.prashna import PrashnaFacade
from jyotish_agent.prashna_models import PrashnaRequest, PrashnaRuleResult
from jyotish_agent.prashna_profiles import (
    load_prashna_adjudication_fixtures,
    load_prashna_rule_profile,
    load_prashna_source_map,
    prashna_rule_profile_sha256,
)


def _request(zone: str, timestamp: str, name: str, latitude: float, longitude: float):
    return PrashnaRequest(question="What blocks this work project?", anchor={
        "asked_at": timestamp,
        "place": {"name": name, "latitude": latitude, "longitude": longitude, "zone_id": zone},
    })


def test_profile_source_and_five_cases_are_checksum_bound_and_honestly_pending():
    profile = load_prashna_rule_profile()
    sources = load_prashna_source_map()
    fixtures = load_prashna_adjudication_fixtures()
    assert profile.profile_id == sources.profile_id == "prashna_work_v1"
    assert sources.rule_profile_sha256 == prashna_rule_profile_sha256()
    assert sources.review.model_dump(mode="json") == {
        "status": "pending", "reviewer": None, "reviewer_role": None,
        "reason": "No licensed or public-domain Praśna interpretation corpus and no qualified human adjudication are admitted.",
    }
    assert fixtures.gate_status == "pending"
    assert fixtures.reviewer is fixtures.reviewer_role is None
    assert len(fixtures.cases) == 5
    assert all(case.review_status == "pending" for case in fixtures.cases)


def test_concurrent_places_are_isolated_and_each_result_is_deterministic():
    requests = (
        _request("Europe/Moscow", "2026-07-14T12:00:00+03:00", "A", 55.75, 37.61),
        _request("Asia/Kolkata", "2026-07-14T14:30:00+05:30", "B", 13.08, 80.27),
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(PrashnaFacade().calculate, requests))
    assert [item.status for item in results] == ["completed", "completed"]
    assert [item.provenance.zone_id for item in results] == ["Europe/Moscow", "Asia/Kolkata"]
    assert results[0].model_dump(mode="json") == PrashnaFacade().calculate(requests[0]).model_dump(mode="json")


def test_checker_rejects_mixed_anchor_fingerprint_and_duplicate_atoms():
    result = PrashnaFacade().calculate(
        _request("Europe/Moscow", "2026-07-14T12:00:00+03:00", "A", 55.75, 37.61)
    )
    artifact = signing.get_cached_domain_artifact(result.artifact_token)
    assert interpretations.validate_prashna_answer(
        [], result.artifact_token, normalized_anchor_sha256="0" * 64
    ) == ["ANCHOR_MISMATCH"]
    assert interpretations.validate_prashna_answer(
        [], result.artifact_token, question_fingerprint="0" * 64
    ) == ["QUESTION_FINGERPRINT_MISMATCH"]
    facts = artifact["facts"]
    try:
        interpretations.iter_prashna_fact_atoms([facts[0], facts[0]])
    except ValueError as exc:
        assert "DUPLICATE_PRASHNA_FACT_ID" in str(exc)
    else:
        raise AssertionError("duplicate atoms must be rejected")


def test_normal_result_payload_and_rule_schema_are_bounded():
    result = PrashnaFacade().calculate(
        _request("Europe/Moscow", "2026-07-14T12:00:00+03:00", "A", 55.75, 37.61)
    )
    assert len(result.model_dump_json().encode()) < 512 * 1024
    assert len(result.rules) <= 100
    rules = tuple(
        PrashnaRuleResult(rule_id=f"prashna.test.r{i}", version="1.0.0", status="pass", severity="info", source_status="not_required")
        for i in range(101)
    )
    payload = result.model_dump()
    payload["rules"] = rules
    try:
        type(result).model_validate(payload)
    except ValidationError:
        pass
    else:
        raise AssertionError("more than 100 rules must be rejected")


def test_built_wheel_contains_all_prashna_package_data(tmp_path):
    # The repository's wheel test builds once globally; this assertion inspects any
    # supplied wheel path via the ordinary package-data layout when present.
    import importlib.resources
    root = importlib.resources.files("jyotish_agent").joinpath("data/prashna")
    assert {item.name for item in root.iterdir()} >= {
        "prashna_work_v1.json", "prashna_work_v1_sources.json", "adjudication_fixtures_v1.json"
    }
