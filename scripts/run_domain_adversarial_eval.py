#!/usr/bin/env python3
"""Execute the checked-in held-out domain adversarial expectations."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import io
import json
import tempfile
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).parents[1]
DEFAULT_FIXTURE = ROOT / "eval" / "heldout_domain_adversarial_v1.json"
EVENT_PLACE = {
    "name": "private", "latitude": 55.7558, "longitude": 37.6173,
    "zone_id": "Europe/Moscow",
}
EVENT_ANCHOR = {"asked_at": "2026-07-14T12:00:00+03:00", "place": EVENT_PLACE}


def _load_runtime():
    with contextlib.redirect_stdout(io.StringIO()):
        from jyotish_agent.interpretations import validate_jaimini_answer, validate_muhurta_answer
        from jyotish_agent.jaimini import ExactKarakaTieError, JaiminiFacade, chara_karakas
        from jyotish_agent.jaimini_models import JaiminiInput
        from jyotish_agent.mcp_facade import JyotishMcpFacade
        from jyotish_agent.muhurta import MuhurtaFacade
        from jyotish_agent.muhurta_models import MuhurtaSearchRequest
        from jyotish_agent.prashna import PrashnaFacade
        from jyotish_agent.prashna_models import PrashnaCompletedResult, PrashnaRequest
    return {
        "validate_jaimini_answer": validate_jaimini_answer,
        "validate_muhurta_answer": validate_muhurta_answer,
        "ExactKarakaTieError": ExactKarakaTieError,
        "JaiminiFacade": JaiminiFacade,
        "chara_karakas": chara_karakas,
        "JaiminiInput": JaiminiInput,
        "JyotishMcpFacade": JyotishMcpFacade,
        "MuhurtaFacade": MuhurtaFacade,
        "MuhurtaSearchRequest": MuhurtaSearchRequest,
        "PrashnaFacade": PrashnaFacade,
        "PrashnaCompletedResult": PrashnaCompletedResult,
        "PrashnaRequest": PrashnaRequest,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    args = parser.parse_args()
    fixture_bytes = args.fixture.read_bytes()
    fixture = json.loads(fixture_bytes)
    runtime = _load_runtime()

    JaiminiFacade = runtime["JaiminiFacade"]
    JaiminiInput = runtime["JaiminiInput"]
    PrashnaFacade = runtime["PrashnaFacade"]
    PrashnaRequest = runtime["PrashnaRequest"]
    PrashnaCompletedResult = runtime["PrashnaCompletedResult"]
    MuhurtaFacade = runtime["MuhurtaFacade"]
    MuhurtaSearchRequest = runtime["MuhurtaSearchRequest"]

    j_exact_request = JaiminiInput.model_validate({
        "profile": "heldout", "gender": "male", "reference_date": "2026-07-14",
        "birth": {"confidence": "exact", "date": "1990-01-15", "time": "10:30:00",
                  "place": {"name": "private", "latitude": 55.7558, "longitude": 37.6173,
                            "timezone": "Europe/Moscow"}},
    })
    j_approx_request = JaiminiInput.model_validate({
        "profile": "heldout", "gender": "male", "reference_date": "2026-07-14",
        "birth": {"confidence": "approximate", "date": "1990-01-15",
                  "earliest_time": "10:25:00", "latest_time": "10:35:00",
                  "place": {"name": "private", "latitude": 55.7558, "longitude": 37.6173,
                            "timezone": "Europe/Moscow"}},
    })
    with contextlib.redirect_stdout(io.StringIO()):
        j_exact = JaiminiFacade().calculate(j_exact_request)

    p_facade = PrashnaFacade(clock=lambda: dt.datetime(2026, 7, 14, 9, tzinfo=dt.UTC))
    p_base_request = PrashnaRequest.model_validate({
        "question": "What blocks this work project?", "anchor": EVENT_ANCHOR,
    })
    with contextlib.redirect_stdout(io.StringIO()):
        p_base = p_facade.calculate(p_base_request)
    assert isinstance(p_base, PrashnaCompletedResult)

    def muhurta_request(**updates):
        payload = {
            "activity": "focused_work_session_v1", "place": EVENT_PLACE,
            "start": "2026-07-15T00:00:00+03:00", "end": "2026-07-16T00:00:00+03:00",
            "duration_minutes": 90, "hard_constraints": {"require_daylight": True},
        }
        payload.update(updates)
        return MuhurtaSearchRequest.model_validate(payload)

    with contextlib.redirect_stdout(io.StringIO()):
        m_base = MuhurtaFacade().search(muhurta_request())

    def j_exact_tie() -> str:
        values = {"Sun": 10.0, "Moon": 10.0, "Mars": 20.0, "Mercury": 18.0,
                  "Jupiter": 16.0, "Venus": 14.0, "Saturn": 12.0}
        try:
            runtime["chara_karakas"](values)
        except runtime["ExactKarakaTieError"]:
            return "EXACT_TIE_REQUIRES_ADJUDICATION"
        return "TIE_NOT_REJECTED"

    def j_approximate() -> str:
        with contextlib.redirect_stdout(io.StringIO()):
            result = JaiminiFacade().calculate(j_approx_request)
        return (
            "COMPLETED_3_SAMPLES_SOURCE_PENDING"
            if result.status == "completed"
            and "3 samples" in result.anchor_summary
            and result.provenance.source_review_status == "pending"
            else "APPROXIMATE_CONTRACT_FAILED"
        )

    def j_source_prose() -> str:
        violations = runtime["validate_jaimini_answer"](
            [], j_exact.artifact_token, interpretation_requested=True,
        )
        return violations[0] if violations else "PROSE_ACCEPTED"

    def j_fact_substitution() -> str:
        violations = runtime["validate_jaimini_answer"](
            [{"path": "jaimini.karakas.7.AK", "value": "__forged__"}],
            j_exact.artifact_token,
        )
        return "FACT_VALUE_MISMATCH" if violations == ["FACT_VALUE_MISMATCH:jaimini.karakas.7.AK"] else "SUBSTITUTION_ACCEPTED"

    def p_anchor_substitution() -> str:
        result = p_facade.calculate(PrashnaRequest.model_validate({
            "question": "Will my relationship last?", "anchor_token": p_base.anchor_token,
        }))
        return getattr(result, "error_code", "MISMATCH_ACCEPTED")

    def p_retry_drift() -> str:
        first = {"question": "What blocks this work project?", "capture_now": True,
                 "place": EVENT_PLACE, "idempotency_key": "heldout-retry-drift-0001"}
        p_facade.calculate(PrashnaRequest.model_validate(first))
        result = p_facade.calculate(PrashnaRequest.model_validate({**first, "include_trace": True}))
        return getattr(result, "error_code", "DRIFT_ACCEPTED")

    def p_secret_wire() -> str:
        secret = "SECRET_PROJECT_ORION"
        with tempfile.TemporaryDirectory() as directory:
            facade = runtime["JyotishMcpFacade"](Path(directory), None)
            result = facade.prashna_payload({"question": secret, "capture_now": True})
        serialized = result.model_dump_json()
        return "INPUT_INVALID_PRIVATE_ABSENT" if result.error_code == "INPUT_INVALID" and secret not in serialized else "PRIVATE_REFLECTED"

    def p_high_stakes() -> str:
        result = p_facade.calculate(PrashnaRequest.model_validate({
            "question": "Will this medical treatment cure me?", "anchor": EVENT_ANCHOR,
        }))
        return getattr(result, "error_code", "HIGH_STAKES_ACCEPTED")

    def p_source_status() -> str:
        return "COMPLETED_INTERPRETATION_UNAVAILABLE" if p_base.status == "completed" and p_base.interpretation_status == "unavailable" else "SOURCE_GATE_FAILED"

    def m_skipped_date() -> str:
        request = MuhurtaSearchRequest.model_validate({
            "activity": "general",
            "place": {"name": "private", "latitude": -13.8333, "longitude": -171.75, "zone_id": "Pacific/Apia"},
            "start": "2011-12-29T00:00:00-10:00", "end": "2011-12-31T00:00:00+14:00",
            "duration_minutes": 30,
        })
        with contextlib.redirect_stdout(io.StringIO()):
            result = MuhurtaFacade().search(request)
        return "COMPLETED_PHYSICAL_RANGE" if result.status == "completed" else "SKIPPED_DATE_FAILED"

    def m_stale_window() -> str:
        fact = next(item for item in m_base.facts if item.fact_id.endswith(".start"))
        submission = {
            "artifact_id": m_base.artifact_id, "artifact_sha256": m_base.artifact_sha256,
            "artifact_token": m_base.artifact_token, "search_range_sha256": m_base.search_range_sha256,
            "window_ids": ["mw_" + "0" * 24],
            "claims": [{"claim_type": "computed_fact", "path": fact.fact_id,
                        "value": str(fact.value), "text": f"{fact.fact_id} = {fact.value}"}],
            "visible_text": f"{fact.fact_id} = {fact.value}",
        }
        violations = runtime["validate_muhurta_answer"](submission)
        return violations[0] if violations else "STALE_WINDOW_ACCEPTED"

    def m_cancel() -> str:
        result = MuhurtaFacade().search(muhurta_request(cancel_requested=True))
        return getattr(result, "error_code", "CANCEL_IGNORED")

    def m_deadline() -> str:
        result = MuhurtaFacade().search(muhurta_request(deadline_utc="2020-01-01T00:00:00Z"))
        return getattr(result, "error_code", "DEADLINE_IGNORED")

    def m_payload() -> str:
        return "PAYLOAD_UNDER_512_KIB" if len(m_base.model_dump_json().encode()) < 512 * 1024 else "PAYLOAD_EXCEEDED"

    def m_source_status() -> str:
        return (
            "COMPLETED_RANKING_UNAVAILABLE_SOURCE_PENDING"
            if m_base.status == "completed" and m_base.ranking_status == "unavailable"
            and m_base.provenance.source_review_status == "pending"
            else "SOURCE_GATE_FAILED"
        )

    scenarios: dict[str, Callable[[], str]] = {
        name: value for name, value in locals().items()
        if callable(value) and name in {case["id"] for case in fixture["cases"]}
    }
    results = []
    for case in fixture["cases"]:
        actual = scenarios[case["id"]]()
        results.append({"id": case["id"], "domain": case["domain"], "expected": case["expected"],
                        "actual": actual, "passed": actual == case["expected"]})
    passed = sum(item["passed"] for item in results)
    print(json.dumps({
        "schema_version": 1,
        "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
        "total": len(results), "passed": passed, "failed": len(results) - passed,
        "results": results,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
