from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jyotish_agent.api import app
from jyotish_agent.doctrine.muhurta_pack import (
    MuhurtaReleaseAudit,
    load_muhurta_release_audit,
)
from jyotish_agent.doctrine.muhurta_release import _base_request, execute_muhurta_full
from jyotish_agent.mcp_facade import JyotishMcpFacade
from jyotish_agent.mcp_models import MuhurtaFullMcpInput
from jyotish_agent.mcp_server import build_server


ROOT = Path(__file__).parents[2]
AUDIT = ROOT / "docs/evidence/doctrine/muhurta-release.json"
PACKAGED_AUDIT = ROOT / "src/jyotish_agent/data/doctrine/muhurta-release.json"


def _admit_source_bytes(monkeypatch) -> None:
    from types import SimpleNamespace

    from jyotish_agent.doctrine import muhurta_pack

    monkeypatch.setattr(
        muhurta_pack.SourceVerifier,
        "verify",
        staticmethod(lambda manifest, root: SimpleNamespace(ok=True)),
    )


def test_available_audit_requires_every_required_gate_to_pass() -> None:
    payload = json.loads(AUDIT.read_text(encoding="utf-8"))
    payload.update(admission_state="private_experimental", available=True)
    required = {
        "source_manifest",
        "profile_identity",
        "private_baseline_profile",
        "profile_rule_fixture_suite",
        "private_runtime_e2e",
        "independent_held_out_evaluation",
    }
    for gate in payload["gates"]:
        if gate["gate_id"] in required:
            gate.update(status="passed", evidence="verified")
    MuhurtaReleaseAudit.model_validate(payload)

    for gate_id in sorted(required):
        for status in ("missing", "failed"):
            candidate = json.loads(json.dumps(payload))
            gate = next(item for item in candidate["gates"] if item["gate_id"] == gate_id)
            gate.update(status=status, evidence=None if status == "missing" else "failure")
            with pytest.raises(ValueError, match="incomplete required gates"):
                MuhurtaReleaseAudit.model_validate(candidate)


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


def test_audit_promotes_private_release_after_real_held_out_evaluation() -> None:
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
    assert muhurta.automated_held_out_count == 19
    assert muhurta.material_error_count == 0
    assert muhurta.material_error_rate == 0.0
    assert muhurta.concierge_session_count == 0
    assert muhurta.value_score is None
    assert {gate.gate_id for gate in audit.gates if gate.status == "missing"} >= {
        "specialist_review",
        "cross_domain_concierge_sessions",
    }
    held_out = next(
        gate for gate in audit.gates if gate.gate_id == "independent_held_out_evaluation"
    )
    assert held_out.status == "passed"
    assert held_out.evidence is not None
    assert "independent-held-out-v1.json" in held_out.evidence
    assert "19/19" in held_out.evidence
    collection_contract = next(
        gate for gate in audit.gates if gate.gate_id == "concierge_collection_contract"
    )
    assert collection_contract.status == "passed"
    assert collection_contract.evidence is not None
    assert "concierge-readiness.json" in collection_contract.evidence
    review_handoff = next(
        gate for gate in audit.gates if gate.gate_id == "specialist_review_handoff"
    )
    assert review_handoff.status == "passed"
    assert review_handoff.evidence is not None
    assert (
        "two admitted rules, six safe activity profiles, and one quarantined"
        in review_handoff.evidence
    )
    assert "strict response schema" in review_handoff.evidence
    concierge_gate = next(
        gate for gate in audit.gates if gate.gate_id == "cross_domain_concierge_sessions"
    )
    assert concierge_gate.status == "missing"
    assert concierge_gate.evidence is None
    assert all(metric.concierge_session_count == 0 for metric in audit.domain_metrics)
    assert all(metric.value_score is None for metric in audit.domain_metrics)
    assert all(
        "independent_held_out_evaluation" not in blocker
        for blocker in audit.public_release_blockers
    )
    assert next(
        gate for gate in audit.gates if gate.gate_id == "whole_project_independent_review"
    ).status == "passed"


def test_ru_en_public_adapters_execute_verified_private_release(
    tmp_path, monkeypatch
) -> None:
    _admit_source_bytes(monkeypatch)
    facade = JyotishMcpFacade(tmp_path, None)
    for locale in ("ru", "en"):
        parsed = MuhurtaFullMcpInput.model_validate(_request(locale=locale))
        result = facade.muhurta_full(parsed)
        assert result.surface == "experimental_full"
        assert result.status == "completed"
        assert result.profile == "focused_work"
        assert result.admission_state == "private_experimental"
        assert result.report is not None
        assert result.error_code is None
        assert result.external_review_missing is True
        assert result.public_release_blockers


def test_private_release_fails_closed_when_source_bytes_do_not_verify(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("JYOTISH_PRIVATE_SOURCES_ROOT", str(tmp_path / "missing"))
    facade = JyotishMcpFacade(tmp_path, None)
    parsed = MuhurtaFullMcpInput.model_validate(_request())

    result = facade.muhurta_full(parsed)

    assert result.status == "unavailable"
    assert result.admission_state == "private_experimental"
    assert result.profile == "focused_work"
    assert result.report is None
    assert result.error_code == "SOURCE_BYTES_UNVERIFIED"


def test_optional_overlay_bytes_are_not_required_by_classical_runtime(
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    from jyotish_agent.doctrine import muhurta_pack

    verified_ids: set[str] = set()

    def verify(manifest, root):
        del root
        verified_ids.update(source.source_id for source in manifest.sources)
        return SimpleNamespace(ok=True)

    monkeypatch.setattr(
        muhurta_pack.SourceVerifier,
        "verify",
        staticmethod(verify),
    )

    audit = load_muhurta_release_audit()

    assert audit.available is True
    assert verified_ids == {"kalaprakasika_1982"}
    assert "bv_raman_muhurtha_1969" not in verified_ids


def test_high_stakes_activity_remains_blocked_before_engine_execution(tmp_path) -> None:
    facade = JyotishMcpFacade(tmp_path, None)
    parsed = MuhurtaFullMcpInput.model_validate(
        _request(activity="medical procedure", locale="en")
    )
    result = facade.muhurta_full(parsed)
    assert result.status == "unavailable"
    assert result.error_code == "HIGH_STAKES_ACTIVITY"
    assert result.report is None


def test_internal_engine_inspection_is_opt_in_and_carries_fold_utc_provenance() -> None:
    normal = execute_muhurta_full(
        MuhurtaFullMcpInput.model_validate(_request()), locale="en", mode="full"
    )
    inspected = execute_muhurta_full(
        MuhurtaFullMcpInput.model_validate(_request(mode="inspection")),
        locale="en",
        mode="inspection",
    )
    assert normal.report is not None and normal.report.inspection is None
    assert inspected.report is not None and inspected.report.inspection
    item = inspected.report.inspection[0].model_dump(mode="json")
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


def test_runtime_is_deterministic_bounded_and_private(tmp_path, monkeypatch) -> None:
    _admit_source_bytes(monkeypatch)
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


def test_http_adapter_exposes_same_private_release_state(monkeypatch) -> None:
    _admit_source_bytes(monkeypatch)
    response = TestClient(app).post(
        "/v2/doctrine/muhurta/full", json=_request(mode="quick", locale="en")
    )
    assert response.status_code == 200
    body = response.json()
    assert body["surface"] == "experimental_full"
    assert body["status"] == "completed"
    assert body["admission_state"] == "private_experimental"
    assert body["report"] is not None
    assert body["error_code"] is None


def test_http_adapter_fails_closed_when_source_bytes_do_not_verify(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("JYOTISH_PRIVATE_SOURCES_ROOT", str(tmp_path / "missing"))

    response = TestClient(app).post(
        "/v2/doctrine/muhurta/full", json=_request(mode="quick", locale="en")
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["admission_state"] == "private_experimental"
    assert body["report"] is None
    assert body["error_code"] == "SOURCE_BYTES_UNVERIFIED"


def test_internal_engine_evaluates_complete_bounded_range_before_result_limit() -> None:
    parsed = MuhurtaFullMcpInput.model_validate(
        _request(
            end="2026-07-22T00:00:00+03:00",
            result_limit=5,
            near_miss_limit=5,
        )
    )
    request = _base_request(parsed)
    from jyotish_agent.muhurta import MuhurtaFacade

    public_slice = MuhurtaFacade().search(request)
    complete = MuhurtaFacade().search(
        request, internal_result_limit=request.max_candidate_intervals
    )
    assert public_slice.status == complete.status == "completed"
    assert len(public_slice.windows) == 20
    assert len(complete.windows) > len(public_slice.windows)
    assert complete.windows[-1].start.date() > public_slice.windows[-1].start.date()


def test_natal_input_is_rejected_instead_of_silently_scored_as_zero() -> None:
    parsed = MuhurtaFullMcpInput.model_validate(
        _request(
            natal={
                "confidence": "exact",
                "date": "1990-01-01",
                "time": "12:00:00",
                "place": {
                    "name": "Birth place",
                    "latitude": 55.7558,
                    "longitude": 37.6173,
                    "timezone": "Europe/Moscow",
                },
            }
        )
    )
    result = execute_muhurta_full(parsed, locale="en", mode="full")
    assert result.status == "unavailable"
    assert result.reason_code == "NATAL_PERSONALIZATION_NOT_COMPILED"
    assert result.report is None


def test_internal_engine_fails_closed_when_compiled_identity_is_invalid(
    monkeypatch,
) -> None:
    import jyotish_agent.doctrine.muhurta_release as release_module

    def substituted(*, verify_source_bytes: bool = True):
        del verify_source_bytes
        raise ValueError("MUHURTA_COMPILED_PROFILE_SUBSTITUTED")

    monkeypatch.setattr(release_module, "load_muhurta_release_audit", substituted)
    parsed = MuhurtaFullMcpInput.model_validate(_request())
    result = release_module.execute_muhurta_full(parsed, locale="en", mode="full")
    assert result.status == "unavailable"
    assert result.reason_code == "RELEASE_IDENTITY_INVALID"
    assert result.report is None
