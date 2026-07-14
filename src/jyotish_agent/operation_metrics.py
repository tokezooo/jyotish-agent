"""Pure privacy-safe diagnostics projection for additive domain operations.

The project intentionally has no metrics sink for these local-only stateless tools.
Callers may emit or aggregate this allowlisted projection, but this module never
persists it and never accepts request/result payloads.
"""

from __future__ import annotations

import math
import re
from typing import Literal, TypedDict


Mode = Literal["jaimini", "prashna", "muhurta"]
Status = Literal["completed", "needs_input", "unavailable", "incomplete"]


class OperationMetric(TypedDict):
    schema_version: Literal[1]
    mode: Mode
    status: Status
    duration_bucket: str
    candidate_count: int
    sample_count: int
    result_count: int
    truncated: bool
    error_code: str | None


def _duration_bucket(duration_ms: float) -> str:
    if not math.isfinite(duration_ms) or duration_ms < 0:
        raise ValueError("duration_ms must be finite and non-negative")
    if duration_ms < 100:
        return "under_100ms"
    if duration_ms < 250:
        return "100ms_to_250ms"
    if duration_ms < 500:
        return "250ms_to_500ms"
    if duration_ms < 1_000:
        return "500ms_to_1s"
    if duration_ms < 2_500:
        return "1s_to_2_5s"
    if duration_ms < 5_000:
        return "2_5s_to_5s"
    return "5s_or_more"


def project_operation_metric(
    *,
    mode: Mode,
    status: Status,
    duration_ms: float,
    candidate_count: int = 0,
    sample_count: int = 0,
    result_count: int = 0,
    truncated: bool = False,
    error_code: str | None = None,
) -> OperationMetric:
    """Return only cardinalities and stable labels; no private payload is accepted."""
    if mode not in {"jaimini", "prashna", "muhurta"}:
        raise ValueError("unsupported operation mode")
    if status not in {"completed", "needs_input", "unavailable", "incomplete"}:
        raise ValueError("unsupported operation status")
    counts = (candidate_count, sample_count, result_count)
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts):
        raise ValueError("operation counts must be non-negative integers")
    if error_code is not None and re.fullmatch(r"[A-Z][A-Z0-9_]{1,79}", error_code) is None:
        raise ValueError("error_code must be a stable uppercase code")
    return {
        "schema_version": 1,
        "mode": mode,
        "status": status,
        "duration_bucket": _duration_bucket(duration_ms),
        "candidate_count": candidate_count,
        "sample_count": sample_count,
        "result_count": result_count,
        "truncated": truncated,
        "error_code": error_code,
    }
