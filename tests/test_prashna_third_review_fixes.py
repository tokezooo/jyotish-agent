from __future__ import annotations

import concurrent.futures
import datetime as dt
import threading

import pytest
from pydantic import ValidationError

from jyotish_agent import interpretations, prashna as prashna_module
from jyotish_agent.prashna import PrashnaFacade
from jyotish_agent.prashna_models import PrashnaAnswerSubmission, PrashnaRequest


PLACE = {
    "name": "Private Retry Office",
    "latitude": 55.7558,
    "longitude": 37.6173,
    "zone_id": "Europe/Moscow",
}
ANCHOR = {"asked_at": "2026-07-14T12:00:00+03:00", "place": PLACE}


def _completed():
    return PrashnaFacade().calculate(
        PrashnaRequest(question="What blocks project Alpha?", anchor=ANCHOR)
    )


def _submission_payload(result) -> dict:
    return {
        "artifact_id": result.artifact_id,
        "artifact_sha256": result.artifact_sha256,
        "artifact_token": result.artifact_token,
        "anchor_token": result.anchor_token,
        "normalized_anchor_sha256": result.normalized_anchor_sha256,
        "question_fingerprint": result.question_fingerprint,
        "current_question_fingerprint": result.current_question_fingerprint,
        "question_relation": result.question_relation,
        "claims": [],
        "visible_text": "",
    }


def test_answer_submission_rejects_explicit_empty_claims_at_construction_and_checker():
    payload = _submission_payload(_completed())
    with pytest.raises(ValidationError, match="at least 1"):
        PrashnaAnswerSubmission.model_validate(payload)
    assert interpretations.validate_prashna_answer(payload) == ["INVALID_ANSWER_SUBMISSION"]


def test_capture_retry_returns_exact_cached_result_without_clock_or_engine(monkeypatch):
    clock_calls = 0
    engine_calls = 0

    def clock():
        nonlocal clock_calls
        clock_calls += 1
        return dt.datetime(2026, 7, 14, 9, 0, tzinfo=dt.UTC)

    facade = PrashnaFacade(clock=clock)
    original = facade._calculate_supported

    def counted(**kwargs):
        nonlocal engine_calls
        engine_calls += 1
        return original(**kwargs)

    monkeypatch.setattr(facade, "_calculate_supported", counted)
    request = PrashnaRequest(
        question="What blocks project Cached?", capture_now=True, place=PLACE,
        idempotency_key="third-review-cached-0001",
    )
    first = facade.calculate(request)
    retry = facade.calculate(request)
    assert clock_calls == engine_calls == 1
    assert retry.anchor_token == first.anchor_token
    assert retry.model_dump(mode="json") == first.model_dump(mode="json")


def test_concurrent_capture_retry_is_single_flight_for_clock_and_engine(monkeypatch):
    clock_calls = 0
    engine_calls = 0
    entered = threading.Event()
    release = threading.Event()

    def clock():
        nonlocal clock_calls
        clock_calls += 1
        return dt.datetime(2026, 7, 14, 9, 0, tzinfo=dt.UTC)

    facade = PrashnaFacade(clock=clock)
    original = facade._calculate_supported

    def counted(**kwargs):
        nonlocal engine_calls
        engine_calls += 1
        entered.set()
        assert release.wait(timeout=5)
        return original(**kwargs)

    monkeypatch.setattr(facade, "_calculate_supported", counted)
    request = PrashnaRequest(
        question="What blocks project SingleFlight?", capture_now=True, place=PLACE,
        idempotency_key="third-review-singleflight-0001",
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(facade.calculate, request)
        assert entered.wait(timeout=5)
        second_future = pool.submit(facade.calculate, request)
        release.set()
        first, second = first_future.result(), second_future.result()
    assert clock_calls == engine_calls == 1
    assert first.anchor_token == second.anchor_token
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


@pytest.mark.parametrize("drift", ["rule", "config", "tzdb"])
def test_capture_retry_drift_is_stale_without_clock_engine_or_new_token(monkeypatch, drift: str):
    clock_calls = 0
    engine_calls = 0

    def clock():
        nonlocal clock_calls
        clock_calls += 1
        return dt.datetime(2026, 7, 14, 9, 0, tzinfo=dt.UTC)

    facade = PrashnaFacade(clock=clock)
    original_calculate = facade._calculate_supported

    def counted(**kwargs):
        nonlocal engine_calls
        engine_calls += 1
        return original_calculate(**kwargs)

    monkeypatch.setattr(facade, "_calculate_supported", counted)
    request = PrashnaRequest(
        question=f"What blocks project Drift{drift}?", capture_now=True, place=PLACE,
        idempotency_key=f"third-review-drift-{drift}-0001",
    )
    first = facade.calculate(request)
    original_token = first.anchor_token
    if drift == "rule":
        monkeypatch.setattr(prashna_module, "prashna_rule_profile_sha256", lambda: "3" * 64)
    elif drift == "config":
        monkeypatch.setattr(prashna_module, "_prashna_config_sha256", lambda: "4" * 64)
    else:
        original_anchor_payload = prashna_module._anchor_payload

        def drifted(anchor):
            payload = original_anchor_payload(anchor)
            payload["tzdb_fingerprint"] = "sha256:" + "5" * 64
            return payload

        monkeypatch.setattr(prashna_module, "_anchor_payload", drifted)
    retry = facade.calculate(request)
    assert retry.status == "needs_input"
    assert retry.error_code == "ANCHOR_STALE"
    assert retry.next_action == "create_new_anchor"
    assert clock_calls == engine_calls == 1
    assert original_token == first.anchor_token
