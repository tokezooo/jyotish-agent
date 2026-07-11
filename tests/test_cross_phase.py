"""Cross-phase Milestone-3 commitments (PLAN.md "Cross-phase" block).

Three guards the plan promised beyond per-module tests:
1. Payload/atom budget regression — module growth must be deliberate, not silent.
2. Lock-hold latency with ALL modules on — the ENGINE_LOCK critical section must
   stay far under the Pi client timeout (30s), or serialized throughput dies.
3. Concurrent mixed-config isolation — PyJHora keeps ayanamsa/node state in process
   globals; ENGINE_LOCK must fully serialize apply+compute so concurrent requests
   with different configs never bleed into each other.

Budget numbers are ceilings ~1.5-2x the measured baseline (450 atoms / 16.2KB /
0.53s all-modules on 2026-07 hardware) — loose enough to survive engine noise,
tight enough to catch a runaway addition.
"""

from __future__ import annotations

import concurrent.futures
import json
import time

import pytest

pytest.importorskip("jhora", reason="PyJHora not installed; run `uv sync`")

from jyotish_agent.config import KNOWN_MODULES, CalculationConfig  # noqa: E402
from jyotish_agent.interpretations import iter_fact_atoms  # noqa: E402
from jyotish_agent.pyjhora_facade import BirthProfile, compute_chart  # noqa: E402

_PROFILE = BirthProfile(
    name="Chennai Test",
    date=(1990, 1, 1),
    time=(12, 30, 0),
    latitude=13.0827,
    longitude=80.2707,
    timezone=5.5,
)
_REFERENCE = (2026, 6, 7)
_ALL_MODULES = tuple(sorted(KNOWN_MODULES))


def _compute(**cfg):
    return compute_chart(
        _PROFILE, reference_date=_REFERENCE, config=CalculationConfig(**cfg)
    )


def test_atom_and_payload_budgets():
    base = _compute()
    full = _compute(modules=_ALL_MODULES)
    base_atoms = len(iter_fact_atoms(base["facts"]))
    full_atoms = len(iter_fact_atoms(full["facts"]))
    # Ceilings: baseline 162 / 450 atoms, 8.1KB / 16.2KB payloads.
    assert base_atoms <= 250, f"default atom count crept to {base_atoms}"
    assert full_atoms <= 700, f"all-modules atom count crept to {full_atoms}"
    assert len(json.dumps(base)) <= 16_000
    assert len(json.dumps(full)) <= 32_000
    # And the floor: modules must actually add their surface.
    assert full_atoms > base_atoms + 200


def test_all_modules_latency_budget():
    _compute(modules=_ALL_MODULES)  # warm engine imports/caches
    start = time.monotonic()
    _compute(modules=_ALL_MODULES)
    elapsed = time.monotonic() - start
    # Measured ~0.53s; 3s catches a ~6x regression while tolerating slow CI. The
    # Pi client timeout is 30s — a failure here fires long before users feel it.
    assert elapsed < 3.0, f"all-modules compute took {elapsed:.2f}s"


def test_concurrent_mixed_configs_do_not_bleed():
    # Different ayanamsas and module sets in flight together. PyJHora state is
    # process-global; ENGINE_LOCK must serialize apply+compute so every result is
    # byte-identical to its own sequentially-computed baseline.
    configs = [
        {"ayanamsa": "LAHIRI", "modules": ("shadbala",)},
        {"ayanamsa": "RAMAN", "modules": ("transits", "ashtakavarga")},
        {"ayanamsa": "KP", "modules": ()},
        {"ayanamsa": "LAHIRI", "modules": _ALL_MODULES},
    ]
    baselines = [json.dumps(_compute(**c), sort_keys=True) for c in configs]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_compute, **c) for c in configs * 3]
        results = [json.dumps(f.result(), sort_keys=True) for f in futures]
    for i, result in enumerate(results):
        assert result == baselines[i % len(configs)], (
            f"concurrent result {i} diverged from its sequential baseline "
            f"(config bleed across ENGINE_LOCK)"
        )


def test_all_modules_golden_fixture_matches():
    from pathlib import Path

    from jyotish_agent.config import ephemeris_mode

    golden = (
        Path(__file__).parent
        / "fixtures"
        / f"golden_chennai_1990_{ephemeris_mode()}_modules.json"
    )
    if not golden.exists():
        pytest.skip(f"no all-modules golden for {ephemeris_mode()} mode")
    expected = json.loads(golden.read_text())
    actual = _compute(modules=_ALL_MODULES)
    assert json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)
