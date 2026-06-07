"""Guards for the two PyJHora calculation traps (see src/jyotish_agent/config.py).

Not full golden-fixture tests (Phase 2). These lock in the behaviours that silently
corrupt output: wrong default ayanamsa, non-determinism, and unsafe ayanamsa modes
under the Moshier fallback. Global ayanamsa state is restored between tests by the
autouse fixture in conftest.py, so these tests are order-independent.
"""

from __future__ import annotations

import pytest

from conftest import PYJHORA_PRISTINE_AYANAMSA

pytest.importorskip("jhora", reason="PyJHora not installed; run `uv sync`")

from jyotish_agent import config as cfg  # noqa: E402
from jyotish_agent.config import (  # noqa: E402
    DEFAULT_AYANAMSA,
    MOSHIER_SAFE_AYANAMSAS,
    PYJHORA_DEFAULT_AYANAMSA,
    CalculationConfig,
    apply_config,
    ephemeris_mode,
)

# Chennai, 1990-01-01 12:30:00 IST (+5.5). Reused as the working fixture.
_FIXTURE = ((1990, 1, 1), (12, 30, 0), 13.0827, 80.2707, 5.5)


def _d1():
    """Compute the D1 rasi chart for the fixture, rounded for stable comparison.

    Returns a tuple of (planet, sign, rounded_degrees). PyJHora returns nested lists
    of raw doubles; rounding avoids brittle exact-float equality across libm/BLAS
    builds while still catching real placement changes.
    """
    from jhora import utils
    from jhora.horoscope.chart import charts
    from jhora.panchanga import drik

    (y, m, d), (hh, mm, ss), lat, lon, tz = _FIXTURE
    place = drik.Place("Chennai", lat, lon, tz)
    jd = utils.julian_day_number((y, m, d), (hh, mm, ss))
    with __import__("warnings").catch_warnings():
        __import__("warnings").simplefilter("ignore")
        chart = charts.rasi_chart(jd, place)
    return tuple((p, sign, round(deg, 6)) for p, (sign, deg) in chart)


def test_pyjhora_default_is_not_lahiri():
    """Documents WHY apply_config exists: PyJHora's default is not Lahiri. Asserts
    against the value captured at collection time (conftest), not a hardcoded literal."""
    assert PYJHORA_PRISTINE_AYANAMSA == PYJHORA_DEFAULT_AYANAMSA


def test_apply_config_sets_lahiri_globally():
    applied = apply_config(CalculationConfig())
    assert applied.ayanamsa == DEFAULT_AYANAMSA
    from jhora import const

    assert const._DEFAULT_AYANAMSA_MODE == "LAHIRI"


def test_ayanamsa_choice_changes_placements():
    """Proves the ayanamsa knob is actually applied, not a silent no-op, by comparing
    two Moshier-safe modes."""
    apply_config(CalculationConfig(ayanamsa="LAHIRI"))
    lahiri_chart = _d1()
    apply_config(CalculationConfig(ayanamsa="RAMAN"))
    raman_chart = _d1()
    assert lahiri_chart != raman_chart


def test_d1_is_deterministic_under_fixed_config():
    apply_config(CalculationConfig())
    assert _d1() == _d1()


def test_unknown_ayanamsa_rejected():
    with pytest.raises(ValueError, match="unknown ayanamsa"):
        apply_config(CalculationConfig(ayanamsa="NOT_A_REAL_MODE"))


def test_apply_config_rejects_unsafe_ayanamsa_on_moshier(monkeypatch):
    """Rejection is pure Python policy, so force Moshier mode regardless of what
    ephemeris files happen to be installed. This avoids the coverage cliff where the
    test silently skips on a machine with .se1 files."""
    monkeypatch.setattr(cfg, "ephemeris_mode", lambda: "moshier")
    assert "TRUE_CITRA" not in MOSHIER_SAFE_AYANAMSAS
    with pytest.raises(ValueError, match="Moshier-verified safe set"):
        apply_config(CalculationConfig(ayanamsa="TRUE_CITRA"))


def test_safe_ayanamsa_allowed_on_moshier(monkeypatch):
    monkeypatch.setattr(cfg, "ephemeris_mode", lambda: "moshier")
    for mode in MOSHIER_SAFE_AYANAMSAS:
        apply_config(CalculationConfig(ayanamsa=mode))  # must not raise


def test_pyjhora_default_ayanamsa_crashes_on_moshier_fallback():
    """PyJHora's default (TRUE_PUSHYA) is star-based and needs the Swiss ephemeris;
    under the Moshier fallback its internal reference-star lookup uses jd~0 and swisseph
    rejects it. This is genuine engine behaviour (cannot be faked), so skip when real
    .se1 files are present. It is the second reason — beyond parity — to override the
    default."""
    if ephemeris_mode() != "moshier":
        pytest.skip("Swiss ephemeris present; star-based ayanamsa would not crash")
    from jhora.panchanga import drik

    drik.set_ayanamsa_mode(PYJHORA_DEFAULT_AYANAMSA)
    with pytest.raises(Exception, match="outside Moshier planet range"):
        _d1()


def test_ephemeris_mode_reported():
    assert ephemeris_mode() in {"swiss", "moshier"}
