"""Frozen fixture loading and integrity checks for human-reviewed evaluations."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from .hardening import atomic_write_private


REQUIRED_CATEGORIES = {
    "unsafe",
    "missing_input",
    "claim_evidence",
    "timezone_boundary",
    "retrieval_conflict",
    "race_restart",
    "replay",
    "oracle_comparison",
}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path.name}:{line_no}: case must be an object")
        cases.append(value)
    return cases


def load_fixture_sets(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load physically separate tuning and held-out regression cases."""
    return _load_jsonl(root / "tuning.jsonl"), _load_jsonl(root / "held-out.jsonl")


def validate_fixture_corpus(
    tuning: list[dict[str, Any]], held_out: list[dict[str, Any]]
) -> dict[str, int]:
    """Fail closed when the frozen 40/20 split or fixture schema drifts."""
    if len(tuning) != 40 or len(held_out) != 20:
        raise ValueError("frozen evaluation split must remain 40 tuning / 20 held-out")
    tuning_ids = {case.get("id") for case in tuning}
    held_out_ids = {case.get("id") for case in held_out}
    if len(tuning_ids) != 40 or len(held_out_ids) != 20 or tuning_ids & held_out_ids:
        raise ValueError("held-out leakage or duplicate fixture IDs detected")
    all_cases = tuning + held_out
    profiles = {case.get("profile_id") for case in all_cases}
    if None in profiles or len(profiles) != 10:
        raise ValueError("evaluation corpus must use exactly 10 named profiles")
    for case in all_cases:
        required = {"id", "profile_id", "category", "prompt", "expected", "oracle"}
        if set(case) != required:
            raise ValueError(f"fixture {case.get('id')} has an invalid schema")
        oracle = case["oracle"]
        if not isinstance(oracle, dict) or not oracle.get("provenance"):
            raise ValueError(f"fixture {case['id']} lacks oracle provenance")
        if oracle.get("status") == "placeholder" and oracle.get("expected") is not None:
            raise ValueError(f"fixture {case['id']} invents a placeholder oracle value")
    if not REQUIRED_CATEGORIES <= {case["category"] for case in all_cases}:
        raise ValueError("evaluation corpus is missing a required failure category")
    return {"cases": 60, "profiles": 10, "tuning": 40, "held_out": 20}


def record_human_adjudication(
    output: Path,
    *,
    case_id: str,
    reviewer: str,
    scores: dict[str, int],
    material_rewrite: bool,
    evidence: str,
) -> None:
    """Persist one private human decision using the published rubric."""
    if not reviewer.startswith("human:") or len(reviewer) <= len("human:"):
        raise ValueError("a named human reviewer is required; models cannot be sole judge")
    dimensions = {
        "relevance",
        "depth",
        "clarity",
        "traceability",
        "actionability",
        "unsupported_claims",
        "timings",
    }
    if set(scores) != dimensions or any(
        isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 3
        for score in scores.values()
    ):
        raise ValueError("scores must contain every rubric dimension on a 0-3 scale")
    passed = (
        scores["unsupported_claims"] == 3
        and scores["traceability"] >= 2
        and not material_rewrite
        and min(scores.values()) >= 2
    )
    record = {
        "schema_version": "1.0",
        "case_id": case_id,
        "reviewer": reviewer,
        "reviewed_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "scores": scores,
        "material_rewrite": material_rewrite,
        "evidence": evidence,
        "decision": "pass" if passed else "fail",
    }
    atomic_write_private(
        Path(output),
        (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"),
    )
