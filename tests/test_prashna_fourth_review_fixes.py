from __future__ import annotations

import datetime as dt

import pytest

from jyotish_agent import prashna as prashna_module
from jyotish_agent.prashna import PrashnaFacade
from jyotish_agent.prashna_models import PrashnaRequest


PLACE = {
    "name": "Private Material Office",
    "latitude": 55.7558,
    "longitude": 37.6173,
    "zone_id": "Europe/Moscow",
}


def _request(*, key: str, include_trace: bool) -> PrashnaRequest:
    return PrashnaRequest(
        question="What blocks project Material?",
        capture_now=True,
        place=PLACE,
        idempotency_key=key,
        include_trace=include_trace,
    )


def _counted_facade(monkeypatch):
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
    return facade, lambda: (clock_calls, engine_calls)


@pytest.mark.parametrize("initial_trace,retry_trace", [(False, True), (True, False)])
def test_capture_key_rejects_changed_result_selector_before_clock_or_engine(
    monkeypatch, initial_trace: bool, retry_trace: bool
):
    facade, calls = _counted_facade(monkeypatch)
    key = f"fourth-review-trace-{initial_trace}-{retry_trace}"
    first = facade.calculate(_request(key=key, include_trace=initial_trace))
    assert first.status == "completed"
    assert (first.trace is not None) is initial_trace

    conflict = facade.calculate(_request(key=key, include_trace=retry_trace))
    assert conflict.status == "needs_input"
    assert conflict.error_code == "IDEMPOTENCY_CONFLICT"
    assert conflict.next_action == "use_new_idempotency_key"
    assert calls() == (1, 1)


def test_capture_request_selector_audit_covers_every_current_public_field():
    assert set(PrashnaRequest.model_fields) == {
        "question",
        "anchor",
        "capture_now",
        "place",
        "anchor_token",
        "clarification_of_fingerprint",
        "idempotency_key",
        "rule_profile",
        "include_trace",
    }
    request = _request(key="fourth-review-material-audit", include_trace=True)
    material = prashna_module._capture_request_material(
        request, prashna_module.question_fingerprint(request.question)
    )
    assert set(material) == {
        "capture_now",
        "place",
        "rule_profile",
        "include_trace",
        "question_fingerprint",
    }


def test_exact_capture_retry_still_returns_deep_copy_without_clock_or_engine(monkeypatch):
    facade, calls = _counted_facade(monkeypatch)
    request = _request(key="fourth-review-exact-retry", include_trace=True)
    first = facade.calculate(request)
    retry = facade.calculate(request)

    assert calls() == (1, 1)
    assert retry is not first
    assert retry.anchor_token == first.anchor_token
    assert retry.model_dump(mode="json") == first.model_dump(mode="json")
