from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from jyotish_agent.api import app
from jyotish_agent.doctrine.muhurta_pack import MuhurtaReleaseAudit
from jyotish_agent.mcp_facade import JyotishMcpFacade
from jyotish_agent.mcp_models import MuhurtaFullMcpInput
from jyotish_agent.mcp_server import build_server


ROOT = Path(__file__).parents[2]
AUDIT = ROOT / "docs/evidence/doctrine/muhurta-release.json"
PACKAGED_AUDIT = ROOT / "src/jyotish_agent/data/doctrine/muhurta-release.json"


def _request(mode: str = "full", locale: str = "en", **updates) -> dict[str, object]:
    payload: dict[str, object] = {
        "activity": "focused work" if locale == "en" else "глубокая работа",
        "place": {
            "name": "Private place",
            "latitude": 55.7558,
            "longitude": 37.6173,
            "zone_id": "Europe/Moscow",
        },
        "start": "2026-07-15T00:00:00+03:00",
        "end": "2026-07-16T00:00:00+03:00",
        "duration_minutes": 60,
        "hard_constraints": {"require_daylight": True},
        "preferences": {"prefer_daylight": True},
        "mode": mode,
        "locale": locale,
        "include_evidence": mode == "inspection",
    }
    payload.update(updates)
    return payload


def test_audit_allows_private_use_but_is_honest_about_public_gaps() -> None:
    audit = MuhurtaReleaseAudit.model_validate_json(AUDIT.read_text())
    packaged = MuhurtaReleaseAudit.model_validate_json(PACKAGED_AUDIT.read_text())
    assert audit == packaged
    assert audit.release_id == "expanded_muhurta_v1"
    assert audit.admission_state == "private_experimental"
    assert audit.available is True
    assert audit.public_release_ready is False
    assert audit.external_review_missing is True
    assert {item.domain for item in audit.domain_metrics} == {
        "jaimini",
        "prashna",
        "muhurta",
    }
    muhurta = next(item for item in audit.domain_metrics if item.domain == "muhurta")
    assert muhurta.material_error_rate == 0.0
    assert muhurta.concierge_session_count == 0
    assert muhurta.value_score is None
    assert {gate.gate_id for gate in audit.gates if gate.status == "missing"} >= {
        "specialist_review",
        "cross_domain_concierge_sessions",
        "whole_project_independent_review",
    }


def test_ru_en_private_runtime_returns_ranked_calendar_ready_windows(tmp_path) -> None:
    facade = JyotishMcpFacade(tmp_path, None)
    for locale in ("ru", "en"):
        parsed = MuhurtaFullMcpInput.model_validate(_request(locale=locale))
        result = facade.muhurta_full(parsed)
        assert result.surface == "experimental_full"
        assert result.status == "completed"
        assert result.profile == "focused_work"
        assert result.admission_state == "private_experimental"
        assert result.report is not None
        assert result.report["top_windows"]
        assert result.report["booking_performed"] is False
        assert result.external_review_missing is True
        assert result.public_release_blockers


def test_high_stakes_activity_remains_blocked_before_engine_execution(tmp_path) -> None:
    facade = JyotishMcpFacade(tmp_path, None)
    parsed = MuhurtaFullMcpInput.model_validate(
        _request(activity="medical procedure", locale="en")
    )
    result = facade.muhurta_full(parsed)
    assert result.status == "unavailable"
    assert result.error_code == "HIGH_STAKES_ACTIVITY"
    assert result.report is None


def test_inspection_is_opt_in_and_carries_fold_utc_provenance(tmp_path) -> None:
    facade = JyotishMcpFacade(tmp_path, None)
    normal = facade.muhurta_full(MuhurtaFullMcpInput.model_validate(_request()))
    inspected = facade.muhurta_full(
        MuhurtaFullMcpInput.model_validate(_request(mode="inspection"))
    )
    assert normal.report is not None and normal.report["inspection"] is None
    assert inspected.report is not None and inspected.report["inspection"]
    item = inspected.report["inspection"][0]
    assert {"zone_id", "start_fold", "end_fold", "start_utc", "end_utc"} <= set(item)


def test_malformed_input_is_sanitized_and_mcp_schema_is_strict(tmp_path) -> None:
    facade = JyotishMcpFacade(tmp_path, None)
    secret = "private_sources/secret.pdf token=SUPER-MUHURTA"
    invalid = facade.muhurta_full_payload(
        {"activity": secret, "mode": "invalid", "unexpected": secret}
    )
    rendered = invalid.model_dump_json()
    assert invalid.status == "needs_input"
    assert invalid.error_code == "INPUT_INVALID"
    assert "SUPER-MUHURTA" not in rendered
    assert "private_sources" not in rendered

    tool = build_server(facade)._tool_manager.get_tool("muhurta_full")
    assert tool is not None
    schema = tool.parameters["properties"]["request"]
    assert schema["additionalProperties"] is False


def test_runtime_is_deterministic_bounded_and_private(tmp_path) -> None:
    facade = JyotishMcpFacade(tmp_path, None)
    parsed = MuhurtaFullMcpInput.model_validate(_request(mode="quick"))
    started = time.perf_counter()
    first = facade.muhurta_full(parsed)
    second = facade.muhurta_full(parsed)
    assert time.perf_counter() - started < 8.0
    assert first == second
    rendered = json.dumps(first.model_dump(mode="json"), ensure_ascii=False)
    assert len(rendered.encode()) < 256 * 1024
    assert "55.7558" not in rendered and "37.6173" not in rendered
    assert "Private place" not in rendered
    assert ".pdf" not in rendered


def test_http_adapter_exposes_same_private_release() -> None:
    response = TestClient(app).post(
        "/v2/doctrine/muhurta/full", json=_request(mode="quick", locale="en")
    )
    assert response.status_code == 200
    body = response.json()
    assert body["surface"] == "experimental_full"
    assert body["status"] == "completed"
    assert body["report"]["top_windows"]
    assert body["report"]["booking_performed"] is False
