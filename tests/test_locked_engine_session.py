"""Phase-1 contract tests for the single locked PyJHora calculation kernel."""

from __future__ import annotations

import concurrent.futures
import dataclasses
import json
import threading

import pytest

pytest.importorskip("jhora", reason="PyJHora not installed; run `uv sync`")

import jyotish_agent.pyjhora_facade as facade  # noqa: E402
from jyotish_agent.config import CalculationConfig, apply_config  # noqa: E402
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
    requested_charts = ["D1"]
    requested_modules: list[str] = []

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
        assert snapshot.config.charts == ("D1",)
        assert snapshot.config.modules == ()
        assert snapshot.sun_longitude_at_sunrise is not None
        assert snapshot.minutes_since_sunrise is not None
        assert snapshot.ephemeris_mode in {"moshier", "swiss"}
        with pytest.raises(AttributeError):
            snapshot.config.charts.append("D10")
        return snapshot

    result = _run_engine_session(
        _PROFILE,
        _REFERENCE,
        CalculationConfig(charts=requested_charts, modules=requested_modules),
        domain_callback=inspect,
    )

    requested_charts.append("D10")
    requested_modules.append("shadbala")

    # D9 is an internal primitive for domain callbacks, not an additive natal fact.
    assert result.domain is result.snapshot
    assert result.natal["calculation_config"]["charts"] == ["D1"]
    assert "d9" not in result.natal["facts"]
    assert not hasattr(result.snapshot, "raw_charts")
    assert result.snapshot.config.charts == ("D1",)
    assert result.snapshot.config.modules == ()


def test_unavailable_sunrise_primitive_is_captured_without_raw_engine_error(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise RuntimeError("private engine detail")

    monkeypatch.setattr(facade, "_special_lagna_primitive", unavailable, raising=False)
    result = _run_engine_session(
        _PROFILE, _REFERENCE, domain_callback=lambda snapshot: snapshot
    )
    assert result.domain.sun_longitude_at_sunrise is None
    assert result.domain.minutes_since_sunrise is None


def test_same_thread_session_reentry_fails_promptly_without_reentrant_lock(monkeypatch):
    lock = _TrackingLock()
    monkeypatch.setattr("jyotish_agent.pyjhora_facade.ENGINE_LOCK", lock)

    def reenter(_snapshot):
        compute_chart(_PROFILE, reference_date=_REFERENCE)

    with pytest.raises(
        facade._EngineSessionReentryError,
        match="engine session re-entry is not allowed",
    ):
        _run_engine_session(_PROFILE, _REFERENCE, domain_callback=reenter)

    assert (lock.enters, lock.exits, lock.active) == (1, 1, False)


def test_callback_cannot_corrupt_completed_natal_engine_reads():
    baseline = compute_chart(_PROFILE, reference_date=_REFERENCE)

    result = _run_engine_session(
        _PROFILE,
        _REFERENCE,
        CalculationConfig(ayanamsa="LAHIRI"),
        domain_callback=lambda _snapshot: apply_config(
            CalculationConfig(ayanamsa="RAMAN")
        ),
    )

    assert json.dumps(result.natal, sort_keys=True) == json.dumps(baseline, sort_keys=True)


def test_pure_natal_assembly_runs_after_engine_lock_release(monkeypatch):
    lock = _TrackingLock()
    monkeypatch.setattr("jyotish_agent.pyjhora_facade.ENGINE_LOCK", lock)

    for name in ("_placements", "_houses", "_aspects", "detect_yogas"):
        original = getattr(facade, name)

        def checked(*args, _original=original, **kwargs):
            assert not lock.active
            return _original(*args, **kwargs)

        monkeypatch.setattr(facade, name, checked)

    _run_engine_session(_PROFILE, _REFERENCE)


def test_callback_exception_releases_lock_for_next_session(monkeypatch):
    lock = _TrackingLock()
    monkeypatch.setattr("jyotish_agent.pyjhora_facade.ENGINE_LOCK", lock)

    def fail(_snapshot):
        raise LookupError("domain callback failed")

    with pytest.raises(LookupError, match="domain callback failed"):
        _run_engine_session(_PROFILE, _REFERENCE, domain_callback=fail)
    assert (lock.enters, lock.exits, lock.active) == (1, 1, False)

    _run_engine_session(_PROFILE, _REFERENCE)
    assert (lock.enters, lock.exits, lock.active) == (2, 2, False)


def test_d1_only_session_engine_chart_cost_is_three_divisional_calls(monkeypatch):
    from jhora.horoscope.chart import charts

    original = charts.divisional_chart
    factors: list[int] = []

    def counted(*args, divisional_chart_factor=1, **kwargs):
        factors.append(divisional_chart_factor)
        return original(
            *args, divisional_chart_factor=divisional_chart_factor, **kwargs
        )

    monkeypatch.setattr(charts, "divisional_chart", counted)

    _run_engine_session(
        _PROFILE, _REFERENCE, CalculationConfig(charts=("D1",))
    )

    # Explicit D1 + internal callback D9 + PyJHora's D1 dasha lookup.
    assert factors == [1, 9, 1]


def test_concurrent_session_callbacks_keep_mixed_configs_isolated():
    configs = [
        CalculationConfig(ayanamsa="LAHIRI", rahu_ketu="true_nodes"),
        CalculationConfig(ayanamsa="RAMAN", rahu_ketu="mean_nodes"),
        CalculationConfig(ayanamsa="KP", rahu_ketu="true_nodes", charts=("D1",)),
    ]

    def compute(config: CalculationConfig, start: threading.Event | None = None) -> str:
        if start is not None:
            assert start.wait(timeout=5)
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
    start = threading.Event()
    with concurrent.futures.ThreadPoolExecutor(max_workers=9) as pool:
        futures = [pool.submit(compute, config, start) for config in configs * 3]
        start.set()
        concurrent_results = [future.result() for future in futures]

    assert concurrent_results == baselines * 3
