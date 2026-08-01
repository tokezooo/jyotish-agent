#!/usr/bin/env python3
"""Aggregate a private opt-in concierge dataset into a privacy-safe report."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from jyotish_agent.doctrine.concierge import (
    ConciergeDataset,
    evaluate_concierge_dataset,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="return exit 2 until the 10-20 session cross-domain gate is ready",
    )
    args = parser.parse_args(argv)
    try:
        dataset = ConciergeDataset.model_validate_json(
            args.input.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, ValidationError):
        print("CONCIERGE_INPUT_INVALID", file=sys.stderr)
        return 1

    report = evaluate_concierge_dataset(dataset)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    if args.require_ready and not report.ready_for_release_gate:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
