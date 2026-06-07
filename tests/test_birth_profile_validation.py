"""Unit tests for birth-profile models, normalization, and soft warnings.

These exercise the validation layer directly (no HTTP, no PyJHora)."""

from __future__ import annotations

import datetime as _dt

import pytest
from pydantic import ValidationError

from jyotish_agent.models import (
    BirthProfileRequest,
    BirthTimeConfidence,
    CalculationConfigRequest,
    Place,
)
from jyotish_agent.validation import (
    config_warnings,
    normalized_profile,
    profile_warnings,
)


def _profile(**over) -> BirthProfileRequest:
    base = {
        "name": "Test",
        "date": _dt.date(1990, 1, 1),
        "time": _dt.time(12, 30, 0),
        "place": {
            "name": "Chennai",
            "latitude": 13.0827,
            "longitude": 80.2707,
            "timezone": 5.5,
        },
    }
    base.update(over)
    return BirthProfileRequest(**base)


def test_valid_profile_normalizes():
    norm = normalized_profile(_profile())
    assert norm["date"] == "1990-01-01"
    assert norm["time"] == "12:30:00"
    assert norm["place"]["timezone"] == 5.5
    assert norm["birth_time_confidence"] == "exact"


def test_invalid_calendar_date_rejected():
    with pytest.raises(ValidationError):
        _profile(date="2025-02-30")


def test_latitude_out_of_range_rejected():
    with pytest.raises(ValidationError):
        Place(name="X", latitude=200, longitude=0, timezone=0)


def test_timezone_required():
    with pytest.raises(ValidationError):
        Place(name="X", latitude=0, longitude=0)


def test_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        _profile(unexpected="x")


def test_non_exact_birth_time_warns():
    w = profile_warnings(_profile(birth_time_confidence=BirthTimeConfidence.approximate))
    assert any("confidence" in m for m in w)


def test_on_the_hour_time_warns_when_not_exact():
    w = profile_warnings(
        _profile(time=_dt.time(6, 0, 0), birth_time_confidence="approximate")
    )
    assert any("on the hour" in m for m in w)


def test_on_the_hour_time_no_warning_when_exact():
    # An 'exact' on-the-hour birth is fine; no nag.
    w = profile_warnings(_profile(time=_dt.time(6, 0, 0)))
    assert not any("on the hour" in m for m in w)


def test_exact_minute_time_no_hour_warning():
    w = profile_warnings(_profile(time=_dt.time(12, 30, 0)))
    assert not any("on the hour" in m for m in w)


def test_year_out_of_supported_range_rejected():
    with pytest.raises(ValidationError):
        _profile(date=_dt.date(1700, 1, 1))


def test_name_too_long_rejected():
    with pytest.raises(ValidationError):
        _profile(name="x" * 5000)


def test_unsupported_chart_warns():
    w = config_warnings(CalculationConfigRequest(charts=["D1", "D9", "D10"]))
    assert any("D10" in m for m in w)


def test_supported_charts_no_warning():
    assert config_warnings(CalculationConfigRequest(charts=["D1", "D9"])) == []
