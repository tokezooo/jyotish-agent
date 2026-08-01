from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jyotish_agent.api import app
from jyotish_agent.doctrine.prashna_pack import PrashnaReleaseAudit
from jyotish_agent.mcp_facade import JyotishMcpFacade
from jyotish_agent.mcp_models import PrashnaFullMcpInput
from jyotish_agent.mcp_server import build_server


ROOT = Path(__file__).parents[2]
AUDIT = ROOT / "docs/evidence/doctrine/prashna-release.json"


def test_available_audit_requires_every_required_gate_to_pass() -> None:
    payload = json.loads(AUDIT.read_text(encoding="utf-8"))
    payload.update(
        compiled_profile_sha256="b" * 64,
        admission_state="experimental_full",
        blockers=[],
        available=True,
    )
    required = {
        "source_manifest",
        "radicality_and_anchor_suite",
        "taxonomy_ru_en",
        "geometry_property_suite",
        "outcome_graph_and_privacy",
        "tajika_source_admission",
        "published_outcome_cases",
        "held_out_questions",
    }
    for gate in payload["gates"]:
        if gate["gate_id"] in required:
            gate.update(status="passed", evidence="verified")
    PrashnaReleaseAudit.model_validate(payload)

    for gate_id in sorted(required):
        for status in ("missing", "failed"):
            candidate = json.loads(json.dumps(payload))
            gate = next(item for item in candidate["gates"] if item["gate_id"] == gate_id)
            gate.update(status=status, evidence=None if status == "missing" else "failure")
            with pytest.raises(ValueError, match="incomplete required gates"):
                PrashnaReleaseAudit.model_validate(candidate)


def _request(mode: str, locale: str) -> dict[str, object]:
    return {
        "question": "What blocks this low-risk work project?",
        "anchor": {
            "asked_at": "2026-07-14T12:00:00+03:00",
            "place": {
                "name": "Moscow",
                "latitude": 55.7558,
                "longitude": 37.6173,
                "zone_id": "Europe/Moscow",
                "fold": 0,
            },
            "time_confidence": "explicit",
        },
        "mode": mode,
        "locale": locale,
        "include_evidence": mode == "inspection",
    }


def test_release_audit_distinguishes_completed_checks_from_future_follow_up() -> None:
    audit = PrashnaReleaseAudit.model_validate_json(AUDIT.read_text())
    assert audit.release_id == "full_prashna_v1"
    assert audit.admission_state == "blocked_sources"
    assert audit.compiled_profile_sha256 is None
    assert audit.available is False
    assert audit.external_review_missing is True
    assert audit.completed_evidence
    assert audit.future_outcome_follow_up
    assert audit.metrics.published_outcome_case_count == 2
    assert audit.metrics.held_out_question_count == 12
    assert audit.metrics.material_error_rate == 0.0
    assert audit.metrics.no_answer_rate == 0.125
    assert {gate.gate_id for gate in audit.gates if gate.status == "missing"} >= {
        "concierge_future_outcomes",
    }
    published_cases = next(
        gate for gate in audit.gates if gate.gate_id == "published_outcome_cases"
    )
    assert published_cases.status == "passed"
    assert published_cases.evidence is not None
    assert "2/2" in published_cases.evidence
    held_out = next(
        gate for gate in audit.gates if gate.gate_id == "held_out_questions"
    )
    assert held_out.status == "passed"
    assert held_out.evidence is not None
    assert "questions-held-out-v1.json" in held_out.evidence
    assert "12/12" in held_out.evidence
    assert all("held_out" not in blocker for blocker in audit.blockers)


def test_ru_en_mode_matrix_is_additive_and_fails_closed_with_audit(tmp_path) -> None:
    facade = JyotishMcpFacade(tmp_path, None)
    for mode in ("quick", "full", "deep", "inspection"):
        for locale in ("ru", "en"):
            parsed = PrashnaFullMcpInput.model_validate(_request(mode, locale))
            result = facade.prashna_full(parsed)
            assert result.surface == "experimental_full"
            assert result.status == "unavailable"
            assert result.request_mode == mode
            assert result.locale == locale
            assert result.admission_state == "blocked_sources"
            assert result.report is None
            assert result.external_review_missing
            assert len(result.model_dump_json()) < 16_000


def test_only_inspection_accepts_evidence() -> None:
    invalid = _request("full", "en")
    invalid["include_evidence"] = True
    try:
        PrashnaFullMcpInput.model_validate(invalid)
    except Exception as exc:
        assert "include_evidence" in str(exc)
    else:
        raise AssertionError("non-inspection evidence was accepted")


def test_secret_malformed_input_is_sanitized(tmp_path) -> None:
    facade = JyotishMcpFacade(tmp_path, None)
    secret = "private_sources/secret.pdf token=SUPER-ARGON"
    result = facade.prashna_full_payload(
        {"question": secret, "mode": "invalid", "unexpected": secret}
    )
    rendered = result.model_dump_json()
    assert result.status == "needs_input"
    assert result.error_code == "INPUT_INVALID"
    assert "ARGON" not in rendered
    assert "private_sources" not in rendered


def test_mcp_schema_and_release_gate_are_deterministic_fast_and_private(
    tmp_path,
) -> None:
    facade = JyotishMcpFacade(tmp_path, None)
    server = build_server(facade)
    tool = server._tool_manager.get_tool("prashna_full")
    assert tool is not None
    schema = tool.parameters["properties"]["request"]
    assert schema["additionalProperties"] is False

    parsed = PrashnaFullMcpInput.model_validate(_request("inspection", "ru"))
    started = time.perf_counter()
    results = [facade.prashna_full(parsed) for _ in range(50)]
    assert time.perf_counter() - started < 1.0
    assert all(result == results[0] for result in results)
    rendered = json.dumps(results[0].model_dump(mode="json"), sort_keys=True)
    assert ".pdf" not in rendered
    assert "private_sources" not in rendered


def test_http_adapter_exposes_same_fail_closed_release() -> None:
    response = TestClient(app).post(
        "/v2/doctrine/prashna/full", json=_request("inspection", "en")
    )
    assert response.status_code == 200
    body = response.json()
    assert body["surface"] == "experimental_full"
    assert body["status"] == "unavailable"
    assert body["admission_state"] == "blocked_sources"
    assert body["report"] is None
