#!/usr/bin/env python3
"""Generate deterministic doctrine admission JSON and Markdown from a gate payload."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from jyotish_agent.doctrine.evaluation import (
    AdmissionEvaluator,
    GateResult,
    QualityMetrics,
    ReviewerDecision,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--markdown-out", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    report = AdmissionEvaluator.evaluate(
        profile_id=payload["profile_id"],
        compiled_profile_sha256=payload["compiled_profile_sha256"],
        source_manifest_sha256=payload["source_manifest_sha256"],
        evidence_store_sha256=payload["evidence_store_sha256"],
        gates=tuple(GateResult.model_validate(item) for item in payload.get("gates", [])),
        metrics=QualityMetrics.model_validate(payload["metrics"]),
        reviewer_decisions=tuple(
            ReviewerDecision.model_validate(item)
            for item in payload.get("reviewer_decisions", [])
        ),
    )
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    args.markdown_out.write_text(
        AdmissionEvaluator.render_dashboard(report), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
