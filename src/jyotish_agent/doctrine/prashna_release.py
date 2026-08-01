"""Private experimental orchestration for the source-bound Full Prashna surface."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from ..prashna import PrashnaFacade, TopicRoute
from ..prashna_models import PrashnaCompletedResult, PrashnaRequest
from .prashna_pack import (
    PrashnaQuestionProfile,
    PrashnaQuestionRoute,
    PrashnaRenderedReport,
    PrashnaRadicalityInput,
    PrashnaRadicalityProfile,
    build_prashna_baseline_testimonies,
    classify_prashna_question,
    evaluate_prashna_baseline_geometry,
    evaluate_prashna_outcome,
    evaluate_prashna_radicality,
    load_prashna_baseline_rule_pack,
    render_prashna_outcome,
)


@dataclass(frozen=True)
class PrashnaFullExecution:
    status: Literal["completed", "unavailable", "needs_input", "incomplete"]
    profile: PrashnaQuestionProfile | None
    report: PrashnaRenderedReport | None
    reason_code: str | None = None


def _base_request(value: PrashnaRequest) -> PrashnaRequest:
    payload = value.model_dump(
        mode="json",
        exclude={"mode", "locale", "include_evidence"},
        exclude_computed_fields=True,
    )
    payload["include_trace"] = False
    return PrashnaRequest.model_validate(payload)


def _calculation_route(
    question: str,
) -> tuple[PrashnaQuestionRoute, TopicRoute | None]:
    route = classify_prashna_question(question)
    if route.status != "supported" or route.profile is None:
        return route, None
    return route, TopicRoute(
        status="supported",
        family=route.profile.value,
        primary_house=route.primary_house,
        secondary_houses=route.secondary_houses,
    )


def execute_prashna_full(
    value: PrashnaRequest,
    *,
    locale: Literal["ru", "en"],
    mode: Literal["quick", "full", "deep", "inspection"],
    include_evidence: bool,
    clock: Callable[[], dt.datetime] | None = None,
) -> PrashnaFullExecution:
    """Run the immutable baseline without selecting the unreviewed Tajika overlay."""

    route, calculation_route = _calculation_route(value.question)
    if route.status == "high_stakes":
        return PrashnaFullExecution(
            status="unavailable",
            profile=None,
            report=None,
            reason_code="HIGH_STAKES_TOPIC",
        )
    if route.status != "supported" or calculation_route is None:
        reason = {
            "composite": "TOPIC_COMPOSITE",
            "ambiguous": "TOPIC_AMBIGUOUS",
            "unsupported": "TOPIC_UNSUPPORTED",
        }.get(route.status, "TOPIC_UNSUPPORTED")
        return PrashnaFullExecution(
            status="needs_input",
            profile=None,
            report=None,
            reason_code=reason,
        )

    base = PrashnaFacade(clock=clock).calculate(
        _base_request(value),
        route_override=calculation_route,
    )
    if base.status != "completed":
        return PrashnaFullExecution(
            status="incomplete" if base.status == "incomplete" else base.status,
            profile=route.profile,
            report=None,
            reason_code=getattr(base, "error_code", "BASE_CALCULATION_UNAVAILABLE"),
        )
    assert isinstance(base, PrashnaCompletedResult)

    radicality_profile = PrashnaRadicalityProfile.model_validate_json(
        (
            Path(__file__).resolve().parents[1]
            / "data/doctrine/prashna-rules.json"
        ).read_text(encoding="utf-8")
    )
    radicality = evaluate_prashna_radicality(
        PrashnaRadicalityInput(
            anchor_state="sealed",
            question_relation=base.question_relation,
            topic_state="single_safe",
            question_form="proper",
            intent_state="sincere",
            sources_admitted=True,
        ),
        radicality_profile,
    )
    pack = load_prashna_baseline_rule_pack()
    geometry = evaluate_prashna_baseline_geometry(base.facts, route, pack)
    testimonies = build_prashna_baseline_testimonies(
        base.facts,
        route,
        geometry,
        pack,
    )
    graph = evaluate_prashna_outcome(
        radicality,
        route,
        geometry,
        testimonies=testimonies,
        available_fact_paths=tuple(fact.fact_id for fact in base.facts),
    )
    report = render_prashna_outcome(
        graph,
        language=locale,
        depth="deep" if mode == "inspection" else mode,
        include_evidence=include_evidence,
    )
    if report.status != "completed":
        return PrashnaFullExecution(
            status="unavailable",
            profile=route.profile,
            report=None,
            reason_code=report.reason_code or "OUTCOME_UNAVAILABLE",
        )
    return PrashnaFullExecution(
        status="completed",
        profile=route.profile,
        report=report,
    )
