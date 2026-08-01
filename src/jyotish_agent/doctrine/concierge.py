"""Privacy-safe evidence contract for real doctrine concierge sessions."""

from __future__ import annotations

import hashlib
import statistics
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from ..research_store import canonical_json
from .models import DoctrineDomain, FrozenModel
from .sources import Sha256


class ConciergeUseCase(StrEnum):
    JAIMINI_SELF = "jaimini_self"
    JAIMINI_CAREER = "jaimini_career"
    JAIMINI_RELATIONSHIPS = "jaimini_relationships"
    JAIMINI_TIMING = "jaimini_timing"
    PRASHNA_WORK_PROJECT = "prashna_work_project"
    PRASHNA_LOST_OBJECT = "prashna_lost_object"
    PRASHNA_COMMUNICATION_CONTACT = "prashna_communication_contact"
    PRASHNA_GENERAL_LOW_RISK = "prashna_general_low_risk"
    MUHURTA_CREATIVE_PRODUCTION = "muhurta_creative_production"
    MUHURTA_FOCUSED_WORK = "muhurta_focused_work"
    MUHURTA_GENERAL_PRIVATE_TASK = "muhurta_general_private_task"
    MUHURTA_LOW_RISK_TRAVEL = "muhurta_low_risk_travel"
    MUHURTA_PRODUCT_LAUNCH = "muhurta_product_launch"
    MUHURTA_STUDY_LEARNING = "muhurta_study_learning"


class ConciergeDecisionImpact(StrEnum):
    CHANGED = "changed"
    CLARIFIED = "clarified"
    NONE = "none"
    NOT_APPLICABLE = "not_applicable"


class ConciergePreference(StrEnum):
    ASSISTANT = "assistant"
    ALTERNATIVE = "alternative"
    TIE = "tie"
    NO_COMPARISON = "no_comparison"


class ConciergeOutcomeStatus(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    PENDING = "pending"
    OBSERVED = "observed"


_USE_CASE_DOMAIN = {
    use_case: DoctrineDomain(use_case.value.split("_", 1)[0])
    for use_case in ConciergeUseCase
}


class ConciergeSessionRecord(FrozenModel):
    """One consented session containing metrics only, never raw user content."""

    schema_version: Literal["1.0"] = "1.0"
    session_id: str = Field(pattern=r"^cs_[a-z0-9]{12,48}$")
    consent_to_aggregate: Literal[True]
    domain: DoctrineDomain
    use_case: ConciergeUseCase
    answer_status: Literal["answered", "no_answer", "blocked"]
    decision_impact: ConciergeDecisionImpact
    follow_up: bool
    returned_within_30_days: bool
    value_score: int = Field(ge=1, le=5)
    assistant_latency_seconds: float = Field(ge=0.0, le=86_400.0)
    manual_alternative_latency_seconds: float | None = Field(
        default=None, ge=0.0, le=604_800.0
    )
    preference: ConciergePreference
    reviewer_material_error: bool | None = None
    eventual_outcome_status: ConciergeOutcomeStatus
    eventual_outcome_material_error: bool | None = None

    @model_validator(mode="after")
    def _coherent_private_metric(self) -> "ConciergeSessionRecord":
        if _USE_CASE_DOMAIN[self.use_case] != self.domain:
            raise ValueError("concierge use case does not belong to its domain")
        if self.answer_status != "answered" and self.decision_impact in {
            ConciergeDecisionImpact.CHANGED,
            ConciergeDecisionImpact.CLARIFIED,
        }:
            raise ValueError("an unanswered session cannot claim decision impact")
        compared = self.manual_alternative_latency_seconds is not None
        if compared != (self.preference != ConciergePreference.NO_COMPARISON):
            raise ValueError("preference and manual comparison must be recorded together")
        if self.domain != DoctrineDomain.PRASHNA:
            if self.eventual_outcome_status != ConciergeOutcomeStatus.NOT_APPLICABLE:
                raise ValueError("eventual outcomes are reserved for Prashna sessions")
        if self.eventual_outcome_status == ConciergeOutcomeStatus.OBSERVED:
            if self.eventual_outcome_material_error is None:
                raise ValueError("an observed outcome requires a material-error decision")
        elif self.eventual_outcome_material_error is not None:
            raise ValueError("only an observed outcome can carry a material-error decision")
        return self


class ConciergeDataset(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    dataset_id: str = Field(pattern=r"^concierge_[a-z0-9_]{3,80}$")
    collection_mode: Literal["opt_in_real_or_concierge"]
    used_for_tuning: Literal[False]
    contains_raw_user_content: Literal[False]
    sessions: tuple[ConciergeSessionRecord, ...] = Field(max_length=20)

    @model_validator(mode="after")
    def _unique_sessions(self) -> "ConciergeDataset":
        session_ids = [session.session_id for session in self.sessions]
        if len(session_ids) != len(set(session_ids)):
            raise ValueError("concierge session IDs must be unique")
        return self

    @property
    def dataset_sha256(self) -> str:
        payload = self.model_dump(mode="json")
        payload["sessions"] = sorted(
            payload["sessions"], key=lambda item: item["session_id"]
        )
        return _hash_payload(payload)


class ConciergeDomainMetrics(FrozenModel):
    domain: DoctrineDomain
    session_count: int = Field(ge=0)
    answered_count: int = Field(ge=0)
    no_answer_count: int = Field(ge=0)
    blocked_count: int = Field(ge=0)
    no_answer_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    decision_changed_or_clarified_rate: float | None = Field(
        default=None, ge=0.0, le=1.0
    )
    follow_up_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    return_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    value_score: float | None = Field(default=None, ge=1.0, le=5.0)
    comparison_count: int = Field(ge=0)
    preference_for_assistant_rate: float | None = Field(
        default=None, ge=0.0, le=1.0
    )
    assistant_latency_median_seconds: float | None = Field(default=None, ge=0.0)
    manual_alternative_latency_median_seconds: float | None = Field(
        default=None, ge=0.0
    )
    latency_saving_median_seconds: float | None = None
    reviewer_evaluated_count: int = Field(ge=0)
    material_error_count: int = Field(ge=0)
    material_error_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    observed_outcome_count: int = Field(ge=0)
    outcome_material_error_count: int = Field(ge=0)
    outcome_material_error_rate: float | None = Field(
        default=None, ge=0.0, le=1.0
    )


class ConciergeEvaluationReport(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    evaluation_id: Literal["cross_domain_concierge_v1"]
    dataset_sha256: Sha256
    target_session_count: tuple[Literal[10], Literal[20]] = (10, 20)
    session_count: int = Field(ge=0, le=20)
    domain_metrics: tuple[ConciergeDomainMetrics, ...] = Field(min_length=3)
    cross_domain_value_score: float | None = Field(default=None, ge=1.0, le=5.0)
    reviewer_evaluated_count: int = Field(ge=0)
    material_error_count: int = Field(ge=0)
    material_error_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    gate_status: Literal["passed", "missing"]
    ready_for_release_gate: bool
    blockers: tuple[str, ...]
    privacy_projection: Literal["aggregate_metrics_only"]
    report_sha256: Sha256

    @model_validator(mode="after")
    def _content_addressed_and_honest(self) -> "ConciergeEvaluationReport":
        if self.ready_for_release_gate != (self.gate_status == "passed"):
            raise ValueError("concierge readiness and gate status disagree")
        if self.ready_for_release_gate == bool(self.blockers):
            raise ValueError("concierge blockers disagree with readiness")
        if {item.domain for item in self.domain_metrics} != set(DoctrineDomain):
            raise ValueError("concierge report must include every doctrine domain")
        payload = self.model_dump(mode="json", exclude={"report_sha256"})
        if self.report_sha256 != _hash_payload(payload):
            raise ValueError("concierge report identity is not content-addressed")
        return self


def evaluate_concierge_dataset(dataset: ConciergeDataset) -> ConciergeEvaluationReport:
    """Aggregate a private session dataset without exporting session-level values."""

    metrics = tuple(
        _build_domain_metrics(
            domain,
            tuple(session for session in dataset.sessions if session.domain == domain),
        )
        for domain in DoctrineDomain
    )
    blockers: list[str] = []
    if len(dataset.sessions) < 10:
        blockers.append("session_count: at least 10 opt-in sessions are required")
    for item in metrics:
        if item.session_count == 0:
            blockers.append(f"domain:{item.domain.value}: no session evidence")
            continue
        if item.reviewer_evaluated_count == 0:
            blockers.append(f"domain:{item.domain.value}: no reviewer error decision")
        if item.comparison_count == 0:
            blockers.append(f"domain:{item.domain.value}: no alternative comparison")

    reviewed = [
        session
        for session in dataset.sessions
        if session.reviewer_material_error is not None
    ]
    material_errors = sum(session.reviewer_material_error is True for session in reviewed)
    payload = {
        "schema_version": "1.0",
        "evaluation_id": "cross_domain_concierge_v1",
        "dataset_sha256": dataset.dataset_sha256,
        "target_session_count": (10, 20),
        "session_count": len(dataset.sessions),
        "domain_metrics": [item.model_dump(mode="json") for item in metrics],
        "cross_domain_value_score": _mean(
            [float(session.value_score) for session in dataset.sessions]
        ),
        "reviewer_evaluated_count": len(reviewed),
        "material_error_count": material_errors,
        "material_error_rate": _rate(material_errors, len(reviewed)),
        "gate_status": "missing" if blockers else "passed",
        "ready_for_release_gate": not blockers,
        "blockers": tuple(blockers),
        "privacy_projection": "aggregate_metrics_only",
    }
    return ConciergeEvaluationReport(
        **payload,
        report_sha256=_hash_payload(payload),
    )


def _build_domain_metrics(
    domain: DoctrineDomain,
    sessions: tuple[ConciergeSessionRecord, ...],
) -> ConciergeDomainMetrics:
    answered = sum(item.answer_status == "answered" for item in sessions)
    no_answer = sum(item.answer_status == "no_answer" for item in sessions)
    blocked = sum(item.answer_status == "blocked" for item in sessions)
    impactful = sum(
        item.decision_impact
        in {ConciergeDecisionImpact.CHANGED, ConciergeDecisionImpact.CLARIFIED}
        for item in sessions
    )
    compared = [
        item for item in sessions if item.preference != ConciergePreference.NO_COMPARISON
    ]
    reviewed = [item for item in sessions if item.reviewer_material_error is not None]
    material_errors = sum(item.reviewer_material_error is True for item in reviewed)
    observed = [
        item
        for item in sessions
        if item.eventual_outcome_status == ConciergeOutcomeStatus.OBSERVED
    ]
    outcome_errors = sum(item.eventual_outcome_material_error is True for item in observed)
    return ConciergeDomainMetrics(
        domain=domain,
        session_count=len(sessions),
        answered_count=answered,
        no_answer_count=no_answer,
        blocked_count=blocked,
        no_answer_rate=_rate(no_answer, len(sessions)),
        decision_changed_or_clarified_rate=_rate(impactful, len(sessions)),
        follow_up_rate=_rate(sum(item.follow_up for item in sessions), len(sessions)),
        return_rate=_rate(
            sum(item.returned_within_30_days for item in sessions), len(sessions)
        ),
        value_score=_mean([float(item.value_score) for item in sessions]),
        comparison_count=len(compared),
        preference_for_assistant_rate=_rate(
            sum(item.preference == ConciergePreference.ASSISTANT for item in compared),
            len(compared),
        ),
        assistant_latency_median_seconds=_median(
            [item.assistant_latency_seconds for item in sessions]
        ),
        manual_alternative_latency_median_seconds=_median(
            [
                item.manual_alternative_latency_seconds
                for item in compared
                if item.manual_alternative_latency_seconds is not None
            ]
        ),
        latency_saving_median_seconds=_median(
            [
                item.manual_alternative_latency_seconds
                - item.assistant_latency_seconds
                for item in compared
                if item.manual_alternative_latency_seconds is not None
            ]
        ),
        reviewer_evaluated_count=len(reviewed),
        material_error_count=material_errors,
        material_error_rate=_rate(material_errors, len(reviewed)),
        observed_outcome_count=len(observed),
        outcome_material_error_count=outcome_errors,
        outcome_material_error_rate=_rate(outcome_errors, len(observed)),
    )


def _mean(values: list[float]) -> float | None:
    return None if not values else round(sum(values) / len(values), 6)


def _median(values: list[float]) -> float | None:
    return None if not values else round(float(statistics.median(values)), 6)


def _rate(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else round(numerator / denominator, 6)


def _hash_payload(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
