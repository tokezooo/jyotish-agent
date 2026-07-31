from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jyotish_agent.api import app
from jyotish_agent.doctrine.jaimini_pack import JaiminiReleaseAudit
from jyotish_agent.mcp_facade import JyotishMcpFacade
from jyotish_agent.mcp_models import JaiminiFullMcpInput
from jyotish_agent.mcp_server import build_server


ROOT = Path(__file__).parents[2]
AUDIT = ROOT / "docs/evidence/doctrine/jaimini-release.json"


def test_available_audit_requires_every_automated_gate_to_pass() -> None:
    payload = json.loads(AUDIT.read_text(encoding="utf-8"))
    payload.update(
        compiled_profile_sha256="a" * 64,
        admission_state="experimental_full",
        blockers=[],
        available=True,
    )
    for gate in payload["gates"]:
        gate.update(status="passed", evidence="verified")
    JaiminiReleaseAudit.model_validate(payload)

    for gate_id in tuple(gate["gate_id"] for gate in payload["gates"]):
        for status in ("missing", "failed"):
            candidate = json.loads(json.dumps(payload))
            gate = next(item for item in candidate["gates"] if item["gate_id"] == gate_id)
            gate.update(status=status, evidence=None if status == "missing" else "failure")
            with pytest.raises(ValueError, match="incomplete required gates"):
                JaiminiReleaseAudit.model_validate(candidate)


def _request(mode: str, locale: str) -> dict[str, object]:
    return {
        "profile": "default",
        "question": "Give a bounded source-bound Jaimini analysis.",
        "mode": mode,
        "locale": locale,
        "topics": ["self", "career", "relationships", "timing"],
        "include_evidence": mode == "inspection",
    }


def test_release_audit_is_honest_and_blocks_promotion_without_compiled_sources() -> (
    None
):
    audit = JaiminiReleaseAudit.model_validate_json(AUDIT.read_text(encoding="utf-8"))

    assert audit.release_id == "full_jaimini_v1"
    assert audit.admission_state == "blocked_sources"
    assert audit.compiled_profile_sha256 is None
    assert audit.available is False
    assert audit.external_review_missing is True
    assert {gate.gate_id for gate in audit.gates if gate.status == "missing"} >= {
        "deep_conversational_e2e",
    }
    hand_worked = next(
        gate for gate in audit.gates if gate.gate_id == "hand_worked_cases"
    )
    assert hand_worked.status == "passed"
    assert hand_worked.evidence is not None
    assert "hand-worked-v1.json" in hand_worked.evidence
    assert "11/11" in hand_worked.evidence
    held_out = next(gate for gate in audit.gates if gate.gate_id == "held_out_cases")
    assert held_out.status == "passed"
    assert held_out.evidence is not None
    assert "geometry-held-out-v1.json" in held_out.evidence
    assert any("nilakantha_subodhini_translation" in item for item in audit.blockers)


def test_quick_full_deep_and_inspection_ru_en_are_additive_fail_closed_surfaces(
    tmp_path: Path,
) -> None:
    facade = JyotishMcpFacade(tmp_path, None)
    for mode in ("quick", "full", "deep", "inspection"):
        for locale in ("ru", "en"):
            parsed = JaiminiFullMcpInput.model_validate(_request(mode, locale))
            result = facade.jaimini_full(parsed)
            assert result.surface == "experimental_full"
            assert result.status == "unavailable"
            assert result.request_mode == mode
            assert result.locale == locale
            assert result.admission_state == "blocked_sources"
            assert result.report is None
            assert result.external_review_missing is True
            assert len(result.model_dump_json()) < 16_000


def test_inspection_is_the_only_mode_that_accepts_evidence_appendix() -> None:
    invalid = _request("full", "en")
    invalid["include_evidence"] = True
    try:
        JaiminiFullMcpInput.model_validate(invalid)
    except Exception as exc:
        assert "include_evidence" in str(exc)
    else:  # pragma: no cover - required strict boundary
        raise AssertionError("non-inspection evidence appendix was accepted")


def test_malformed_or_secret_input_is_sanitized_and_not_reflected(
    tmp_path: Path,
) -> None:
    facade = JyotishMcpFacade(tmp_path, None)
    secret = "private_sources/secret.pdf token=super-secret"
    result = facade.jaimini_full_payload(
        {"question": secret, "mode": "invalid", "unexpected": secret}
    )
    rendered = result.model_dump_json()

    assert result.status == "needs_input"
    assert result.error_code == "INPUT_INVALID"
    assert secret not in rendered
    assert "private_sources" not in rendered
    assert "super-secret" not in rendered


def test_mcp_discovery_publishes_strict_jaimini_full_schema(tmp_path: Path) -> None:
    server = build_server(JyotishMcpFacade(tmp_path, None))
    tool = server._tool_manager.get_tool("jaimini_full")
    assert tool is not None
    schema = tool.parameters["properties"]["request"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]["mode"]["enum"]) == {
        "quick",
        "full",
        "deep",
        "inspection",
    }


def test_release_gate_is_deterministic_fast_and_private(tmp_path: Path) -> None:
    facade = JyotishMcpFacade(tmp_path, None)
    request = JaiminiFullMcpInput.model_validate(_request("inspection", "ru"))
    started = time.perf_counter()
    results = [facade.jaimini_full(request) for _ in range(50)]
    elapsed = time.perf_counter() - started

    assert all(result == results[0] for result in results)
    assert elapsed < 1.0
    rendered = json.dumps(results[0].model_dump(mode="json"), sort_keys=True)
    assert ".pdf" not in rendered
    assert "private_sources" not in rendered


def test_http_adapter_exposes_the_same_fail_closed_release() -> None:
    response = TestClient(app).post(
        "/v2/doctrine/jaimini/full", json=_request("inspection", "en")
    )
    assert response.status_code == 200
    body = response.json()
    assert body["surface"] == "experimental_full"
    assert body["status"] == "unavailable"
    assert body["admission_state"] == "blocked_sources"
    assert body["report"] is None
