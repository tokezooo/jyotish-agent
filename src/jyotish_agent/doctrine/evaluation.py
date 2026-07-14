"""Admission states, immutable evaluation reports, and quality dashboard."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import Field, model_validator

from ..research_store import canonical_json
from .models import FrozenModel
from .sources import Sha256


REQUIRED_AUTOMATED_GATES = (
    "rule_fixtures",
    "hand_worked_cases",
    "school_conflict_cases",
    "metamorphic_tests",
    "held_out_cases",
    "conversational_e2e_ru",
    "conversational_e2e_en",
    "privacy_adversarial",
    "payload_performance",
    "deep_conversational_e2e",
)


class GateResult(FrozenModel):
    gate_id: str = Field(min_length=1, max_length=120)
    status: Literal["passed", "failed", "missing"]
    evidence: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _evidence_contract(self) -> "GateResult":
        if self.status == "passed" and not self.evidence:
            raise ValueError("passed gate requires evidence")
        if self.status == "missing" and self.evidence is not None:
            raise ValueError("missing gate cannot claim evidence")
        return self


class QualityMetrics(FrozenModel):
    topic_coverage: float = Field(ge=0.0, le=1.0)
    source_coverage: float = Field(ge=0.0, le=1.0)
    conflict_count: int = Field(ge=0)
    heldout_pass_rate: float = Field(ge=0.0, le=1.0)
    material_error_count: int = Field(ge=0)
    confidence_distribution: dict[str, int]
    user_value_score: float | None = Field(default=None, ge=0.0, le=1.0)
    no_answer_rate: float = Field(ge=0.0, le=1.0)


class ReviewerDecision(FrozenModel):
    subject_type: Literal["rule", "profile"]
    subject_id: str = Field(min_length=1, max_length=160)
    status: Literal["pending", "approved", "amended", "rejected"]
    note: str | None = Field(default=None, max_length=1_000)


class AdmissionReport(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    profile_id: str
    compiled_profile_sha256: Sha256
    source_manifest_sha256: Sha256
    evidence_store_sha256: Sha256
    gates: tuple[GateResult, ...]
    gate_summary: dict[str, int]
    metrics: QualityMetrics
    reviewer_decisions: tuple[ReviewerDecision, ...]
    admission_state: Literal[
        "automated_verified",
        "experimental_full",
        "reviewed",
        "partially_reviewed",
        "rejected",
    ]
    eligible_for_experimental_full: bool
    external_review_missing: bool
    promotion_blockers: tuple[str, ...]
    rejected_rule_ids: tuple[str, ...]
    report_sha256: Sha256


class AdmissionEvaluator:
    @staticmethod
    def assert_required_gates(
        *,
        gates: tuple[object, ...],
        required_gate_ids: tuple[str, ...],
        available: bool,
    ) -> None:
        """Reject an available release unless every required gate passed."""

        if not available:
            return
        by_id = {
            str(getattr(gate, "gate_id")): str(getattr(gate, "status"))
            for gate in gates
        }
        incomplete = [
            gate_id
            for gate_id in required_gate_ids
            if by_id.get(gate_id) != "passed"
        ]
        if incomplete:
            raise ValueError(
                "available release has incomplete required gates: "
                + ", ".join(incomplete)
            )

    @staticmethod
    def evaluate(
        *,
        profile_id: str,
        compiled_profile_sha256: str,
        source_manifest_sha256: str,
        evidence_store_sha256: str,
        gates: tuple[GateResult, ...],
        metrics: QualityMetrics,
        reviewer_decisions: tuple[ReviewerDecision, ...] = (),
    ) -> AdmissionReport:
        by_id: dict[str, GateResult] = {}
        for gate in gates:
            if gate.gate_id in by_id:
                raise ValueError(f"duplicate gate: {gate.gate_id}")
            by_id[gate.gate_id] = gate
        normalized = tuple(
            by_id.get(gate_id, GateResult(gate_id=gate_id, status="missing"))
            for gate_id in REQUIRED_AUTOMATED_GATES
        )
        blockers = tuple(
            f"{gate.gate_id}:{gate.status}"
            for gate in normalized
            if gate.status != "passed"
        )
        eligible = not blockers
        rejected_rules = tuple(
            sorted(
                decision.subject_id
                for decision in reviewer_decisions
                if decision.subject_type == "rule" and decision.status == "rejected"
            )
        )
        if any(decision.status == "rejected" for decision in reviewer_decisions):
            state = "rejected"
        elif not eligible:
            state = "automated_verified"
        elif any(
            decision.subject_type == "profile" and decision.status == "approved"
            for decision in reviewer_decisions
        ):
            state = "reviewed"
        elif reviewer_decisions:
            state = "partially_reviewed"
        else:
            state = "experimental_full"
        summary = {
            status: sum(gate.status == status for gate in normalized)
            for status in ("passed", "failed", "missing")
        }
        external_review_missing = not reviewer_decisions or any(
            decision.status == "pending" for decision in reviewer_decisions
        )
        payload = {
            "schema_version": "1.0",
            "profile_id": profile_id,
            "compiled_profile_sha256": compiled_profile_sha256,
            "source_manifest_sha256": source_manifest_sha256,
            "evidence_store_sha256": evidence_store_sha256,
            "gates": [gate.model_dump(mode="json") for gate in normalized],
            "gate_summary": summary,
            "metrics": metrics.model_dump(mode="json"),
            "reviewer_decisions": [
                decision.model_dump(mode="json") for decision in reviewer_decisions
            ],
            "admission_state": state,
            "eligible_for_experimental_full": eligible,
            "external_review_missing": external_review_missing,
            "promotion_blockers": blockers,
            "rejected_rule_ids": rejected_rules,
        }
        return AdmissionReport(**payload, report_sha256=_hash_payload(payload))

    @staticmethod
    def render_dashboard(report: AdmissionReport) -> str:
        metrics = report.metrics
        confidence = ", ".join(
            f"{key}={metrics.confidence_distribution[key]}"
            for key in sorted(metrics.confidence_distribution)
        )
        value = (
            "missing"
            if metrics.user_value_score is None
            else f"{metrics.user_value_score:.1%}"
        )
        lines = [
            f"# Doctrine quality — {report.profile_id}",
            "",
            f"Admission: **{report.admission_state}**",
            f"Automated gates: {report.gate_summary['passed']} passed, "
            f"{report.gate_summary['failed']} failed, {report.gate_summary['missing']} missing",
            f"External review missing: {'yes' if report.external_review_missing else 'no'}",
            "",
            "## Metrics",
            "",
            f"- Topic coverage: {metrics.topic_coverage:.1%}",
            f"- Source coverage: {metrics.source_coverage:.1%}",
            f"- Conflicts: {metrics.conflict_count}",
            f"- Held-out pass rate: {metrics.heldout_pass_rate:.1%}",
            f"- Material errors: {metrics.material_error_count}",
            f"- Confidence distribution: {confidence}",
            f"- User value: {value}",
            f"- No-answer rate: {metrics.no_answer_rate:.1%}",
        ]
        if report.promotion_blockers:
            lines.extend(["", "## Promotion blockers", ""])
            lines.extend(f"- {item}" for item in report.promotion_blockers)
        return "\n".join(lines).rstrip() + "\n"


class EvaluationLedger:
    def __init__(self) -> None:
        self._reports: list[AdmissionReport] = []

    def append(self, report: AdmissionReport) -> AdmissionReport:
        self._reports.append(report)
        return report

    @property
    def reports(self) -> tuple[AdmissionReport, ...]:
        return tuple(self._reports)

    def active_rule_ids(self, rule_ids: tuple[str, ...]) -> tuple[str, ...]:
        rejected = set(self._reports[-1].rejected_rule_ids) if self._reports else set()
        return tuple(sorted(rule_id for rule_id in rule_ids if rule_id not in rejected))


def _hash_payload(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
