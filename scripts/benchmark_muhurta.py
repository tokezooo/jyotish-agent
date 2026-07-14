#!/usr/bin/env python3
"""Reproducible warm one-day Muhūrta benchmark; emits one JSON record."""

from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import time

from jyotish_agent.muhurta import MuhurtaFacade
from jyotish_agent.muhurta_models import MuhurtaCompletedResult, MuhurtaSearchRequest
from jyotish_agent.muhurta_profiles import load_muhurta_rule_profile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.runs <= 100:
        parser.error("--runs must be in 1..100")
    request = MuhurtaSearchRequest.model_validate({
        "activity": "focused_work_session_v1",
        "place": {"name": "private", "latitude": 55.7558, "longitude": 37.6173, "zone_id": "Europe/Moscow"},
        "start": "2026-07-15T00:00:00+03:00",
        "end": "2026-07-16T00:00:00+03:00",
        "duration_minutes": 90,
        "hard_constraints": {"require_daylight": True},
    })
    facade = MuhurtaFacade()
    rule_profile = load_muhurta_rule_profile()
    facade.search(request)  # warm imports/caches
    samples: list[float] = []
    result = None
    for _ in range(args.runs):
        started = time.perf_counter()
        result = facade.search(request)
        samples.append((time.perf_counter() - started) * 1000)
    assert isinstance(result, MuhurtaCompletedResult)
    ordered = sorted(samples)
    p95 = ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]
    print(json.dumps({
        "case": "one_day_moscow_focused_work_90m",
        "runner": "scripts/benchmark_muhurta.py",
        "python": platform.python_version(),
        "warm_runs": args.runs,
        "p50_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(p95, 3),
        "min_ms": round(ordered[0], 3),
        "max_ms": round(ordered[-1], 3),
        "candidate_intervals": result.total_candidate_intervals,
        "result_bytes": len(result.model_dump_json().encode()),
        "ephemeris_mode": result.provenance.ephemeris_mode,
        "config_sha256": result.provenance.config_sha256,
        "rule_profile_sha256": result.provenance.rule_profile_sha256,
        "transition_canonicalization_version": (
            rule_profile.transition_canonicalization.version
        ),
        "transition_cluster_tolerance_seconds": (
            rule_profile.transition_canonicalization.tolerance_seconds
        ),
        "source_map_sha256": result.provenance.source_map_sha256,
        "source_gate": result.provenance.source_review_status,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
