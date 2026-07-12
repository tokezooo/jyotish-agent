"""Declarative, case-ID-independent probes for frozen evaluation fixtures."""

from __future__ import annotations

from typing import Any

from .interpretations import screen_question


def execute_case_probe(
    case: dict[str, Any], profile: dict[str, Any], boundary: str
) -> dict[str, str]:
    """Execute a declared boundary using fixture data, never the case identifier."""
    if case["profile_id"] != profile["id"] or not case["prompt"].strip():
        raise ValueError("fixture did not materialize its profile and prompt")
    if boundary != "safety_screen":
        raise ValueError(f"unsupported automated production boundary: {boundary}")
    outcome = "unsafe_refusal" if screen_question(case["prompt"]) is not None else "safe"
    return {"outcome": outcome}
