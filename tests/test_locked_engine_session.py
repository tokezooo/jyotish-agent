"""Phase-1 contract tests for the single locked PyJHora calculation kernel."""

from __future__ import annotations

import concurrent.futures
import dataclasses
import json

import pytest

pytest.importorskip("jhora", reason="PyJHora not installed; run `uv sync`")

from jyotish_agent.config import CalculationConfig  # noqa: E402
from jyotish_agent.pyjhora_facade import (  # noqa: E402
    BirthProfile,
    _run_engine_session,
    compute_chart,
)

_PROFILE = BirthProfile(
    name="Chennai Test",
    date=(1990, 1, 1),
    time=(12, 30, 0),
    latitude=13.0827,
    longitude=80.2707,
    timezone=5.5,
)
_REFERENCE = (2026, 6, 7)


class _TrackingLock:
    def __init__(self) -> None:
        self.active = False
        self.enters = 0
        self.exits = 0

    def __enter__(self):
        assert not self.active
        self.active = True
        self.enters += 1
        return self

    def __exit__(self, exc_type, exc, tb):
        assert self.active
        self.active = False
        self.exits += 1


def test_session_owns_one_lock_and_runs_callback_inside_it(monkeypatch):
    lock = _TrackingLock()
    monkeypatch.setattr("jyotish_agent.pyjhora_facade.ENGINE_LOCK", lock)
    callback_states: list[bool] = []

    result = _run_engine_session(
        _PROFILE,
        _REFERENCE,
        CalculationConfig(),
        domain_callback=lambda _snapshot: callback_states.append(lock.active)
        or "domain-result",
    )

    assert callback_states == [True]
    assert (lock.enters, lock.exits, lock.active) == (1, 1, False)
    assert result.domain == "domain-result"


def test_session_snapshot_is_immutable_normalized_d1_d9_without_raw_charts():
    def inspect(snapshot):
        assert isinstance(snapshot.d1, tuple)
        assert isinstance(snapshot.d9, tuple)
        assert len(snapshot.d1) == 10  # Lagna plus nine grahas.
        assert len(snapshot.d9) == 10
        assert snapshot.d1[0].planet_index is None
        assert {p.planet_index for p in snapshot.d1[1:]} == set(range(9))
        assert all(0 <= p.sign_index < 12 for p in (*snapshot.d1, *snapshot.d9))
        assert all(isinstance(p.degrees, float) for p in (*snapshot.d1, *snapshot.d9))
        with pytest.raises(dataclasses.FrozenInstanceError):
            snapshot.d1[0].sign_index = 1
        return snapshot

    result = _run_engine_session(
        _PROFILE,
        _REFERENCE,
        CalculationConfig(charts=("D1",)),
        domain_callback=inspect,
    )

    # D9 is an internal primitive for domain callbacks, not an additive natal fact.
    assert result.domain is result.snapshot
    assert result.natal["calculation_config"]["charts"] == ["D1"]
    assert "d9" not in result.natal["facts"]
    assert not hasattr(result.snapshot, "raw_charts")


def test_session_natal_result_is_byte_identical_to_public_compute_chart():
    config = CalculationConfig(
        ayanamsa="RAMAN",
        node_aspects="jupiter_like",
        charts=("D1", "D9", "D10"),
        modules=("shadbala",),
    )
    session = _run_engine_session(_PROFILE, _REFERENCE, config)
    public = compute_chart(_PROFILE, reference_date=_REFERENCE, config=config)

    assert json.dumps(session.natal, sort_keys=True) == json.dumps(
        public, sort_keys=True
    )


def test_concurrent_session_callbacks_keep_mixed_configs_isolated():
    configs = [
        CalculationConfig(ayanamsa="LAHIRI", rahu_ketu="true_nodes"),
        CalculationConfig(ayanamsa="RAMAN", rahu_ketu="mean_nodes"),
        CalculationConfig(ayanamsa="KP", rahu_ketu="true_nodes", charts=("D1",)),
    ]

    def compute(config: CalculationConfig) -> str:
        result = _run_engine_session(
            _PROFILE,
            _REFERENCE,
            config,
            domain_callback=lambda snapshot: {
                "ayanamsa": snapshot.config.ayanamsa,
                "rahu_ketu": snapshot.config.rahu_ketu,
                "d1": [dataclasses.asdict(p) for p in snapshot.d1],
                "d9": [dataclasses.asdict(p) for p in snapshot.d9],
            },
        )
        return json.dumps(result.domain, sort_keys=True)

    baselines = [compute(config) for config in configs]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(compute, config) for config in configs * 3]
        concurrent_results = [future.result() for future in futures]

    assert concurrent_results == baselines * 3
