from __future__ import annotations

import json
from dataclasses import dataclass

from jyotish_agent import jaimini as domain
from jyotish_agent.jaimini_models import JaiminiInput


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


def _snapshot(*, lagna: int = 0, d9_lagna: int = 8) -> Snapshot:
    d1 = (Position(None, lagna, 10.0),) + tuple(
        Position(index, (index * 2 + 1) % 12, 29.0 - index)
        for index in range(9)
    )
    d9 = (Position(None, d9_lagna, 11.0),) + tuple(
        Position(index, (index * 3 + 2) % 12, 20.0 - index)
        for index in range(9)
    )
    return Snapshot(Config(), d1, d9)


def _request(*, approximate: bool = False) -> JaiminiInput:
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
    assert first.artifact_id.startswith("jya_")
    assert len(first.artifact_sha256) == len(first.artifact_token) == 64
    assert len(first.sections) <= 12
    assert sum(len(section.facts) for section in first.sections) <= 144
    atoms = {
        fact.fact_id: fact.value for section in first.sections for fact in section.facts
    }
    assert atoms["jaimini.karakas.7.AK"] == "Sun"
    assert "jaimini.arudha.AL" in atoms
    assert "jaimini.chara_dasha.1.start" in atoms
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
