"""Pure, byte-deterministic planning for the supported research family."""

from __future__ import annotations

from .research_models import QuestionIntent, QuestionPlan
from .research_store import canonical_json


def build_question_plan(intent: QuestionIntent) -> QuestionPlan:
    """Map a typed classifier result to a plan without model or clock inputs."""
    if intent.family == "career_factors_and_timing":
        modules = ("shadbala", "transits", "ashtakavarga")
        if intent.explicit_annual_scope:
            modules += ("varshaphal",)
        return QuestionPlan(
            outcome="supported",
            family="career_factors_and_timing",
            explicit_annual_scope=intent.explicit_annual_scope,
            charts=("D1", "D9", "D10"),
            modules=modules,
        )
    if intent.family in {"unknown", "composite"}:
        return QuestionPlan(
            outcome="needs_clarification",
            family=None,
            explicit_annual_scope=False,
            charts=(),
            modules=(),
        )
    return QuestionPlan(
        outcome="unsupported",
        family=None,
        explicit_annual_scope=False,
        charts=(),
        modules=(),
    )


def question_plan_bytes(plan: QuestionPlan) -> bytes:
    """Return the sole canonical byte representation used for plan hashing."""
    return canonical_json(plan.model_dump(mode="json")).encode("utf-8")
