#!/usr/bin/env python3
"""Warm local benchmark for the three additive domains; emits privacy-safe JSON."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import io
import json
import math
import platform
import statistics
import time
from collections.abc import Callable

def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def _measure(name: str, runs: int, call: Callable[[], object]) -> tuple[dict, object]:
    with contextlib.redirect_stdout(io.StringIO()):
        call()
    samples: list[float] = []
    result: object = None
    for _ in range(runs):
        started = time.perf_counter()
        with contextlib.redirect_stdout(io.StringIO()):
            result = call()
        samples.append((time.perf_counter() - started) * 1_000)
    assert result is not None and hasattr(result, "model_dump_json")
    payload = result.model_dump_json().encode()  # type: ignore[union-attr]
    provenance = getattr(result, "provenance", None)
    return ({
        "case": name,
        "runs": runs,
        "p50_ms": round(statistics.median(samples), 3),
        "p95_ms": round(_percentile(samples, 0.95), 3),
        "payload_bytes": len(payload),
        "status": getattr(result, "status"),
        "ephemeris_mode": getattr(provenance, "ephemeris_mode"),
        "source_status": getattr(provenance, "source_review_status", "pending"),
    }, result)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.runs <= 30:
        parser.error("--runs must be in 1..30")

    # PyJHora prints import diagnostics. They are neither benchmark data nor safe
    # machine output, so capture them before importing the domain facades.
    with contextlib.redirect_stdout(io.StringIO()):
        from jyotish_agent.jaimini import JaiminiFacade
        from jyotish_agent.jaimini_models import JaiminiInput
        from jyotish_agent.muhurta import MuhurtaFacade
        from jyotish_agent.muhurta_models import MuhurtaSearchRequest
        from jyotish_agent.prashna import PrashnaFacade
        from jyotish_agent.prashna_models import PrashnaCompletedResult, PrashnaRequest

    place = {"name": "private", "latitude": 55.7558, "longitude": 37.6173, "timezone": "Europe/Moscow"}
    base = {
        "profile": "private",
        "rule_profile": "jaimini_core_v1",
        "analysis_scope": "core_with_chara_dasha",
        "gender": "male",
        "reference_date": "2026-07-14",
    }
    jaimini = JaiminiFacade()
    j_exact = JaiminiInput.model_validate({**base, "birth": {"confidence": "exact", "date": "1990-01-15", "time": "10:30:00", "place": place}})
    j_approx = JaiminiInput.model_validate({**base, "birth": {"confidence": "approximate", "date": "1990-01-15", "earliest_time": "10:25:00", "latest_time": "10:35:00", "place": place}})

    event_place = {"name": "private", "latitude": 55.7558, "longitude": 37.6173, "zone_id": "Europe/Moscow"}
    p_explicit = PrashnaRequest.model_validate({
        "question": "What blocks this work project now?",
        "anchor": {"asked_at": "2026-07-14T12:00:00+03:00", "place": event_place},
    })
    prashna_explicit = PrashnaFacade(clock=lambda: dt.datetime(2026, 7, 14, 9, tzinfo=dt.UTC))
    prashna_capture = PrashnaFacade(clock=lambda: dt.datetime(2026, 7, 14, 9, tzinfo=dt.UTC))
    p_capture = PrashnaRequest.model_validate({
        "question": "What blocks this work project now?", "capture_now": True,
        "place": event_place, "idempotency_key": "task7-benchmark-capture",
    })
    with contextlib.redirect_stdout(io.StringIO()):
        captured = prashna_capture.calculate(p_capture)
    assert isinstance(captured, PrashnaCompletedResult)
    p_replay = PrashnaRequest.model_validate({
        "question": "What blocks this work project now?", "anchor_token": captured.anchor_token,
    })
    capture_sequence = 0

    def fresh_capture():
        nonlocal capture_sequence
        capture_sequence += 1
        request = PrashnaRequest.model_validate({
            "question": "What blocks this work project now?", "capture_now": True,
            "place": event_place,
            "idempotency_key": f"task7-benchmark-capture-{capture_sequence:04d}",
        })
        return PrashnaFacade(
            clock=lambda: dt.datetime(2026, 7, 14, 9, tzinfo=dt.UTC)
        ).calculate(request)

    muhurta = MuhurtaFacade()
    m_one_day = MuhurtaSearchRequest.model_validate({
        "activity": "focused_work_session_v1", "place": event_place,
        "start": "2026-07-15T00:00:00+03:00", "end": "2026-07-16T00:00:00+03:00",
        "duration_minutes": 90, "hard_constraints": {"require_daylight": True},
    })

    cases: list[dict] = []
    cases.append(_measure("jaimini_exact", args.runs, lambda: jaimini.calculate(j_exact))[0])
    cases.append(_measure("jaimini_approximate", args.runs, lambda: jaimini.calculate(j_approx))[0])
    cases.append(_measure("prashna_explicit", args.runs, lambda: prashna_explicit.calculate(p_explicit))[0])
    cases.append(_measure("prashna_capture", args.runs, fresh_capture)[0])
    cases.append(_measure("prashna_replay", args.runs, lambda: prashna_capture.calculate(p_replay))[0])
    cases.append(_measure("muhurta_one_day", args.runs, lambda: muhurta.search(m_one_day))[0])
    print(json.dumps({
        "schema_version": 1,
        "runner": "scripts/benchmark_domains.py",
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "ephemeris": sorted({case["ephemeris_mode"] for case in cases}),
        },
        "input_bounds": {
            "jaimini_approximate_minutes": 10,
            "prashna_capture_cache_scope": "process_local",
            "muhurta_days": 1,
        },
        "interpretation_gate": "pending",
        "note": "Local warm evidence, not a universal SLO.",
        "cases": cases,
    }, ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    main()
