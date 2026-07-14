from __future__ import annotations

import json
import datetime as dt
from dataclasses import dataclass

import pytest

from jyotish_agent import jaimini as domain
from jyotish_agent.jaimini_models import JaiminiInput
from jyotish_agent.jaimini_models import ExactJaiminiBirthInput, JaiminiPlace
from jyotish_agent.timezone_resolution import TimezoneResolutionError


@dataclass(frozen=True)
class Position:
    planet_index: int | None
    sign_index: int
    degrees: float


@dataclass(frozen=True)
class Config:
    ayanamsa: str = "LAHIRI"
    rahu_ketu: str = "true_nodes"
    node_aspects: str = "standard"
    charts: tuple[str, ...] = ("D1",)
    modules: tuple[str, ...] = ()


@dataclass(frozen=True)
class Snapshot:
    config: Config
    d1: tuple[Position, ...]
    d9: tuple[Position, ...]
    sun_longitude_at_sunrise: float | None = 100.0
    minutes_since_sunrise: float | None = 120.0
    ephemeris_mode: str = "moshier"


def _snapshot(
    *, lagna: int = 0, d9_lagna: int = 8, tie: bool = False,
    sunrise_available: bool = True,
) -> Snapshot:
    d1 = (Position(None, lagna, 10.0),) + tuple(
        Position(index, (index * 2 + 1) % 12, 29.0 - index)
        for index in range(9)
    )
    d9 = (Position(None, d9_lagna, 11.0),) + tuple(
        Position(index, (index * 3 + 2) % 12, 20.0 - index)
        for index in range(9)
    )
    if tie:
        d1 = tuple(
            Position(item.planet_index, item.sign_index, 29.0)
            if item.planet_index in {0, 1}
            else item
            for item in d1
        )
    return Snapshot(
        Config(), d1, d9,
        100.0 if sunrise_available else None,
        120.0 if sunrise_available else None,
    )


def _request(*, approximate: bool = False, include_trace: bool = False) -> JaiminiInput:
    place = {
        "name": "Fixture City",
        "latitude": 10.0,
        "longitude": 20.0,
        "timezone": "Etc/UTC",
    }
    birth = (
        {
            "confidence": "approximate",
            "date": "2000-01-01",
            "earliest_time": "10:00:00",
            "latest_time": "10:10:00",
            "place": place,
        }
        if approximate
        else {
            "confidence": "exact",
            "date": "2000-01-01",
            "time": "10:05:00",
            "place": place,
        }
    )
    return JaiminiInput.model_validate(
        {
            "profile": "Synthetic Founder",
            "birth": birth,
            "gender": "male",
            "reference_date": "2026-07-14",
            "include_trace": include_trace,
        }
    )


def test_domain_facade_returns_bounded_signed_deterministic_facts(monkeypatch):
    assert hasattr(domain, "JaiminiFacade")
    monkeypatch.setattr(domain, "capture_birth_snapshots", lambda *_a, **_k: (_snapshot(),))
    first = domain.JaiminiFacade().calculate(_request())
    second = domain.JaiminiFacade().calculate(_request())

    assert first == second
    assert first.status == "completed"
    assert first.mode == "jaimini"
    assert first.profile_name == "Synthetic Founder"
    assert first.anchor_summary == "exact birth anchor; 1 sample"
    assert first.interpretation_status == "unavailable"
    assert first.interpretation is None
    assert first.provenance.source_review_status == "pending"
    assert first.provenance.ephemeris_mode == "moshier"
    assert first.provenance.tzdb_fingerprint.startswith("sha256:")
    assert first.artifact_id.startswith("jya_")
    assert len(first.artifact_sha256) == len(first.artifact_token) == 64
    assert len(first.sections) <= 12
    assert all(len(section.facts) <= 144 for section in first.sections)
    assert sum(len(section.facts) for section in first.sections) <= 384
    atoms = {
        fact.fact_id: fact.value for section in first.sections for fact in section.facts
    }
    assert atoms["jaimini.karakas.7.AK"] == "Sun"
    assert "jaimini.arudha.AL" in atoms
    assert "jaimini.chara_dasha.1.start" in atoms
    assert atoms["jaimini.special_lagnas.bhava_lagna.degrees"] == 130.0
    assert "jaimini.co_lords.Scorpio.selected" in atoms
    assert "jaimini.karakas.7.Sun.score_arcseconds" in atoms
    assert "jaimini.rasi_drishti.planet.Sun.signs" in atoms
    assert "jaimini.argala.AL.2_vs_12.status" in atoms
    assert "jaimini.chara_antardasha.1.1" in atoms
    assert first.trace is None
    assert any(item.code == "SOURCE_ADMISSION_UNVERIFIED" for item in first.limitations)
    assert len(json.dumps(first.model_dump(mode="json"), ensure_ascii=False).encode()) < 512 * 1024


def test_approximate_range_marks_changed_geometry_unstable(monkeypatch):
    assert hasattr(domain, "JaiminiFacade")
    monkeypatch.setattr(
        domain,
        "capture_birth_snapshots",
        lambda *_a, **_k: (_snapshot(lagna=0), _snapshot(lagna=0), _snapshot(lagna=1)),
    )
    result = domain.JaiminiFacade().calculate(_request(approximate=True))
    assert result.anchor_summary == "approximate birth anchor; 3 samples at 5-minute steps"
    facts = {
        fact.fact_id: fact for section in result.sections for fact in section.facts
    }
    assert facts["jaimini.lagna.sign"].stability == "unstable"
    assert any(item.code == "BIRTH_TIME_SENSITIVE" for item in result.limitations)


def test_artifact_contains_no_raw_birth_profile_or_coordinates(monkeypatch):
    assert hasattr(domain, "JaiminiFacade")
    monkeypatch.setattr(domain, "capture_birth_snapshots", lambda *_a, **_k: (_snapshot(),))
    serialized = json.dumps(
        domain.JaiminiFacade().calculate(_request()).model_dump(mode="json"),
        ensure_ascii=False,
    )
    assert "Fixture City" not in serialized
    assert '"latitude"' not in serialized
    assert '"longitude"' not in serialized


def test_include_trace_controls_bounded_rule_inputs(monkeypatch):
    monkeypatch.setattr(domain, "capture_birth_snapshots", lambda *_a, **_k: (_snapshot(),))
    hidden = domain.JaiminiFacade().calculate(_request(include_trace=False))
    shown = domain.JaiminiFacade().calculate(_request(include_trace=True))
    assert hidden.status == shown.status == "completed"
    assert hidden.trace is None
    assert shown.trace
    trace = {fact.fact_id: fact.value for fact in shown.trace}
    assert "jaimini.trace.arudha.A1.lord_sign" in trace
    assert "jaimini.trace.argala.AL.2_vs_12.contributors" in trace
    assert len(shown.trace) <= 256


def test_missing_sunrise_primitive_and_exact_karaka_tie_are_typed(monkeypatch):
    monkeypatch.setattr(
        domain, "capture_birth_snapshots", lambda *_a, **_k: (_snapshot(sunrise_available=False),)
    )
    missing = domain.JaiminiFacade().calculate(_request())
    assert missing.status == "incomplete"
    assert missing.next_action == "retry_calculation"
    assert missing.limitations[0].code == "SPECIAL_LAGNA_PRIMITIVE_UNAVAILABLE"

    monkeypatch.setattr(
        domain, "capture_birth_snapshots", lambda *_a, **_k: (_snapshot(tie=True),)
    )
    tied = domain.JaiminiFacade().calculate(_request())
    assert tied.status == "incomplete"
    assert tied.next_action == "adjudicate_karaka_tie"
    assert tied.limitations[0].code == "KARAKA_TIE_REQUIRES_ADJUDICATION"
    assert "Sun" not in tied.limitations[0].message
    assert "Moon" not in tied.limitations[0].message


def test_birth_anchor_resolves_dst_fold_gap_and_asserted_offset():
    common = {"name": "Private", "latitude": 40.7, "longitude": -74.0,
              "timezone": "America/New_York"}
    ambiguous = ExactJaiminiBirthInput(
        confidence="exact", date=dt.date(2024, 11, 3), time=dt.time(1, 30),
        place=JaiminiPlace(**common),
    )
    with pytest.raises(TimezoneResolutionError, match="AMBIGUOUS_LOCAL_TIME"):
        domain._local_datetimes(ambiguous)

    folded = ambiguous.model_copy(
        update={"place": JaiminiPlace(**common, fold=1, asserted_offset_hours=-5)}
    )
    assert domain._local_datetimes(folded)[0].astimezone(dt.UTC) == dt.datetime(
        2024, 11, 3, 6, 30, tzinfo=dt.UTC
    )

    gap = ExactJaiminiBirthInput(
        confidence="exact", date=dt.date(2024, 3, 10), time=dt.time(2, 30),
        place=JaiminiPlace(**common),
    )
    with pytest.raises(TimezoneResolutionError, match="NONEXISTENT_LOCAL_TIME"):
        domain._local_datetimes(gap)
