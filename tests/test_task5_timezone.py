from __future__ import annotations

import uuid
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jyotish_agent.api import app
from jyotish_agent.research_service import ResearchService
from jyotish_agent.research_store import ResearchStore


def _body(zone: dict, *, civil: str = "2024-01-15T12:00:00", longitude=-74.0):
    date, time = civil.split("T")
    return {
        "operation_id": f"op_{uuid.uuid4()}",
        "expected_revision": 0,
        "question": "What career factors and timing should I consider?",
        "birth_profile": {
            "name": "DST fixture", "date": date, "time": time,
            "place": {"name": "fixture", "latitude": 40.7,
                      "longitude": longitude, "timezone": zone},
        },
        "calculation_config": {"reference_date": "2026-07-12"},
        "model_version": "m1", "planner_version": "p1",
        "corpus_version": "c1", "contract_version": "2.0",
    }


@pytest.fixture
def client(tmp_path: Path):
    app.state.research_service = ResearchService(ResearchStore(tmp_path / "data"))
    return TestClient(app)


def test_iana_resolution_persists_replay_inputs(client):
    response = client.post("/v2/research-runs", json=_body(
        {"kind": "iana", "zone_id": "America/New_York"}
    ))
    assert response.status_code == 201, response.text
    resolution = response.json()["timezone_resolution"]
    assert resolution["original_civil_datetime"] == "2024-01-15T12:00:00"
    assert resolution["zone_id"] == "America/New_York"
    assert resolution["resolved_offset_minutes"] == -300
    assert resolution["utc_instant"] == "2024-01-15T17:00:00Z"
    assert resolution["fold"] == 0
    assert resolution["tzdb_fingerprint"].startswith("sha256:")


@pytest.mark.parametrize(
    ("civil", "expected_code"),
    [("2024-03-10T02:30:00", "NONEXISTENT_LOCAL_TIME"),
     ("2024-11-03T01:30:00", "AMBIGUOUS_LOCAL_TIME")],
)
def test_dst_gap_and_unspecified_fold_are_stable_errors(client, civil, expected_code):
    response = client.post("/v2/research-runs", json=_body(
        {"kind": "iana", "zone_id": "America/New_York"}, civil=civil
    ))
    assert response.status_code == 422
    assert response.json()["error_code"] == expected_code


def test_fold_selects_distinct_utc_instants(client):
    instants = []
    for fold in (0, 1):
        response = client.post("/v2/research-runs", json=_body(
            {"kind": "iana", "zone_id": "America/New_York", "fold": fold},
            civil="2024-11-03T01:30:00",
        ))
        assert response.status_code == 201, response.text
        instants.append(response.json()["timezone_resolution"]["utc_instant"])
    assert instants == ["2024-11-03T05:30:00Z", "2024-11-03T06:30:00Z"]


def test_asserted_offset_mismatch_and_coordinate_warning(client):
    mismatch = client.post("/v2/research-runs", json=_body(
        {"kind": "iana_with_asserted_offset", "zone_id": "America/New_York",
         "asserted_offset_hours": -5}, civil="2024-07-01T12:00:00"
    ))
    assert mismatch.status_code == 422
    assert mismatch.json()["error_code"] == "TIMEZONE_OFFSET_MISMATCH"

    warning = client.post("/v2/research-runs", json=_body(
        {"kind": "iana", "zone_id": "Asia/Tokyo"}, longitude=-74.0
    ))
    assert warning.status_code == 201
    assert warning.json()["timezone_resolution"]["warnings"] == [
        "COORDINATE_TIMEZONE_MISMATCH"
    ]


def test_iana_resolution_is_independent_of_process_timezone(client, monkeypatch):
    results = []
    for process_zone in ("UTC", "Pacific/Honolulu"):
        monkeypatch.setenv("TZ", process_zone)
        if hasattr(time, "tzset"):
            time.tzset()
        response = client.post("/v2/research-runs", json=_body(
            {"kind": "iana", "zone_id": "America/New_York"}
        ))
        assert response.status_code == 201
        results.append(response.json()["timezone_resolution"]["utc_instant"])
    assert results == ["2024-01-15T17:00:00Z"] * 2
