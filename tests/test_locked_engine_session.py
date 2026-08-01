"""Phase-1 contract tests for the single locked PyJHora calculation kernel."""

from __future__ import annotations

import concurrent.futures
import dataclasses
import json
import threading
from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

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


class _RiseOnlySwiss:
    """Minimal deterministic Swiss facade that exposes only rise events."""

    def __init__(self, events: tuple[float, ...], *, missing: bool = False) -> None:
        import swisseph as swe

        self.SUN = swe.SUN
        self.CALC_RISE = swe.CALC_RISE
        self.BIT_DISC_CENTER = swe.BIT_DISC_CENTER
        self.BIT_NO_REFRACTION = swe.BIT_NO_REFRACTION
        self.FLG_SWIEPH = swe.FLG_SWIEPH
        self.GREG_CAL = swe.GREG_CAL
        self._swe = swe
        self.events = events
        self.missing = missing
        self.calls: list[dict[str, object]] = []

    def julday(self, *args):
        return self._swe.julday(*args)

    def revjul(self, *args):
        return self._swe.revjul(*args)

    def rise_trans(self, start_jd, body, **kwargs):
        self.calls.append({"start_jd": start_jd, "body": body, **kwargs})
        if self.missing:
            return -2, (0.0,) * 10
        event = next((value for value in self.events if value >= start_jd), None)
        return (
            (-2, (0.0,) * 10)
            if event is None
            else (0, (event, *(0.0 for _ in range(9))))
        )


class _RiseDrik:
    PLANET_FLAGS = 66_386

    def __init__(self, longitudes: dict[float, float]) -> None:
        self.longitudes = longitudes
        self.solar_calls: list[float] = []

    def solar_longitude(self, jd: float) -> float:
        self.solar_calls.append(jd)
        return self.longitudes[jd]


def _utc_jd(instant: datetime) -> float:
    import swisseph as swe

    return facade._utc_julian_day(swe, instant)


def _anchor_profile(birth_utc: datetime, zone_id: str = "Etc/UTC") -> BirthProfile:
    zone = ZoneInfo(zone_id)
    local = birth_utc.astimezone(zone)
    offset = local.utcoffset()
    assert offset is not None
    return BirthProfile(
        name="Anchor Test",
        date=(local.year, local.month, local.day),
        time=(local.hour, local.minute, local.second),
        latitude=0.0,
        longitude=0.0,
        timezone=offset.total_seconds() / 3600,
        timezone_name=zone_id,
        utc_instant=birth_utc,
    )


@pytest.mark.parametrize(
    ("birth_utc", "expected_anchor", "expected_minutes"),
    (
        (
            datetime(2024, 1, 2, 5, 59, tzinfo=UTC),
            datetime(2024, 1, 1, 6, 0, tzinfo=UTC),
            1_439.0,
        ),
        (
            datetime(2024, 1, 2, 6, 0, tzinfo=UTC),
            datetime(2024, 1, 2, 6, 0, tzinfo=UTC),
            0.0,
        ),
        (
            datetime(2024, 1, 2, 7, 0, tzinfo=UTC),
            datetime(2024, 1, 2, 6, 0, tzinfo=UTC),
            60.0,
        ),
    ),
)
def test_regular_special_lagna_uses_latest_prior_apparent_sunrise(
    birth_utc: datetime,
    expected_anchor: datetime,
    expected_minutes: float,
):
    previous = _utc_jd(datetime(2024, 1, 1, 6, 0, tzinfo=UTC))
    current = _utc_jd(datetime(2024, 1, 2, 6, 0, tzinfo=UTC))
    swe = _RiseOnlySwiss((previous, current))
    drik = _RiseDrik({previous: 90.0, current: 100.0})
    profile = _anchor_profile(birth_utc)
    place = SimpleNamespace(latitude=0.0, longitude=0.0)

    longitude, elapsed = facade._special_lagna_primitive(
        drik, 0.0, place, profile, _swe=swe
    )

    expected_jd = _utc_jd(expected_anchor)
    assert drik.solar_calls == [expected_jd]
    assert longitude == drik.longitudes[expected_jd]
    assert elapsed == expected_minutes
    assert swe.calls
    assert all(call["body"] == swe.SUN for call in swe.calls)
    assert all(call["rsmi"] == swe.CALC_RISE for call in swe.calls)
    assert all(call["rsmi"] & swe.BIT_DISC_CENTER == 0 for call in swe.calls)
    assert all(call["rsmi"] & swe.BIT_NO_REFRACTION == 0 for call in swe.calls)
    assert all(call["flags"] == swe.FLG_SWIEPH for call in swe.calls)
    assert all(call["flags"] != drik.PLANET_FLAGS for call in swe.calls)


def test_regular_special_lagna_resets_at_exact_sunrise_boundary():
    previous = _utc_jd(datetime(2024, 1, 1, 6, 0, tzinfo=UTC))
    current = _utc_jd(datetime(2024, 1, 2, 6, 0, tzinfo=UTC))
    swe = _RiseOnlySwiss((previous, current))
    drik = _RiseDrik({previous: 90.0, current: 100.0})
    place = SimpleNamespace(latitude=0.0, longitude=0.0)

    before = facade._special_lagna_primitive(
        drik,
        0.0,
        place,
        _anchor_profile(datetime(2024, 1, 2, 5, 59, tzinfo=UTC)),
        _swe=swe,
    )
    exact = facade._special_lagna_primitive(
        drik,
        0.0,
        place,
        _anchor_profile(datetime(2024, 1, 2, 6, 0, tzinfo=UTC)),
        _swe=swe,
    )

    assert before == (90.0, 1_439.0)
    assert exact == (100.0, 0.0)
    assert before != exact  # The canonical anchor switch is a real discontinuity.


def test_regular_special_lagna_normalizes_rounded_360_degree_sun():
    anchor = _utc_jd(datetime(2024, 1, 2, 6, 0, tzinfo=UTC))
    swe = _RiseOnlySwiss((anchor,))
    drik = _RiseDrik({anchor: 359.9999995})

    longitude, elapsed = facade._special_lagna_primitive(
        drik,
        0.0,
        SimpleNamespace(latitude=0.0, longitude=0.0),
        _anchor_profile(datetime(2024, 1, 2, 6, 0, tzinfo=UTC)),
        _swe=swe,
    )

    assert longitude == 0.0
    assert elapsed == 0.0
    assert facade._round_deg(359.9999995) == 360.0


def test_regular_special_lagna_elapsed_uses_aware_utc_across_dst_fall_back():
    previous = _utc_jd(datetime(2024, 11, 2, 11, 30, tzinfo=UTC))
    current = _utc_jd(datetime(2024, 11, 3, 11, 0, tzinfo=UTC))
    swe = _RiseOnlySwiss((previous, current))
    drik = _RiseDrik({previous: 90.0, current: 100.0})
    birth_utc = datetime(2024, 11, 3, 6, 30, tzinfo=UTC)

    longitude, elapsed = facade._special_lagna_primitive(
        drik,
        0.0,
        SimpleNamespace(latitude=40.7, longitude=-74.0),
        _anchor_profile(birth_utc, "America/New_York"),
        _swe=swe,
    )

    assert longitude == 90.0
    assert elapsed == 1_140.0
    assert (
        birth_utc.astimezone(ZoneInfo("America/New_York")).hour
        - datetime(2024, 11, 2, 11, 30, tzinfo=UTC)
        .astimezone(ZoneInfo("America/New_York"))
        .hour
    ) != elapsed / 60


def test_polar_missing_rise_code_fails_special_lagna_primitive_closed():
    swe = _RiseOnlySwiss((), missing=True)
    drik = _RiseDrik({})
    result = facade._special_lagna_primitive(
        drik,
        0.0,
        SimpleNamespace(latitude=80.0, longitude=0.0),
        _anchor_profile(datetime(2024, 6, 21, 12, 0, tzinfo=UTC)),
        _swe=swe,
    )

    assert result == (None, None)
    assert drik.solar_calls == []
    assert len(swe.calls) == 2


def test_real_swiss_polar_day_returns_no_adjacent_sunrise():
    from jhora.panchanga import drik

    birth_utc = datetime(2024, 6, 21, 12, 0, tzinfo=UTC)
    place = drik.Place("Polar Test", 80.0, 0.0, 0.0, elevation=0.0)

    result = facade._special_lagna_primitive(
        drik, 0.0, place, _anchor_profile(birth_utc)
    )

    assert result == (None, None)


def test_real_swiss_selects_second_qualifying_rise_in_one_civil_day():
    import swisseph as swe
    from jhora.panchanga import drik

    birth_utc = datetime(2024, 4, 2, 23, 59, 58, tzinfo=UTC)
    profile = dataclasses.replace(
        _anchor_profile(birth_utc), longitude=90.0
    )
    place = drik.Place("Double Rise Test", 0.0, 90.0, 0.0, elevation=0.0)
    day_start = datetime(2024, 4, 2, tzinfo=UTC)
    common = {
        "body": swe.SUN,
        "rsmi": swe.CALC_RISE,
        "geopos": (90.0, 0.0, 0.0),
        "atpress": 0.0,
        "attemp": 15.0,
        "flags": swe.FLG_SWIEPH,
    }
    first_result, first_times = swe.rise_trans(
        _utc_jd(day_start) - 1 / 86_400,
        **common,
    )
    second_result, second_times = swe.rise_trans(
        float(first_times[0]) + 1 / 86_400,
        **common,
    )
    expected_anchor = float(second_times[0])
    expected_elapsed = (
        birth_utc - facade._utc_from_julian_day(swe, expected_anchor)
    ).total_seconds()

    assert first_result == second_result == 0
    assert facade._utc_from_julian_day(swe, float(first_times[0])).date() == day_start.date()
    assert facade._utc_from_julian_day(swe, expected_anchor).date() == day_start.date()
    assert 0 < expected_elapsed < 2

    longitude, elapsed = facade._special_lagna_primitive(
        drik, 0.0, place, profile
    )

    assert longitude == pytest.approx(drik.solar_longitude(expected_anchor), abs=1e-6)
    assert elapsed * 60 == pytest.approx(expected_elapsed, abs=1e-4)


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
