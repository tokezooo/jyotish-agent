"""RFC 7807 problem+json responses.

Every error the API returns is a problem document with the standard members
(type, title, status, detail) plus three extension members the product mandates so
a failure is actionable, not just classified:

    problem - what went wrong, in one line
    cause   - why it happened
    fix     - what the caller should do about it

Birth data is never echoed into error bodies (privacy); only field locations and the
rule that failed are reported.
"""

from __future__ import annotations

import sqlite3
import re

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .error_registry import error_record
from .research_store import CorpusIntegrityError

PROBLEM_JSON = "application/problem+json"
_PROBLEM_BASE = "https://jyotish-agent.local/problems"


def request_run_context(request: Request) -> tuple[str | None, str]:
    match = re.search(
        r"/v2/research-runs/(rr_[0-9a-f-]+)(?:/([^/]+))?", request.url.path
    )
    if not match:
        stage = "create" if request.url.path.rstrip("/").endswith("research-runs") else "request"
        return None, stage
    stage = {
        "screen": "screen", "plan": "plan", "calculate": "calculate",
        "retrieve": "retrieve", "answers": "answer", "replay": "replay",
    }.get(match.group(2), "inspect")
    return match.group(1), stage


def problem_response(
    status: int,
    title: str,
    problem: str,
    cause: str,
    fix: str,
    problem_type: str = "about:blank",
    extra: dict | None = None,
) -> JSONResponse:
    body = {
        "type": f"{_PROBLEM_BASE}/{problem_type}" if problem_type != "about:blank" else problem_type,
        "title": title,
        "status": status,
        # `detail` is the RFC 7807 standard member; `problem`/`cause`/`fix` are the
        # product's actionable triad. `detail` == `problem` by design (RFC compliance
        # plus the triad), not an accident.
        "detail": problem,
        "problem": problem,
        "cause": cause,
        "fix": fix,
        "error_code": (
            "UNEXPECTED_INTERNAL"
            if status >= 500
            else problem_type.replace("-", "_").upper()
        ),
        "run_id": None,
        "stage": "request",
        "retryable": status >= 500,
    }
    if extra:
        body.update(extra)
    return JSONResponse(status_code=status, content=body, media_type=PROBLEM_JSON)


def registry_problem_response(
    error_code: str,
    *,
    status: int,
    run_id: str | None,
    stage: str,
    title: str,
) -> JSONResponse:
    record = error_record(error_code, run_id=run_id, stage=stage)
    return JSONResponse(
        status_code=status,
        media_type=PROBLEM_JSON,
        content={
            "type": f"{_PROBLEM_BASE}/{error_code.lower().replace('_', '-')}",
            "title": title,
            "status": status,
            "detail": record["problem"],
            **record,
        },
    )


class CalculationError(ValueError):
    """A request was structurally valid but the engine rejected its parameters
    (e.g. an unknown or Moshier-unsafe ayanamsa). Maps to 422."""


def _loc(err: dict) -> str:
    # Drop the leading 'body' element; join the rest as a dotted field path.
    # For an unexpected (extra) field the offending key IS in loc and could carry
    # client-chosen text, so report a generic label instead of reflecting it.
    if err.get("type") == "extra_forbidden":
        return "(unexpected field)"
    parts = [str(p) for p in err.get("loc", []) if p != "body"]
    return ".".join(parts) or "(root)"


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(sqlite3.OperationalError)
    async def _sqlite_handler(request: Request, exc: sqlite3.OperationalError):
        run_id, stage = request_run_context(request)
        message = str(exc).lower()
        if "locked" in message or "busy" in message:
            return registry_problem_response(
                "SQLITE_BUSY", status=503, run_id=run_id, stage=stage,
                title="Research ledger busy",
            )
        return registry_problem_response(
            "UNEXPECTED_INTERNAL", status=500, run_id=run_id, stage=stage,
            title="Internal error",
        )

    @app.exception_handler(CorpusIntegrityError)
    async def _corpus_integrity_handler(request: Request, exc: CorpusIntegrityError):
        run_id, stage = request_run_context(request)
        return registry_problem_response(
            "CORPUS_INTEGRITY_ERROR", status=409, run_id=run_id, stage=stage,
            title="Corpus integrity failure",
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError):
        run_id, stage = request_run_context(request)
        body = exc.body if isinstance(exc.body, dict) else {}
        answer = body.get("answer") if isinstance(body, dict) else None
        schema_version = answer.get("schema_version") if isinstance(answer, dict) else None
        if (
            request.url.path.startswith("/v2/research-runs/")
            and request.url.path.endswith("/answers")
            and isinstance(schema_version, str)
            and schema_version.split(".", 1)[0] != "2"
        ):
            return registry_problem_response(
                "UNSUPPORTED_SCHEMA_VERSION",
                status=422,
                run_id=run_id,
                stage=stage,
                title="Unsupported answer schema version",
            )
        if run_id is not None:
            return registry_problem_response(
                "INPUT_INVALID", status=422, run_id=run_id, stage=stage,
                title="Invalid run operation payload",
            )
        # Report field locations and rule messages, NOT the submitted values.
        fields = sorted({_loc(e) for e in exc.errors()})
        messages = [f"{_loc(e)}: {e.get('msg', 'invalid')}" for e in exc.errors()]
        return problem_response(
            status=422,
            title="Invalid birth data",
            problem="One or more request fields are invalid or missing.",
            cause="; ".join(messages),
            fix=(
                "Correct these fields and resubmit: "
                + ", ".join(fields)
                + ". Provide a valid calendar date/time, explicit "
                "latitude/longitude, and a timezone offset in hours."
            ),
            problem_type="invalid-birth-data",
            extra={"invalid_fields": fields},
        )

    @app.exception_handler(CalculationError)
    async def _calc_handler(request: Request, exc: CalculationError):
        return problem_response(
            status=422,
            title="Calculation parameter rejected",
            problem=str(exc),
            cause="The engine rejected a calculation parameter.",
            fix="Use a supported ayanamsa (e.g. LAHIRI) and node mode "
            "('true_nodes' or 'mean_nodes').",
            problem_type="calculation-parameter-rejected",
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception):
        # Catch-all so 500s also speak problem+json and NEVER leak internals or
        # birth-derived data. No detail from the exception is included.
        run_id, stage = request_run_context(request)
        return registry_problem_response(
            "UNEXPECTED_INTERNAL", status=500, run_id=run_id, stage=stage,
            title="Internal error",
        )
