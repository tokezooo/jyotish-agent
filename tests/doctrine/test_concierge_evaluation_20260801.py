from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from jyotish_agent.doctrine.concierge import (
    ConciergeDataset,
    ConciergeEvaluationReport,
    ConciergeSessionRecord,
    evaluate_concierge_dataset,
)


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/run_concierge_eval.py"
AUDIT = ROOT / "docs/evidence/doctrine/concierge-readiness.json"


def _session(
    index: int,
    *,
    domain: str,
    use_case: str,
    compared: bool = False,
    reviewed: bool | None = None,
    answer_status: str = "answered",
    outcome_status: str = "not_applicable",
    outcome_error: bool | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "session_id": f"cs_{index:012d}",
        "consent_to_aggregate": True,
        "domain": domain,
        "use_case": use_case,
        "answer_status": answer_status,
        "decision_impact": "clarified" if answer_status == "answered" else "none",
        "follow_up": index % 2 == 0,
        "returned_within_30_days": index % 3 == 0,
        "value_score": 4 if answer_status == "answered" else 2,
        "assistant_latency_seconds": 90 + index,
        "manual_alternative_latency_seconds": 900 + index if compared else None,
        "preference": "assistant" if compared else "no_comparison",
        "reviewer_material_error": reviewed,
        "eventual_outcome_status": outcome_status,
        "eventual_outcome_material_error": outcome_error,
    }


def _dataset(sessions: list[dict[str, object]]) -> ConciergeDataset:
    return ConciergeDataset.model_validate(
        {
            "schema_version": "1.0",
            "dataset_id": "concierge_release_gate_v1",
            "collection_mode": "opt_in_real_or_concierge",
            "used_for_tuning": False,
            "contains_raw_user_content": False,
            "sessions": sessions,
        }
    )


def _ready_dataset() -> ConciergeDataset:
    sessions = [
        _session(
            1,
            domain="jaimini",
            use_case="jaimini_self",
            compared=True,
            reviewed=False,
        ),
        _session(2, domain="jaimini", use_case="jaimini_career"),
        _session(3, domain="jaimini", use_case="jaimini_relationships"),
        _session(4, domain="jaimini", use_case="jaimini_timing"),
        _session(
            5,
            domain="prashna",
            use_case="prashna_work_project",
            compared=True,
            reviewed=True,
            outcome_status="observed",
            outcome_error=False,
        ),
        _session(
            6,
            domain="prashna",
            use_case="prashna_lost_object",
            outcome_status="pending",
        ),
        _session(
            7,
            domain="prashna",
            use_case="prashna_communication_contact",
            outcome_status="pending",
        ),
        _session(
            8,
            domain="muhurta",
            use_case="muhurta_focused_work",
            compared=True,
            reviewed=False,
        ),
        _session(9, domain="muhurta", use_case="muhurta_product_launch"),
        _session(
            10,
            domain="muhurta",
            use_case="muhurta_study_learning",
            answer_status="no_answer",
        ),
    ]
    return _dataset(sessions)


def test_ready_report_requires_real_cross_domain_metrics_without_session_export() -> None:
    dataset = _ready_dataset()
    report = evaluate_concierge_dataset(dataset)

    assert report.gate_status == "passed"
    assert report.ready_for_release_gate is True
    assert report.session_count == 10
    assert report.blockers == ()
    assert report.cross_domain_value_score == 3.8
    assert report.reviewer_evaluated_count == 3
    assert report.material_error_count == 1
    assert report.material_error_rate == 0.333333
    assert {item.domain.value for item in report.domain_metrics} == {
        "jaimini",
        "prashna",
        "muhurta",
    }
    muhurta = next(item for item in report.domain_metrics if item.domain == "muhurta")
    assert muhurta.session_count == 3
    assert muhurta.no_answer_count == 1
    assert muhurta.no_answer_rate == 0.333333
    rendered = report.model_dump_json()
    assert "cs_000000000001" not in rendered
    assert "question" not in rendered.casefold()


def test_partial_dataset_is_reported_missing_without_fabricated_values() -> None:
    report = evaluate_concierge_dataset(_dataset([]))

    assert report.gate_status == "missing"
    assert report.ready_for_release_gate is False
    assert report.session_count == 0
    assert report.cross_domain_value_score is None
    assert report.material_error_rate is None
    assert report.blockers == (
        "session_count: at least 10 opt-in sessions are required",
        "domain:jaimini: no session evidence",
        "domain:prashna: no session evidence",
        "domain:muhurta: no session evidence",
    )
    recorded = ConciergeEvaluationReport.model_validate_json(AUDIT.read_text())
    assert report == recorded


def test_dataset_identity_is_order_independent_and_report_tampering_fails() -> None:
    dataset = _ready_dataset()
    reversed_dataset = _dataset(
        list(reversed([item.model_dump(mode="json") for item in dataset.sessions]))
    )
    assert dataset.dataset_sha256 == reversed_dataset.dataset_sha256
    assert (
        evaluate_concierge_dataset(dataset).report_sha256
        == evaluate_concierge_dataset(reversed_dataset).report_sha256
    )

    payload = evaluate_concierge_dataset(dataset).model_dump(mode="json")
    payload["session_count"] = 11
    with pytest.raises(ValueError, match="not content-addressed"):
        ConciergeEvaluationReport.model_validate(payload)


def test_private_schema_rejects_raw_content_duplicates_and_domain_drift() -> None:
    raw = _session(1, domain="jaimini", use_case="jaimini_self")
    raw["question"] = "Private user question"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ConciergeSessionRecord.model_validate(raw)

    duplicate = _session(1, domain="jaimini", use_case="jaimini_self")
    with pytest.raises(ValidationError, match="session IDs must be unique"):
        _dataset([duplicate, duplicate])

    drift = _session(2, domain="muhurta", use_case="jaimini_career")
    with pytest.raises(ValidationError, match="does not belong"):
        ConciergeSessionRecord.model_validate(drift)


def test_comparison_and_eventual_outcome_contracts_fail_closed() -> None:
    comparison = _session(1, domain="jaimini", use_case="jaimini_self")
    comparison["preference"] = "assistant"
    with pytest.raises(ValidationError, match="recorded together"):
        ConciergeSessionRecord.model_validate(comparison)

    non_prashna_outcome = _session(
        2,
        domain="muhurta",
        use_case="muhurta_focused_work",
        outcome_status="pending",
    )
    with pytest.raises(ValidationError, match="reserved for Prashna"):
        ConciergeSessionRecord.model_validate(non_prashna_outcome)

    observed_without_decision = _session(
        3,
        domain="prashna",
        use_case="prashna_work_project",
        outcome_status="observed",
    )
    with pytest.raises(ValidationError, match="requires a material-error decision"):
        ConciergeSessionRecord.model_validate(observed_without_decision)


def test_cli_writes_only_aggregate_and_require_ready_is_fail_closed(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "private.json"
    output_path = tmp_path / "aggregate.json"
    input_path.write_text(_dataset([]).model_dump_json(indent=2), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(input_path),
            "--json-out",
            str(output_path),
            "--require-ready",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr == ""
    report = ConciergeEvaluationReport.model_validate_json(output_path.read_text())
    assert report.session_count == 0

    invalid = json.loads(input_path.read_text())
    invalid["sessions"] = [
        {**_session(1, domain="jaimini", use_case="jaimini_self"), "question": "secret"}
    ]
    input_path.write_text(json.dumps(invalid), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), str(input_path), "--json-out", str(output_path)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    assert completed.stderr == "CONCIERGE_INPUT_INVALID\n"
    assert "secret" not in completed.stderr
