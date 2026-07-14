from __future__ import annotations

import concurrent.futures
import datetime as dt

import pytest
from pydantic import ValidationError

from jyotish_agent import interpretations
from jyotish_agent.event_models import EventAnchor, EventPlace
from jyotish_agent.prashna import PrashnaFacade
from jyotish_agent.prashna_models import PrashnaRequest
from jyotish_agent.prashna_profiles import (
    PrashnaAdjudicationFixtures,
    PrashnaRuleProfile,
    PrashnaSourceRule,
    PrashnaSourceMap,
    load_prashna_adjudication_fixtures,
    load_prashna_rule_profile,
    load_prashna_source_map,
)
from jyotish_agent import prashna_profiles


PLACE = {
    "name": "Confidential Alpha Office",
    "latitude": 55.7558,
    "longitude": 37.6173,
    "zone_id": "Europe/Moscow",
}
ANCHOR = {"asked_at": "2026-07-14T12:00:00+03:00", "place": PLACE}


def test_anchor_relation_rejects_same_family_alpha_beta_gamma():
    facade = PrashnaFacade()
    alpha = facade.calculate(PrashnaRequest(question="What blocks project Alpha?", anchor=ANCHOR))
    assert alpha.status == "completed"
    for changed in ("What blocks project Beta?", "What blocks project Gamma?"):
        result = facade.calculate(PrashnaRequest(question=changed, anchor_token=alpha.anchor_token))
        assert result.status == "needs_input"
        assert result.error_code == "ANCHOR_MISMATCH"
        assert result.next_action == "create_new_anchor"
    appended = facade.calculate(PrashnaRequest(
        question="What blocks project Alpha? Which obstacle blocks project Beta?",
        anchor_token=alpha.anchor_token,
        clarification_of_fingerprint=alpha.question_fingerprint,
    ))
    assert appended.status == "needs_input"
    assert appended.error_code == "ANCHOR_MISMATCH"


def test_changed_question_requires_explicit_provable_clarification_relation():
    facade = PrashnaFacade()
    original = "What is blocking my work project?"
    initial = facade.calculate(PrashnaRequest(question=original, anchor=ANCHOR))
    changed = original + " Which obstacle is most visible?"
    accepted = facade.calculate(PrashnaRequest(
        question=changed,
        anchor_token=initial.anchor_token,
        clarification_of_fingerprint=initial.question_fingerprint,
    ))
    unproven = facade.calculate(PrashnaRequest(
        question="Which obstacle in this work project is most visible?",
        anchor_token=initial.anchor_token,
        clarification_of_fingerprint=initial.question_fingerprint,
    ))
    assert accepted.status == "completed"
    assert accepted.question_fingerprint == initial.question_fingerprint
    assert unproven.status == "needs_input"
    assert unproven.error_code == "ANCHOR_MISMATCH"


def test_capture_now_transport_retry_uses_explicit_process_local_idempotency_identity():
    calls = 0

    def clock():
        nonlocal calls
        calls += 1
        return dt.datetime(2026, 7, 14, 9, calls, tzinfo=dt.UTC)

    request = PrashnaRequest(
        question="What blocks project Alpha?",
        capture_now=True,
        place=PLACE,
        idempotency_key="transport-retry-alpha-0001",
    )
    facade = PrashnaFacade(clock=clock)
    first = facade.calculate(request)
    retry = facade.calculate(request)
    assert calls == 1
    assert first.status == retry.status == "completed"
    assert first.anchor_token == retry.anchor_token
    assert first.anchor_summary == retry.anchor_summary


def test_capture_now_concurrent_retry_captures_clock_once():
    calls = 0

    def clock():
        nonlocal calls
        calls += 1
        return dt.datetime(2026, 7, 14, 9, 0, tzinfo=dt.UTC)

    request = PrashnaRequest(
        question="What blocks project Concurrent?",
        capture_now=True,
        place=PLACE,
        idempotency_key="transport-retry-concurrent-0001",
    )
    facade = PrashnaFacade(clock=clock)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: facade.calculate(request), range(2)))
    assert calls == 1
    assert results[0].anchor_token == results[1].anchor_token
    assert results[0].anchor_summary == results[1].anchor_summary


@pytest.mark.parametrize(
    "asked_at",
    [1720958400, "2026-07-14 12:00:00+03:00", "2026-07-14T12:00:00"],
)
def test_event_time_is_strict_rfc3339_only(asked_at):
    with pytest.raises(ValidationError, match="RFC3339"):
        EventAnchor(asked_at=asked_at, place=PLACE)


@pytest.mark.parametrize("zone_id", ["Etc/GMT-3", "Etc/UTC", "UTC", "GMT"])
def test_fixed_offset_zone_aliases_are_rejected(zone_id: str):
    with pytest.raises(ValidationError, match="regional IANA"):
        EventPlace.model_validate({**PLACE, "zone_id": zone_id})


def test_asserted_rfc3339_offset_matches_zone_to_the_minute_exactly():
    london = {**PLACE, "zone_id": "Europe/London"}
    with pytest.raises(ValidationError, match="TIMEZONE_OFFSET_MISMATCH"):
        EventAnchor(asked_at="2026-07-14T12:00:00+00:59", place=london)
    assert EventAnchor(asked_at="2026-07-14T12:00:00+01:00", place=london).normalized_utc.isoformat() == "2026-07-14T11:00:00+00:00"


def test_typed_rescues_include_complete_privacy_safe_registry_envelope():
    facade = PrashnaFacade()
    result = facade.calculate(PrashnaRequest(question="Where are my private keys?", anchor=ANCHOR))
    payload = result.model_dump(mode="json")
    for key in ("error_code", "request_id", "mode", "stage", "retryable", "problem", "cause", "fix", "next_action"):
        assert key in payload
    serialized = result.model_dump_json()
    assert "private keys" not in serialized
    assert "Confidential Alpha Office" not in serialized
    assert "55.7558" not in serialized


def test_validation_error_text_hides_raw_private_inputs():
    with pytest.raises(ValidationError) as captured:
        PrashnaRequest(
            question="SECRET PROJECT ORION",
            capture_now=True,
            place={**PLACE, "zone_id": "Etc/GMT-3"},
            idempotency_key="transport-secret-0001",
        )
    text = str(captured.value)
    assert "SECRET PROJECT ORION" not in text
    assert "Confidential Alpha Office" not in text
    assert "55.7558" not in text


def test_governance_loaders_return_strict_models_and_gate_is_pending():
    profile = load_prashna_rule_profile()
    sources = load_prashna_source_map()
    fixtures = load_prashna_adjudication_fixtures()
    assert isinstance(profile, PrashnaRuleProfile)
    assert isinstance(sources, PrashnaSourceMap)
    assert isinstance(fixtures, PrashnaAdjudicationFixtures)
    assert sources.review.status == fixtures.gate_status == "pending"
    evidence = prashna_profiles.prashna_source_admission_evidence()
    assert evidence["verified"] is False
    assert evidence["rule_sources"] == {}


def test_future_admission_binds_fragments_rights_provenance_reviewer_and_fixtures(monkeypatch):
    profile = load_prashna_rule_profile()
    sources = load_prashna_source_map()
    fixtures = load_prashna_adjudication_fixtures()
    checksums = {rule_id: str(index) * 64 for index, rule_id in enumerate((
        "prashna.geometry.applying_separating",
        "prashna.radicality.source_gate",
    ), start=1)}
    approved_sources = sources.model_copy(update={
        "interpretation_status": "available",
        "review": sources.review.model_copy(update={
            "status": "approved", "reviewer": "qualified-source-reviewer",
            "reviewer_role": "classical-text-reviewer",
        }),
        "rules": tuple(
            PrashnaSourceRule(
                rule_id=rule_id, source_status="approved",
                fragment_id=f"sf_{index}", fragment_sha256=checksum,
            )
            for index, (rule_id, checksum) in enumerate(checksums.items(), start=1)
        ),
    })
    approved_fixtures = fixtures.model_copy(update={
        "gate_status": "approved", "reviewer": "qualified-case-reviewer",
        "reviewer_role": "prashna-practitioner",
        "cases": tuple(case.model_copy(update={"review_status": "approved"}) for case in fixtures.cases),
    })
    manifest = {"sources": [{
        "source_version_id": "sv_prashna_pd",
        "manifest_checksum": "9" * 64,
        "rights_note": "Verified public-domain root edition.",
        "provenance_url": "https://example.invalid/public-domain-scan",
        "review": {
            "status": "approved", "reviewer": "qualified-source-reviewer",
            "reviewer_role": "classical-text-reviewer",
        },
        "fragments": [
            {"fragment_id": f"sf_{index}", "checksum": checksum}
            for index, checksum in enumerate(checksums.values(), start=1)
        ],
    }]}
    monkeypatch.setattr(prashna_profiles, "load_prashna_rule_profile", lambda: profile)
    monkeypatch.setattr(prashna_profiles, "load_prashna_source_map", lambda: approved_sources)
    monkeypatch.setattr(prashna_profiles, "load_prashna_adjudication_fixtures", lambda: approved_fixtures)
    monkeypatch.setattr(prashna_profiles, "load_builtin_manifest", lambda: manifest)
    evidence = prashna_profiles.prashna_source_admission_evidence()
    assert evidence["verified"] is True
    assert set(evidence["rule_sources"]) == set(checksums)
    assert all(item["source_reviewer_role"] == "classical-text-reviewer" for item in evidence["rule_sources"].values())
    assert all(item["provenance_url"].endswith("public-domain-scan") for item in evidence["rule_sources"].values())


def test_checker_accepts_only_canonical_structured_computed_claims():
    result = PrashnaFacade().calculate(PrashnaRequest(question="What blocks project Alpha?", anchor=ANCHOR))
    valid = {
        "claim_type": "computed_fact",
        "path": "prashna.topic.primary_house",
        "value": "10",
        "text": "prashna.topic.primary_house = 10",
    }
    predictive = {**valid, "text": "Project Alpha will definitely succeed."}
    assert interpretations.validate_prashna_answer([valid], result.artifact_token) == []
    assert interpretations.validate_prashna_answer([predictive], result.artifact_token) == [
        "UNSUPPORTED_CLAIM_TEXT:prashna.topic.primary_house"
    ]
    assert interpretations.validate_prashna_answer(
        [{"path": valid["path"], "value": valid["value"]}], result.artifact_token
    ) == ["INVALID_CLAIM_STRUCTURE"]
