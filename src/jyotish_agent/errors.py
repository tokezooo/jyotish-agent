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

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

PROBLEM_JSON = "application/problem+json"
_PROBLEM_BASE = "https://jyotish-agent.local/problems"


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
    }
    if extra:
        body.update(extra)
    return JSONResponse(status_code=status, content=body, media_type=PROBLEM_JSON)


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
    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError):
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
        return problem_response(
            status=500,
            title="Internal error",
            problem="An unexpected error occurred while processing the request.",
            cause="Internal engine or server error.",
            fix="Retry; if it persists, report the request shape (not the data).",
            problem_type="internal-error",
        )
