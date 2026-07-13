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
import threading
import time
from contextvars import ContextVar

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import ENGINE_VERSION
from .config import ConfigError
from .error_registry import ERROR_REGISTRY
from .errors import (
    CalculationError,
    register_error_handlers,
    registry_problem_response,
    request_run_context,
)
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
    CorpusFragmentsIngestRequest,
    CorpusFragmentsResponse,
    CorpusFragmentResponse,
    CorpusReviewRequest,
    CorpusSourceIngest,
    CorpusSourceResponse,
    CreateResearchRunRequest,
    PlanResearchRunRequest,
    ResearchCalculationResponse,
    ResearchAnswerResponse,
    ResearchEventsResponse,
    ResearchInspectResponse,
    ResearchOperationRequest,
    ResearchPlanResponse,
    ResearchRetrievalResponse,
    ResearchReplayResponse,
    ResearchRunResponse,
    ResearchScreenResponse,
    SubmitAnswerRequest,
    RetrieveResearchRunRequest,
)
from .research_service import (
    InvalidRunTransition,
    ReplayError,
    ResearchService,
    UnsupportedContractVersion,
    UnsupportedTimezoneMode,
)
from .timezone_resolution import TimezoneResolutionError
from .research_store import (
    OptimisticConflict,
    ResearchStore,
    RunNotFound,
    SourceConflict,
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
_RESEARCH_SERVICE_LOCK = threading.Lock()


def _research_service(request: Request) -> ResearchService:
    configured = getattr(request.app.state, "research_service", None)
    if configured is not None:
        return configured
    with _RESEARCH_SERVICE_LOCK:
        configured = getattr(request.app.state, "research_service", None)
        if configured is None:
            configured = ResearchService(ResearchStore(default_data_root()))
            request.app.state.research_service = configured
        return configured


_RUN_CONTEXT: ContextVar[tuple[str | None, str]] = ContextVar(
    "jyotish_run_context", default=(None, "request")
)


def _research_problem(status: int, title: str, problem: str, fix: str) -> JSONResponse:
    run_id, stage = _RUN_CONTEXT.get()
    error_code = (
        "RUN_NOT_FOUND"
        if status == 404
        else "UNSUPPORTED_TIMEZONE"
        if status == 422 and "timezone" in title.lower()
        else "OPERATION_CONFLICT"
        if status == 409
        else "UNEXPECTED_INTERNAL"
    )
    if error_code in ERROR_REGISTRY:
        return registry_problem_response(
            error_code, status=status, run_id=run_id, stage=stage, title=title
        )
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
            "error_code": f"RESEARCH_RUN_{status}",
            "run_id": None,
            "stage": "research_run",
            "retryable": status >= 500,
        },
    )


@app.middleware("http")
async def _access_log(request: Request, call_next):
    context_token = _RUN_CONTEXT.set(request_run_context(request))
    start = time.monotonic()
    status = 500  # if call_next raises, we still log the failure as a 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        _RUN_CONTEXT.reset(context_token)
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
    return {
        "status": "ok",
        "engine_version": ENGINE_VERSION,
        "research_api_version": "2.0",
    }


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
    except UnsupportedContractVersion:
        return registry_problem_response(
            "UNSUPPORTED_CONTRACT_VERSION", status=422, run_id=None,
            stage="create", title="Unsupported answer contract",
        )
    except TimezoneResolutionError as exc:
        response = _research_problem(
            422, "Timezone resolution failed", exc.error_code,
            "Correct the civil time, fold, zone ID, or asserted offset and retry.",
        )
        body = bytes(response.body)
        import json as _json
        content = _json.loads(body)
        content["error_code"] = exc.error_code
        return JSONResponse(status_code=422, media_type="application/problem+json", content=content)


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


@app.get("/v2/research-runs/{run_id}/inspect", response_model=ResearchInspectResponse)
async def inspect_research_run(
    run_id: str, request: Request
) -> ResearchInspectResponse | JSONResponse:
    try:
        return _research_service(request).inspect_run(run_id)
    except RunNotFound:
        return _research_problem(
            404, "Research run not found", "No persisted research run has that ID.",
            "Check the rr_ run ID and retry.",
        )


@app.post("/v2/research-runs/{run_id}/replay", response_model=ResearchReplayResponse)
async def replay_research_run(run_id: str, request: Request):
    try:
        return _research_service(request).replay_run(run_id)
    except RunNotFound:
        return _research_problem(404, "Research run not found",
                                 "No persisted research run has that ID.",
                                 "Check the rr_ run ID and retry.")
    except ReplayError as exc:
        if exc.error_code in {"MISSING_PINNED_VERSION", "MEMO_HASH_MISMATCH"}:
            return registry_problem_response(
                exc.error_code, status=409, run_id=run_id, stage="replay",
                title="Offline replay failed",
            )
        problem = _research_problem(
            409, "Offline replay failed", exc.error_code,
            "Restore the pinned ledger material/version and retry.",
        )
        import json as _json
        content = _json.loads(problem.body)
        content["error_code"] = exc.error_code
        content["run_id"] = run_id
        return JSONResponse(status_code=409, media_type="application/problem+json", content=content)


@app.post(
    "/v2/research-runs/{run_id}/screen", response_model=ResearchScreenResponse
)
async def screen_research_run(
    run_id: str, req: ResearchOperationRequest, request: Request
) -> ResearchScreenResponse | JSONResponse:
    try:
        return _research_service(request).screen_run(run_id, req)
    except RunNotFound:
        return _research_problem(
            404, "Research run not found", "No persisted research run has that ID.",
            "Check the rr_ run ID and retry.",
        )
    except (OptimisticConflict, InvalidRunTransition):
        return _research_problem(
            409, "Research operation conflict",
            "The operation is stale, duplicated with changed input, or invalid in this state.",
            "Refresh the run, use its current revision, and keep one operation ID per request.",
        )


@app.post("/v2/research-runs/{run_id}/plan", response_model=ResearchPlanResponse)
async def plan_research_run(
    run_id: str, req: PlanResearchRunRequest, request: Request
) -> ResearchPlanResponse | JSONResponse:
    try:
        return _research_service(request).plan_run(run_id, req)
    except RunNotFound:
        return _research_problem(
            404, "Research run not found", "No persisted research run has that ID.",
            "Check the rr_ run ID and retry.",
        )
    except (OptimisticConflict, InvalidRunTransition):
        return _research_problem(
            409, "Research plan conflict",
            "Planning is stale or invalid for the run's current state.",
            "Screen safely, then retry with the current revision and a fresh operation ID.",
        )


@app.post(
    "/v2/research-runs/{run_id}/retrieve", response_model=ResearchRetrievalResponse
)
async def retrieve_research_run(
    run_id: str, req: RetrieveResearchRunRequest, request: Request
) -> ResearchRetrievalResponse | JSONResponse:
    try:
        return _research_service(request).retrieve_run(run_id, req)
    except RunNotFound:
        return _research_problem(
            404, "Research run not found", "No persisted research run has that ID.",
            "Check the rr_ run ID and retry.",
        )
    except (OptimisticConflict, InvalidRunTransition):
        return _research_problem(
            409, "Research retrieval conflict",
            "Retrieval is stale, unsafe, or has no supported plan.",
            "Create a supported plan, then retry with the current revision and a fresh operation ID.",
        )


@app.post(
    "/v2/corpus/source-versions", status_code=201, response_model=CorpusSourceResponse
)
async def ingest_corpus_source(
    req: CorpusSourceIngest, request: Request
) -> dict | JSONResponse:
    try:
        return _research_service(request).ingest_source(req)
    except (OptimisticConflict, SourceConflict):
        return _research_problem(
            409, "Corpus source conflict",
            "The source identifier conflicts with persisted provenance.",
            "Use the exact original manifest or a new source-version identifier.",
        )


@app.post(
    "/v2/corpus/source-versions/{source_version_id}/fragments",
    status_code=201,
    response_model=CorpusFragmentsResponse,
)
async def ingest_corpus_fragments(
    source_version_id: str, req: CorpusFragmentsIngestRequest, request: Request
) -> dict | JSONResponse:
    try:
        return _research_service(request).ingest_fragments(source_version_id, req)
    except (OptimisticConflict, SourceConflict):
        return _research_problem(
            409, "Corpus fragment conflict",
            "A fragment checksum, locator, or identifier conflicts with persisted data.",
            "Correct the manifest or create a new immutable source version.",
        )


@app.post(
    "/v2/corpus/source-versions/{source_version_id}/review",
    response_model=CorpusSourceResponse,
)
async def review_corpus_source(
    source_version_id: str, req: CorpusReviewRequest, request: Request
) -> dict | JSONResponse:
    try:
        return _research_service(request).review_source(source_version_id, req)
    except (OptimisticConflict, SourceConflict):
        return _research_problem(
            409, "Corpus source review conflict",
            "The review is stale, conflicts with its operation, manifest, or terminal state.",
            "Refresh the pending source revision or create a new immutable source version.",
        )


@app.post(
    "/v2/corpus/fragments/{fragment_id}/review",
    response_model=CorpusFragmentResponse,
)
async def review_corpus_fragment(
    fragment_id: str, req: CorpusReviewRequest, request: Request
) -> dict | JSONResponse:
    try:
        return _research_service(request).review_fragment(fragment_id, req)
    except (OptimisticConflict, SourceConflict):
        return _research_problem(
            409, "Corpus fragment review conflict",
            "The review is stale, conflicts with its operation, parent approval, or terminal state.",
            "Refresh the pending fragment revision or create a new immutable source version.",
        )


@app.post(
    "/v2/research-runs/{run_id}/calculate", response_model=ResearchCalculationResponse
)
async def calculate_research_run(
    run_id: str, req: ResearchOperationRequest, request: Request
) -> ResearchCalculationResponse | JSONResponse:
    try:
        return _research_service(request).calculate_run(run_id, req)
    except RunNotFound:
        return _research_problem(
            404, "Research run not found", "No persisted research run has that ID.",
            "Check the rr_ run ID and retry.",
        )
    except (OptimisticConflict, InvalidRunTransition):
        return _research_problem(
            409, "Research operation conflict",
            "Calculation is stale or invalid for the run's current state.",
            "Create a supported deterministic plan, then retry with the current revision and a fresh operation ID.",
        )
    except ConfigError as exc:
        raise CalculationError(str(exc)) from exc
    except TimezoneResolutionError as exc:
        problem = _research_problem(
            422, "Timezone resolution failed", exc.error_code,
            "Restore pinned timezone material or correct the civil time/fold.",
        )
        import json as _json
        content = _json.loads(problem.body)
        content["error_code"] = exc.error_code
        return JSONResponse(status_code=422, media_type="application/problem+json", content=content)


@app.post(
    "/v2/research-runs/{run_id}/answers", response_model=ResearchAnswerResponse
)
async def submit_research_answer(
    run_id: str, req: SubmitAnswerRequest, request: Request
) -> ResearchAnswerResponse | JSONResponse:
    try:
        return _research_service(request).submit_answer(run_id, req)
    except RunNotFound:
        return _research_problem(
            404,
            "Research run not found",
            "No persisted research run has that ID.",
            "Check the rr_ run ID and retry.",
        )
    except (OptimisticConflict, InvalidRunTransition):
        return _research_problem(
            409,
            "Research answer conflict",
            "The answer is stale, changed under a reused operation ID, or the repair budget is exhausted.",
            "Refresh the run and retry once with the current revision and a fresh operation ID.",
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
