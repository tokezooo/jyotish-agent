from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

from jyotish_agent.mcp_server import SERVER_INSTRUCTIONS, build_server
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
        assert str(exc) == "error_code must be a registered stable code"
    else:  # pragma: no cover
        raise AssertionError("privacy-unsafe error code was accepted")


def test_operation_metric_rejects_private_and_non_strict_runtime_values() -> None:
    base = {
        "mode": "prashna", "status": "needs_input", "duration_ms": 1,
        "candidate_count": 0, "sample_count": 0, "result_count": 0,
        "truncated": False, "error_code": "INPUT_INVALID",
    }
    for private in ("SECRET_PROJECT_ORION", "VLAD_PRIVATE_1990", "LATITUDE_557558"):
        try:
            project_operation_metric(**{**base, "error_code": private})
        except ValueError as exc:
            assert str(exc) == "error_code must be a registered stable code"
        else:  # pragma: no cover
            raise AssertionError("private material was accepted as an error code")
    for field, value in (
        ("truncated", 1), ("truncated", "false"), ("duration_ms", object()),
        ("candidate_count", object()), ("mode", object()), ("status", object()),
    ):
        try:
            project_operation_metric(**{**base, field: value})
        except (TypeError, ValueError):
            pass
        else:  # pragma: no cover
            raise AssertionError(f"non-strict {field} was accepted")


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
    manifest = json.loads((ROOT / "tests" / "fixtures" / "task7_requirement_manifest_v1.json").read_text())
    assert audit["schema_version"] == 1
    requirements = audit["requirements"]
    assert len(requirements) >= 45
    assert len({item["id"] for item in requirements}) == len(requirements)
    canonical = {
        requirement_id
        for section in manifest["plan_sections"].values()
        for requirement_id in section
    }
    assert len(canonical) == sum(len(section) for section in manifest["plan_sections"].values())
    assert {item["id"] for item in requirements} == canonical
    assert all(item["status"] in {"met", "intentionally_unavailable", "not_in_scope", "gap"} for item in requirements)
    assert all(item["evidence"] for item in requirements)
    unavailable = {item["id"] for item in requirements if item["status"] == "intentionally_unavailable"}
    assert {
        "governance.jaimini_sources", "governance.prashna_sources",
        "governance.muhurta_sources", "value.real_concierge_sessions",
        "jaimini.governed_interpretation", "prashna.doctrinal_judgement",
        "muhurta.doctrinal_ranking", "muhurta.natal_personalization",
        "jaimini.adjudicated_golden_fixtures",
        "muhurta.requested_planetary_change_boundaries",
        "muhurta.adjudicated_golden_searches",
        "release.doctrinal_quality_held_out_evals",
    } <= unavailable
    gaps = {item["id"] for item in requirements if item["status"] == "gap"}
    assert gaps == set()
    counts = Counter(item["status"] for item in requirements)
    assert audit["summary"] == {
        status: counts[status]
        for status in ("met", "intentionally_unavailable", "not_in_scope", "gap")
    }


def test_stdio_release_matrix_is_privacy_safe_and_covers_brief() -> None:
    matrix = json.loads((ROOT / "docs" / "release-stdio-matrix-v1.json").read_text())
    ids = {case["id"] for case in matrix["cases"]}
    assert {"j_ru_exact", "j_en_approximate", "j_tie", "j_boundary", "j_inspection"} <= ids
    assert {"p_ru_explicit", "p_en_capture_retry_clarify", "p_material_mismatch", "p_secret_invalid"} <= ids
    assert {"m_ru_one_day", "m_en_multi_day", "m_no_window", "m_oversized", "m_cancel_deadline", "m_high_stakes"} <= ids
    assert matrix["transport"] == "mixed_release_evidence"
    assert all(case["evidence_layer"] in {"process_stdio", "facade", "pure_core"} for case in matrix["cases"])
    assert all(case["assertions"] for case in matrix["cases"])
    for case in matrix["cases"]:
        if case["evidence_layer"] == "process_stdio":
            assert "stdio" in case["evidence"].lower()
        assert set(case["assertions"]) <= set(matrix["assertion_catalog"])
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


def test_codex_smoke_artifact_schema_requires_real_routing_and_leak_checks() -> None:
    schema = json.loads((ROOT / "docs" / "codex-conversational-smoke-schema-v1.json").read_text())
    case = schema["properties"]["cases"]["items"]
    assert case["additionalProperties"] is False
    assert {
        "prompt", "output_redacted", "tool_routing", "result_status", "checks", "passed",
    } <= set(case["required"])
    assert {
        "natural_answer", "source_gate_honest", "no_internal_ledger",
        "no_private_material", "expected_route",
    } == set(case["properties"]["checks"]["required"])
    assert schema["properties"]["summary"]["properties"]["release_gate"]["enum"] == ["passed", "failed"]
    excluded = schema["properties"]["excluded_failed_attempts"]["items"]
    assert excluded["additionalProperties"] is False
    assert {"failure", "counted", "corrective_commit"} <= set(excluded["required"])
    assert excluded["properties"]["counted"]["const"] is False


def test_real_codex_smokes_cover_quick_and_inspection_for_every_domain() -> None:
    artifact = json.loads((ROOT / "docs" / "release-codex-conversational-smokes-v1.json").read_text())
    assert artifact["runner"] == "real_codex_cli_against_current_worktree"
    assert artifact["summary"] == {"passed": 6, "failed": 0, "release_gate": "passed"}
    by_route: dict[str, set[str]] = {}
    for case in artifact["cases"]:
        assert case["passed"] is True and case["failure"] is None
        assert all(case["checks"].values())
        assert len(case["tool_routing"]) == 1
        assert len(case["raw_transcript_sha256"]) == 64
        assert len(case["execution_record_sha256"]) == 64
        by_route.setdefault(case["tool_routing"][0], set()).add(case["flow"])
    assert by_route == {
        "jaimini": {"quick", "inspection"},
        "prashna": {"quick", "inspection"},
        "muhurta": {"quick", "inspection"},
    }
    assert artifact["excluded_failed_attempts"] == [{
        "id": "cs_failed_prashna_pre_guard_inference",
        "prompt": "RU quick obstacle question produced unsupported practical inference",
        "output_redacted": "The pre-fix answer hid internals but inferred a practical communication or ownership theme from computed factors while source review was pending.",
        "failure": "Source-gate honesty failed: practical meaning was inferred from literal chart facts.",
        "raw_transcript_sha256": "544a6265959aa52e0cd75dac5b06b1a298531b8e9dd9f187c86869eba419dd94",
        "execution_record": "docs/evidence/codex-smokes/cs_failed_prashna_pre_guard_inference.json",
        "execution_record_sha256": "1a2fb4547ed8c0cc7481999a365341e06adc229ce364631c289136ef779d19c5",
        "counted": False,
        "corrective_commit": "75e16b0",
    }]
    serialized = json.dumps(artifact, sort_keys=True).lower()
    assert not any(marker in serialized for marker in ("artifact_token", "question_fingerprint", "jya_", "sha256:"))


def test_codex_smoke_execution_records_are_canonical_durable_evidence() -> None:
    index = json.loads((ROOT / "docs" / "release-codex-conversational-smokes-v1.json").read_text())
    records = sorted((ROOT / "docs" / "evidence" / "codex-smokes").glob("*.json"))
    assert len(records) == 7
    loaded: dict[str, dict] = {}
    for path in records:
        raw = path.read_bytes()
        record = json.loads(raw)
        canonical = json.dumps(
            record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode() + b"\n"
        assert raw == canonical
        assert record["client_version"] == "codex-cli 0.144.0"
        assert record["exit_code"] == 0
        assert record["sandbox"] == "read-only"
        assert record["mcp_command_identity"] == "uv --directory <current-worktree> run jyotish-mcp"
        assert [event["event"] for event in record["ordered_events"]] == [
            "thread_started", "tool_call", "final_agent_message", "turn_completed",
        ]
        tool = record["ordered_events"][1]
        assert tool["server"] == "jyotish" and tool["status"] == "completed"
        assert tool["tool"] in {"jaimini", "prashna", "muhurta"}
        assert record["final_output_sanitized"]
        assert record["redaction_policy"] == (
            "Private computed body/sign/date/window details are replaced by "
            "[redacted computed detail] or an equally specific bracketed redaction; "
            "raw JSONL remains local and untracked."
        )
        assert len(record["raw_transcript_sha256"]) == 64
        serialized = raw.decode().lower()
        assert not any(marker in serialized for marker in (
            "/users/", "artifact_token", "question_fingerprint", "anchor_token",
            "jya_", "prq_", "mw_", '"latitude"', '"longitude"',
        ))
        loaded[record["id"]] = record

    expected_times = {
        "cs_jaimini_ru_quick": "2026-07-14T07:32:13+03:00",
        "cs_jaimini_ru_inspection": "2026-07-14T07:36:14+03:00",
        "cs_failed_prashna_pre_guard_inference": "2026-07-14T07:36:59+03:00",
        "cs_muhurta_ru_quick": "2026-07-14T07:38:35+03:00",
        "cs_muhurta_en_inspection": "2026-07-14T07:40:02+03:00",
        "cs_prashna_ru_quick": "2026-07-14T07:40:57+03:00",
        "cs_prashna_en_inspection": "2026-07-14T07:43:20+03:00",
    }
    assert {key: value["executed_at"] for key, value in loaded.items()} == expected_times

    counted_index = {case["id"]: case for case in index["cases"]}
    for record_id, case in counted_index.items():
        record = loaded[record_id]
        path = ROOT / case["execution_record"]
        assert path.name == f"{record_id}.json"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == case["execution_record_sha256"]
        assert record["counted"] is True and record["passed"] is True
        assert record["prompt"] == case["prompt"]
        assert record["raw_transcript_sha256"] == case["raw_transcript_sha256"]
        assert record["ordered_events"][1]["tool"] == case["tool_routing"][0]

    excluded = index["excluded_failed_attempts"][0]
    failed_record = loaded[excluded["id"]]
    failed_path = ROOT / excluded["execution_record"]
    assert hashlib.sha256(failed_path.read_bytes()).hexdigest() == excluded["execution_record_sha256"]
    assert failed_record["counted"] is False and failed_record["passed"] is False
    assert failed_record["failure_reason"] == "unsupported doctrine-like practical inference"
    assert failed_record["corrected_by"] == "75e16b0"


def test_consultant_skill_forbids_practical_inference_while_domain_source_gate_is_pending() -> None:
    skill = (ROOT / ".agents" / "skills" / "jyotish-consultant" / "SKILL.md").read_text()
    normalized = " ".join(skill.split())
    assert "do not infer practical meaning, advice, significance, or an area to watch" in normalized
    assert "Mercury, a house lord, a pada, a boundary, or another computed factor" in normalized
    assert "do not infer a practical obstacle, theme, advice, or area to watch" in " ".join(SERVER_INSTRUCTIONS.split())


def test_heldout_adversarial_runner_matches_independently_authored_fixture() -> None:
    fixture_path = ROOT / "eval" / "heldout_domain_adversarial_v1.json"
    fixture = json.loads(fixture_path.read_text())
    assert fixture["authorship"] == "independently authored release expectations; never generated from production output"
    assert len(fixture["cases"]) == 15
    assert {case["domain"] for case in fixture["cases"]} == {"jaimini", "prashna", "muhurta"}
    assert len({case["id"] for case in fixture["cases"]}) == 15
    assert not any("heldout_domain_adversarial" in path.read_text(errors="ignore") for path in (ROOT / "src").rglob("*.py"))
    completed = subprocess.run(
        [sys.executable, "scripts/run_domain_adversarial_eval.py"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["fixture_sha256"] == hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    assert result["total"] == result["passed"] == 15
    assert result["failed"] == 0
    assert all(item["actual"] == item["expected"] and item["passed"] for item in result["results"])
    saved = json.loads((ROOT / "docs" / "release-domain-adversarial-eval-v1.json").read_text())
    assert saved == result
