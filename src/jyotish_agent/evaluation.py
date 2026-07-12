"""Frozen fixture loading and integrity checks for human-reviewed evaluations."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from .hardening import atomic_write_private
from .evaluation_probes import execute_case_probe


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


def validate_fixture_checksums(root: Path, *, split: str | None = None) -> dict[str, Any]:
    if split is not None and split not in {"tuning", "held-out"}:
        raise ValueError("split must be tuning or held-out")
    names = [f"{split}-checksums.json"] if split else [
        "tuning-checksums.json", "held-out-checksums.json"
    ]
    manifests = [json.loads((root / name).read_text(encoding="utf-8")) for name in names]
    checked: set[str] = set()
    for manifest in manifests:
        if manifest.get("algorithm") != "sha256" or not isinstance(manifest.get("files"), dict):
            raise ValueError("invalid fixture checksum manifest")
        for relative, expected in manifest["files"].items():
            path = root / relative
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError(f"fixture checksum mismatch: {relative}")
            checked.add(relative)
    return {"files": len(checked), "algorithm": "sha256"}


def run_fixture_specs(
    root: Path, *, split: str, execute: bool = True, allow_held_out: bool = False
) -> dict[str, int]:
    if split not in {"tuning", "held-out"}:
        raise ValueError("split must be tuning or held-out")
    if split == "held-out" and not allow_held_out:
        raise ValueError("held-out execution requires an explicit final-review gate")
    validate_fixture_checksums(root, split=split)
    filename = "tuning.jsonl" if split == "tuning" else "held-out.jsonl"
    cases = _load_jsonl(root / filename)
    specs_name = "tuning-specs.json" if split == "tuning" else "held-out-specs.json"
    specs_doc = json.loads((root / specs_name).read_text(encoding="utf-8"))
    groups = specs_doc.get("groups")
    if not isinstance(groups, list):
        raise ValueError("fixture specs must contain groups")
    by_id: dict[str, dict[str, Any]] = {}
    for group in groups:
        if set(group) != {"case_ids", "boundary", "scenario", "assertion", "mode"}:
            raise ValueError("fixture spec group has an invalid schema")
        for case_id in group["case_ids"]:
            if case_id in by_id:
                raise ValueError(f"duplicate fixture spec: {case_id}")
            by_id[case_id] = group
    if set(by_id) != {case["id"] for case in cases}:
        raise ValueError("fixture specs must cover only the selected split")
    profiles_doc = json.loads((root / "profiles.json").read_text(encoding="utf-8"))
    profiles = {profile["id"]: profile for profile in profiles_doc["profiles"]}
    automated = manual = 0
    for case in cases:
        spec = by_id[case["id"]]
        if spec["mode"] == "manual_not_scored":
            if (
                spec["boundary"] is not None
                or spec["scenario"] is not None
                or not spec["assertion"].get("reason")
            ):
                raise ValueError(f"manual fixture {case['id']} lacks a not-scored reason")
            manual += 1
            continue
        if spec["mode"] != "automated":
            raise ValueError(f"fixture {case['id']} has an invalid mode")
        boundary = spec["boundary"]
        if not isinstance(boundary, str) or not boundary:
            raise ValueError(f"fixture {case['id']} lacks a production boundary")
        if spec["scenario"] != {
            "input": "case.prompt", "profile": "case.profile_id", "action": boundary
        } and not (
            boundary == "safety_screen"
            and spec["scenario"] == {
                "input": "case.prompt", "profile": "case.profile_id", "action": "screen_question"
            }
        ):
            raise ValueError(f"fixture {case['id']} lacks an explicit scenario")
        if spec["assertion"] != {"equals": "case.expected"}:
            raise ValueError(f"fixture {case['id']} lacks an exact outcome assertion")
        automated += 1
        if execute:
            observed = execute_case_probe(case, profiles[case["profile_id"]], boundary)
            if observed != case["expected"]:
                raise RuntimeError(
                    f"fixture {case['id']} failed: expected {case['expected']!r}, "
                    f"observed {observed!r}"
                )
    return {"total": len(cases), "automated": automated, "manual_not_scored": manual}


def validate_fixture_spec_coverage(root: Path) -> dict[str, int]:
    """Explicit maintainer gate that may inspect both frozen splits."""
    tuning, held_out = load_fixture_sets(root)
    docs = [
        json.loads((root / "tuning-specs.json").read_text(encoding="utf-8")),
        json.loads((root / "held-out-specs.json").read_text(encoding="utf-8")),
    ]
    listed = [case_id for doc in docs for group in doc["groups"] for case_id in group["case_ids"]]
    expected = {case["id"] for case in tuning + held_out}
    if len(listed) != 60 or len(set(listed)) != 60 or set(listed) != expected:
        raise ValueError("fixture specs must cover all 60 cases exactly")
    return {"cases": 60, "groups": sum(len(doc["groups"]) for doc in docs)}


def _main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run frozen Jyotish evaluation specs")
    parser.add_argument("split", choices=("tuning", "held-out"))
    parser.add_argument("--allow-held-out", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)
    result = run_fixture_specs(
        Path(__file__).resolve().parents[2] / "eval" / "fixtures",
        split=args.split,
        execute=not args.validate_only,
        allow_held_out=args.allow_held_out,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))


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
    run_id: str,
    runtime_versions: dict[str, str],
    duration_ms: int,
    artifact_hashes: dict[str, str],
    started_at: str,
    finished_at: str,
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
    if set(runtime_versions) != {"engine", "planner", "corpus", "contract"} or not all(
        isinstance(value, str) and value for value in runtime_versions.values()
    ):
        raise ValueError("all pinned runtime versions are required")
    if not run_id.startswith("rr_") or isinstance(duration_ms, bool) or duration_ms < 0:
        raise ValueError("run_id and non-negative duration_ms are required")
    if not artifact_hashes or any(
        not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
        for value in artifact_hashes.values()
    ):
        raise ValueError("artifact SHA-256 hashes are required")
    for timestamp in (started_at, finished_at):
        dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
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
        "run_id": run_id,
        "runtime_versions": runtime_versions,
        "duration_ms": duration_ms,
        "artifact_hashes": artifact_hashes,
        "started_at": started_at,
        "finished_at": finished_at,
        "decision": "pass" if passed else "fail",
    }
    atomic_write_private(
        Path(output),
        (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"),
    )
