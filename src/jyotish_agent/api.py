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

from . import ENGINE_VERSION
from .config import ConfigError
from .errors import CalculationError, register_error_handlers
from .models import (
    ChartComputeRequest,
    ChartComputeResponse,
    ValidateRequest,
    ValidateResponse,
)
from .pyjhora_facade import compute_chart
from .validation import config_warnings, normalized_profile, profile_warnings

logger = logging.getLogger("jyotish_agent.api")

app = FastAPI(
    title="Jyotish Agent",
    version=ENGINE_VERSION,
    description="Deterministic Vedic-astrology calculations behind typed tools.",
)
register_error_handlers(app)


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

    warnings = profile_warnings(req.birth_profile) + config_warnings(req.config)
    return ChartComputeResponse(
        normalized_input=result["normalized_input"],
        calculation_config=result["calculation_config"],
        facts=result["facts"],
        provenance=result["provenance"],
        warnings=warnings,
    )
