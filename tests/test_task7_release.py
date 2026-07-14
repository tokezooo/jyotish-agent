from __future__ import annotations

import asyncio
import hashlib
import json
from collections import Counter
from pathlib import Path

from jyotish_agent.mcp_server import build_server
from jyotish_agent.mcp_facade import JyotishMcpFacade
from jyotish_agent.operation_metrics import project_operation_metric


ROOT = Path(__file__).parents[1]


def test_operation_metric_is_allowlisted_and_bucketed() -> None:
    event = project_operation_metric(
        mode="muhurta",
        status="completed",
        duration_ms=513.2,
        candidate_count=36,
        sample_count=0,
        result_count=5,
        truncated=True,
        error_code=None,
    )
    assert event == {
        "schema_version": 1,
        "mode": "muhurta",
        "status": "completed",
        "duration_bucket": "500ms_to_1s",
        "candidate_count": 36,
        "sample_count": 0,
        "result_count": 5,
        "truncated": True,
        "error_code": None,
    }
    forbidden = {
        "question", "answer", "latitude", "longitude", "place", "profile",
        "anchor", "token", "fingerprint", "time", "trace", "rule",
    }
    assert not any(any(word in key for word in forbidden) for key in event)


def test_operation_metric_rejects_unstable_error_code() -> None:
    try:
        project_operation_metric(
            mode="prashna", status="needs_input", duration_ms=1,
            candidate_count=0, sample_count=0, result_count=0,
            truncated=False, error_code="private question leaked",
        )
    except ValueError as exc:
        assert str(exc) == "error_code must be a stable uppercase code"
    else:  # pragma: no cover
        raise AssertionError("privacy-unsafe error code was accepted")


def test_domain_tool_snapshot_matches_live_discovery(tmp_path: Path) -> None:
    server = build_server(JyotishMcpFacade(tmp_path / "data", None))
    live = {tool.name: tool.model_dump(mode="json") for tool in asyncio.run(server.list_tools())}
    snapshot = json.loads((ROOT / "docs" / "domain-tool-snapshot-v1.json").read_text())
    assert snapshot["schema_version"] == 1
    for name in ("jaimini", "prashna", "muhurta"):
        tool = live[name]
        expected = snapshot["tools"][name]
        assert expected["description"] == tool["description"]
        assert expected["annotations"] == tool["annotations"]
        for field in ("inputSchema", "outputSchema"):
            digest = hashlib.sha256(
                json.dumps(tool[field], sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            assert expected[field + "Sha256"] == digest


def test_requirement_audit_is_complete_and_honest() -> None:
    audit = json.loads((ROOT / "docs" / "prashna-muhurta-jaimini-requirement-audit-v1.json").read_text())
    assert audit["schema_version"] == 1
    requirements = audit["requirements"]
    assert len(requirements) >= 45
    assert len({item["id"] for item in requirements}) == len(requirements)
    assert all(item["status"] in {"met", "intentionally_unavailable", "not_in_scope", "gap"} for item in requirements)
    assert all(item["evidence"] for item in requirements)
    unavailable = {item["id"] for item in requirements if item["status"] == "intentionally_unavailable"}
    assert {
        "governance.jaimini_sources", "governance.prashna_sources",
        "governance.muhurta_sources", "value.real_concierge_sessions",
        "jaimini.governed_interpretation", "prashna.doctrinal_judgement",
        "muhurta.doctrinal_ranking", "muhurta.natal_personalization",
    } <= unavailable
    assert audit["summary"]["gap"] >= 1
    assert audit["summary"] == dict(Counter(item["status"] for item in requirements))


def test_stdio_release_matrix_is_privacy_safe_and_covers_brief() -> None:
    matrix = json.loads((ROOT / "docs" / "release-stdio-matrix-v1.json").read_text())
    ids = {case["id"] for case in matrix["cases"]}
    assert {"j_ru_exact", "j_en_approximate", "j_tie", "j_boundary", "j_inspection"} <= ids
    assert {"p_ru_explicit", "p_en_capture_retry_clarify", "p_material_mismatch", "p_secret_invalid"} <= ids
    assert {"m_ru_one_day", "m_en_multi_day", "m_no_window", "m_oversized", "m_cancel_deadline", "m_high_stakes"} <= ids
    assert set(matrix["common_assertions"]) >= {
        "strict_schema", "signed_artifact", "checker_fail_closed",
        "payload_under_512_kib", "no_research_run", "no_private_error_echo",
    }
    serialized = json.dumps(matrix, sort_keys=True).lower()
    assert not any(word in serialized for word in ("latitude", "longitude", "anchor_token", "fingerprint"))


def test_domain_docs_cover_required_operational_matrix() -> None:
    for name in ("jaimini", "prashna", "muhurta"):
        en = (ROOT / "docs" / "domains" / f"{name}.en.md").read_text()
        ru = (ROOT / "docs" / "domains" / f"{name}.ru.md").read_text()
        combined = en + ru
        for marker in (
            "exact", "approximate", "unknown", "Privacy", "Inspection",
            "Limits", "Errors", "unavailable",
        ):
            assert marker.lower() in combined.lower(), (name, marker)


def test_release_benchmark_artifact_has_all_modes_and_no_private_fields() -> None:
    report = json.loads((ROOT / "docs" / "release-benchmark-v1.json").read_text())
    assert report["schema_version"] == 1
    assert {case["case"] for case in report["cases"]} == {
        "jaimini_exact", "jaimini_approximate", "prashna_explicit",
        "prashna_capture", "prashna_replay", "muhurta_one_day",
    }
    forbidden = ("question", "latitude", "longitude", "profile_name", "anchor_token", "fingerprint")
    serialized = json.dumps(report, sort_keys=True).lower()
    assert not any(name in serialized for name in forbidden)
    assert all(
        case["runs"] >= 1
        and case["payload_bytes"] < 524_288
        and case["ephemeris_mode"] in {"moshier", "swiss"}
        for case in report["cases"]
    )
