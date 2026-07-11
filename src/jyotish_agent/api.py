"""FastAPI application: validate birth data and compute chart facts.

Two endpoints:
    POST /birth-profiles/validate  - normalize a profile, return soft warnings
    POST /charts/compute           - deterministic fact set for the agent to cite

Request logging records method, path, status, and duration only. Birth data and
computed placements are never logged (privacy), and never echoed into error bodies.
"""

from __future__ import annotations

import datetime as _dt
import logging
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import ENGINE_VERSION
from .config import ConfigError
from .errors import CalculationError, register_error_handlers
from .interpretations import redirect_message, screen_question, validate_answer
from .models import (
    ChartComputeRequest,
    ChartComputeResponse,
    ScreenRequest,
    ScreenResponse,
    ValidateAnswerRequest,
    ValidateAnswerResponse,
    ValidateRequest,
    ValidateResponse,
)
from .pyjhora_facade import compute_chart
from .research_models import (
    CreateResearchRunRequest,
    ResearchEventsResponse,
    ResearchRunResponse,
)
from .research_service import ResearchService, UnsupportedTimezoneMode
from .research_store import (
    OptimisticConflict,
    ResearchStore,
    RunNotFound,
    default_data_root,
)
from .signing import cache_facts, get_cached_facts, verify_facts
from .validation import normalized_profile, profile_warnings

logger = logging.getLogger("jyotish_agent.api")

app = FastAPI(
    title="Jyotish Agent",
    version=ENGINE_VERSION,
    description="Deterministic Vedic-astrology calculations behind typed tools.",
)
register_error_handlers(app)


def _research_service(request: Request) -> ResearchService:
    configured = getattr(request.app.state, "research_service", None)
    if configured is not None:
        return configured
    return ResearchService(ResearchStore(default_data_root()))


def _research_problem(status: int, title: str, problem: str, fix: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={
            "type": f"https://jyotish-agent.local/problems/research-run-{status}",
            "title": title,
            "status": status,
            "detail": problem,
            "problem": problem,
            "cause": title,
            "fix": fix,
        },
    )


@app.middleware("http")
async def _access_log(request: Request, call_next):
    start = time.monotonic()
    status = 500  # if call_next raises, we still log the failure as a 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        duration_ms = round((time.monotonic() - start) * 1000, 1)
        # No request/response body: birth data must not reach the logs.
        logger.info(
            "%s %s -> %s (%sms)",
            request.method,
            request.url.path,
            status,
            duration_ms,
        )


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "engine_version": ENGINE_VERSION}


@app.post("/v2/research-runs", response_model=ResearchRunResponse, status_code=201)
async def create_research_run(
    req: CreateResearchRunRequest, request: Request
) -> ResearchRunResponse | JSONResponse:
    try:
        return _research_service(request).create_run(req)
    except OptimisticConflict:
        return _research_problem(
            409,
            "Research operation conflict",
            "The operation ID or expected revision conflicts with persisted state.",
            "Use a new op_ UUID4 for a changed request and the current revision.",
        )
    except UnsupportedTimezoneMode:
        return _research_problem(
            422,
            "Timezone mode is not executable yet",
            "This version cannot resolve the requested timezone mode.",
            "Use fixed_offset_legacy (or a numeric UTC offset) for Task 1.",
        )


@app.get("/v2/research-runs/{run_id}", response_model=ResearchRunResponse)
async def get_research_run(
    run_id: str, request: Request
) -> ResearchRunResponse | JSONResponse:
    try:
        return _research_service(request).get_run(run_id)
    except RunNotFound:
        return _research_problem(
            404,
            "Research run not found",
            "No persisted research run has that ID.",
            "Check the rr_ run ID and retry.",
        )


@app.get("/v2/research-runs/{run_id}/events", response_model=ResearchEventsResponse)
async def get_research_events(
    run_id: str, request: Request
) -> ResearchEventsResponse | JSONResponse:
    try:
        return _research_service(request).get_events(run_id)
    except RunNotFound:
        return _research_problem(
            404,
            "Research run not found",
            "No persisted research run has that ID.",
            "Check the rr_ run ID and retry.",
        )


@app.post("/birth-profiles/validate", response_model=ValidateResponse)
async def validate_birth_profile(req: ValidateRequest) -> ValidateResponse:
    return ValidateResponse(
        normalized_profile=normalized_profile(req),
        warnings=profile_warnings(req),
    )


@app.post("/charts/compute", response_model=ChartComputeResponse)
async def compute(req: ChartComputeRequest) -> ChartComputeResponse:
    profile = req.birth_profile.to_birth_profile()
    config = req.config.to_calculation_config()
    ref_date = req.config.reference_date or _dt.date.today()
    reference = (ref_date.year, ref_date.month, ref_date.day)

    try:
        result = compute_chart(profile, reference_date=reference, config=config)
    except ConfigError as exc:
        # Only known calculation-parameter rejections become a 422. Any other
        # exception (EngineOutputError, internal ValueError, etc.) propagates to the
        # catch-all 500 handler, which never echoes internal/birth-derived detail.
        raise CalculationError(str(exc)) from exc

    warnings = profile_warnings(req.birth_profile)
    return ChartComputeResponse(
        normalized_input=result["normalized_input"],
        calculation_config=result["calculation_config"],
        facts=result["facts"],
        provenance=result["provenance"],
        warnings=warnings,
        facts_token=cache_facts(result["facts"]),
    )


@app.post("/answers/validate", response_model=ValidateAnswerResponse)
async def validate_answer_endpoint(req: ValidateAnswerRequest) -> ValidateAnswerResponse:
    # Resolve facts from the server-side cache by token (the agent passes only the
    # token). Fall back to HMAC-verified client-supplied facts if the token isn't
    # cached (e.g. after a restart). This is what binds validation to real output —
    # the agent can't self-certify against forged facts.
    facts = get_cached_facts(req.facts_token)
    if facts is None:
        if req.facts is not None and verify_facts(req.facts, req.facts_token):
            facts = req.facts
        else:
            return ValidateAnswerResponse(
                valid=False,
                violations=[
                    "facts_token not recognized (and no valid facts fallback). Recompute "
                    "the chart with /charts/compute and pass the returned facts_token."
                ],
            )
    # Then the fact-citation contract: every cited fact must exist with a matching value.
    facts_used = [ref.model_dump() for ref in req.answer.facts_used]
    # Pass the summary so prose placement claims that contradict the facts are caught,
    # not just the explicitly-cited facts_used.
    violations = validate_answer(facts_used, facts, summary=req.answer.summary)
    return ValidateAnswerResponse(valid=not violations, violations=violations)


@app.post("/questions/screen", response_model=ScreenResponse)
async def screen(req: ScreenRequest) -> ScreenResponse:
    # Best-effort keyword screen (English, substring) for domains the agent must
    # refuse/redirect. Advisory: the agent's own judgement via the skill is primary.
    category = screen_question(req.question)
    return ScreenResponse(
        safe=category is None,
        category=category.value if category else None,
        redirect=redirect_message(category) if category else None,
    )
