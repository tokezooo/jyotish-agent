from __future__ import annotations

import copy
import datetime as dt

import pytest

from jyotish_agent import interpretations, signing
from jyotish_agent.prashna import PrashnaFacade, route_prashna_topic
from jyotish_agent.prashna_models import PrashnaRequest


ANCHOR = {
    "asked_at": "2026-07-14T12:00:00+03:00",
    "place": {
        "name": "Moscow",
        "latitude": 55.7558,
        "longitude": 37.6173,
        "zone_id": "Europe/Moscow",
    },
}


def test_router_is_bounded_and_safety_first():
    routed = route_prashna_topic("Что сейчас мешает моему рабочему проекту?")
    assert routed.status == "supported"
    assert routed.primary_house == 10
    assert routed.secondary_houses == (6, 11)
    assert route_prashna_topic("Будет ли операция успешной?").status == "high_stakes"
    assert route_prashna_topic("Кто выиграет судебный спор по инвестициям?").status == "high_stakes"
    assert route_prashna_topic("Что с отношениями и рабочим проектом?").status == "composite"
    assert route_prashna_topic("Где мои ключи?").status == "unsupported"


def test_explicit_anchor_calculates_bounded_signed_facts_and_fails_source_closed():
    result = PrashnaFacade().calculate(
        PrashnaRequest(question="Что сейчас мешает моему рабочему проекту?", anchor=ANCHOR)
    )
    assert result.status == "completed"
    assert result.mode == "prashna"
    assert result.interpretation_status == "unavailable"
    assert result.anchor_summary == "sealed question moment: 2026-07-14T09:00:00Z; Europe/Moscow"
    assert len(result.anchor_token) == 64
    assert len(result.question_fingerprint) == 64
    assert result.truncation.returned_count <= 100
    assert result.truncation.truncated is False
    ids = [fact.fact_id for fact in result.facts]
    assert ids == sorted(ids)
    assert "prashna.lagna.sign" in ids
    assert "prashna.topic.primary_house" in ids
    assert "prashna.moon.sign" in ids
    assert any(rule.status in {"pass", "warn", "fail", "not_applicable"} for rule in result.rules)
    artifact = signing.get_cached_domain_artifact(result.artifact_token)
    assert artifact is not None and signing.verify_domain_artifact(artifact)
    assert artifact["mode"] == "prashna"
    for field in ("normalized_anchor_sha256", "question_fingerprint", "current_question_fingerprint", "question_relation", "rule_profile_sha256", "source_map_sha256", "facts", "rule_traces", "provenance"):
        changed = copy.deepcopy(artifact)
        changed[field] = "0" * 64 if "sha256" in field or field == "question_fingerprint" else []
        assert signing.verify_domain_artifact(changed) is False
    assert interpretations.validate_prashna_answer(
        [{
            "claim_type": "computed_fact",
            "path": "prashna.topic.primary_house",
            "value": "10",
            "text": "prashna.topic.primary_house = 10",
        }],
        result.artifact_token,
    ) == []
    assert interpretations.validate_prashna_answer([], result.artifact_token, interpretation_requested=True) == [
        "INTERPRETATION_SOURCE_UNAVAILABLE"
    ]


def test_exactly_once_now_capture_and_anchor_reuse_mismatch_and_tamper():
    calls = 0

    def clock():
        nonlocal calls
        calls += 1
        return dt.datetime(2026, 7, 14, 9, 0, tzinfo=dt.UTC) + dt.timedelta(minutes=calls)

    facade = PrashnaFacade(clock=clock)
    place = ANCHOR["place"]
    initial = facade.calculate(
        PrashnaRequest(
            question="What is blocking my work project?",
                capture_now=True,
                place=place,
                idempotency_key="core-now-capture-0001",
        )
    )
    duplicate = facade.calculate(
        PrashnaRequest(question="What is blocking my work project?", anchor_token=initial.anchor_token)
    )
    clarification = facade.calculate(PrashnaRequest(
        question="What is blocking my work project? Which obstacle is most visible?",
        anchor_token=initial.anchor_token,
        clarification_of_fingerprint=initial.question_fingerprint,
    ))
    mismatch = facade.calculate(
        PrashnaRequest(question="Will my relationship last?", anchor_token=initial.anchor_token)
    )
    tamper = facade.calculate(
        PrashnaRequest(question="What is blocking my work project?", anchor_token="0" * 64)
    )
    assert calls == 1
    assert duplicate.status == clarification.status == "completed"
    assert duplicate.anchor_summary == clarification.anchor_summary == initial.anchor_summary
    assert duplicate.question_fingerprint == initial.question_fingerprint
    assert mismatch.status == tamper.status == "needs_input"
    assert mismatch.error_code == tamper.error_code == "ANCHOR_MISMATCH"
    assert mismatch.next_action == "create_new_anchor"


def test_unsupported_composite_and_high_stakes_are_typed_without_engine_work():
    facade = PrashnaFacade()
    unsupported = facade.calculate(PrashnaRequest(question="Где ключи?", anchor=ANCHOR))
    composite = facade.calculate(PrashnaRequest(question="Что с отношениями и проектом?", anchor=ANCHOR))
    medical = facade.calculate(PrashnaRequest(question="Есть ли у меня рак?", anchor=ANCHOR))
    assert unsupported.status == composite.status == "needs_input"
    assert unsupported.next_action == composite.next_action == "provide_primary_question"
    assert medical.status == "unavailable"
    assert medical.next_action == "consult_qualified_professional"
    serialized = medical.model_dump_json()
    assert "рак" not in serialized and "Moscow" not in serialized


@pytest.mark.parametrize(
    "question",
    [
        "Will this medical treatment cure me?",
        "Will I win this legal case?",
        "Should I make this financial investment?",
        "Will this pregnancy be safe?",
        "When will this person die?",
        "Will someone harm me?",
    ],
)
def test_every_named_high_stakes_family_fails_closed(question: str):
    result = PrashnaFacade().calculate(PrashnaRequest(question=question, anchor=ANCHOR))
    assert result.status == "unavailable"
    assert result.error_code == "HIGH_STAKES_TOPIC"
    assert result.next_action == "consult_qualified_professional"
