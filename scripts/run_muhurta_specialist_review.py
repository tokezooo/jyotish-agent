#!/usr/bin/env python3
"""Generate and evaluate the source-bound Muhurta specialist-review handoff."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ValidationError

from jyotish_agent.doctrine.specialist_review import (
    MuhurtaSpecialistReviewHandoff,
    MuhurtaSpecialistReviewResponse,
    build_muhurta_specialist_review_handoff,
    evaluate_muhurta_specialist_review,
    muhurta_specialist_review_response_schema,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    handoff = commands.add_parser("handoff")
    handoff.add_argument("--json-out", type=Path, required=True)

    schema = commands.add_parser("response-schema")
    schema.add_argument("--json-out", type=Path, required=True)

    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("handoff", type=Path)
    evaluate.add_argument("response", type=Path)
    evaluate.add_argument("--json-out", type=Path, required=True)
    evaluate.add_argument(
        "--require-approved",
        action="store_true",
        help="return exit 2 for incomplete/amended review and exit 3 for rejection",
    )
    args = parser.parse_args(argv)

    if args.command == "handoff":
        return _write(args.json_out, build_muhurta_specialist_review_handoff())
    if args.command == "response-schema":
        return _write_json(args.json_out, muhurta_specialist_review_response_schema())

    try:
        handoff_value = MuhurtaSpecialistReviewHandoff.model_validate_json(
            args.handoff.read_text(encoding="utf-8")
        )
        response_value = MuhurtaSpecialistReviewResponse.model_validate_json(
            args.response.read_text(encoding="utf-8")
        )
        report = evaluate_muhurta_specialist_review(handoff_value, response_value)
    except (OSError, UnicodeError, ValidationError, ValueError):
        print("SPECIALIST_REVIEW_INPUT_INVALID", file=sys.stderr)
        return 1
    result = _write(args.json_out, report)
    if result != 0 or not args.require_approved:
        return result
    if report.gate_status == "failed":
        return 3
    if report.gate_status == "missing":
        return 2
    return 0


def _write(path: Path, value: BaseModel) -> int:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value.model_dump_json(indent=2) + "\n", encoding="utf-8")
    except (OSError, UnicodeError):
        print("SPECIALIST_REVIEW_OUTPUT_INVALID", file=sys.stderr)
        return 1
    return 0


def _write_json(path: Path, value: object) -> int:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, UnicodeError, TypeError, ValueError):
        print("SPECIALIST_REVIEW_OUTPUT_INVALID", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
