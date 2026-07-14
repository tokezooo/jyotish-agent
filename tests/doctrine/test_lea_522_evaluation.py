from __future__ import annotations

from jyotish_agent.doctrine.evaluation import (
    REQUIRED_AUTOMATED_GATES,
    AdmissionEvaluator,
    EvaluationLedger,
    GateResult,
    QualityMetrics,
    ReviewerDecision,
)


def _gates(status: str = "passed") -> tuple[GateResult, ...]:
    return tuple(
        GateResult(
            gate_id=gate,
            status=status,
            evidence=f"evidence:{gate}" if status == "passed" else None,
        )
        for gate in REQUIRED_AUTOMATED_GATES
    )


def _metrics() -> QualityMetrics:
    return QualityMetrics(
        topic_coverage=0.90,
        source_coverage=0.85,
        conflict_count=2,
        heldout_pass_rate=0.95,
        material_error_count=0,
        confidence_distribution={"low": 2, "medium": 7, "high": 1},
        user_value_score=0.80,
        no_answer_rate=0.05,
    )


def _evaluate(gates, decisions=()):
    return AdmissionEvaluator.evaluate(
        profile_id="shared_doctrine_v1",
        compiled_profile_sha256="a" * 64,
        source_manifest_sha256="b" * 64,
        evidence_store_sha256="c" * 64,
        gates=gates,
        metrics=_metrics(),
        reviewer_decisions=decisions,
    )


def test_missing_or_failed_gate_cannot_be_reported_as_experimental_full() -> None:
    gates = list(_gates())
    gates[-1] = GateResult(
        gate_id="deep_conversational_e2e", status="missing", evidence=None
    )
    report = _evaluate(tuple(gates))
    assert report.admission_state == "automated_verified"
    assert report.eligible_for_experimental_full is False
    assert report.promotion_blockers == ("deep_conversational_e2e:missing",)
    assert report.gate_summary == {
        "passed": len(REQUIRED_AUTOMATED_GATES) - 1,
        "failed": 0,
        "missing": 1,
    }

    failed = list(_gates())
    failed[0] = GateResult(
        gate_id=failed[0].gate_id, status="failed", evidence="test failure"
    )
    assert _evaluate(tuple(failed)).admission_state == "automated_verified"


def test_all_automated_gates_promote_without_external_reviewer() -> None:
    report = _evaluate(_gates())
    assert report.admission_state == "experimental_full"
    assert report.eligible_for_experimental_full is True
    assert report.external_review_missing is True
    assert report.promotion_blockers == ()


def test_reviewer_states_are_partial_reviewed_or_rejected_per_rule_and_profile() -> (
    None
):
    partial = _evaluate(
        _gates(),
        (
            ReviewerDecision(
                subject_type="rule",
                subject_id="rule.one",
                status="approved",
                note="checked",
            ),
            ReviewerDecision(
                subject_type="rule", subject_id="rule.two", status="pending", note=None
            ),
        ),
    )
    assert partial.admission_state == "partially_reviewed"

    reviewed = _evaluate(
        _gates(),
        (
            ReviewerDecision(
                subject_type="profile",
                subject_id="shared_doctrine_v1",
                status="approved",
                note="approved",
            ),
        ),
    )
    assert reviewed.admission_state == "reviewed"

    rejected = _evaluate(
        _gates(),
        (
            ReviewerDecision(
                subject_type="rule",
                subject_id="rule.bad",
                status="rejected",
                note="material error",
            ),
        ),
    )
    assert rejected.admission_state == "rejected"
    assert rejected.rejected_rule_ids == ("rule.bad",)


def test_ledger_preserves_historical_revision_and_filters_rejected_rules_for_new_runs() -> (
    None
):
    ledger = EvaluationLedger()
    old = ledger.append(_evaluate(_gates()))
    rejected = ledger.append(
        _evaluate(
            _gates(),
            (
                ReviewerDecision(
                    subject_type="rule",
                    subject_id="rule.bad",
                    status="rejected",
                    note="bad",
                ),
            ),
        )
    )
    assert ledger.reports == (old, rejected)
    assert ledger.active_rule_ids(("rule.good", "rule.bad")) == ("rule.good",)
    assert old.admission_state == "experimental_full"
    assert old.report_sha256 != rejected.report_sha256


def test_machine_json_and_human_dashboard_are_deterministic_and_complete() -> None:
    report = _evaluate(_gates())
    first_json = report.model_dump_json(indent=2)
    second_json = report.model_dump_json(indent=2)
    first_md = AdmissionEvaluator.render_dashboard(report)
    second_md = AdmissionEvaluator.render_dashboard(report)
    assert first_json == second_json
    assert first_md == second_md
    for label in (
        "Topic coverage",
        "Source coverage",
        "Held-out pass rate",
        "Material errors",
        "Confidence distribution",
        "User value",
        "No-answer rate",
        "experimental_full",
    ):
        assert label in first_md
