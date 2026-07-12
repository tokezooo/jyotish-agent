from __future__ import annotations

import uuid
import time
import hashlib
import sqlite3
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


@pytest.mark.parametrize("zone_id", ["UTC", "Europe/London"])
def test_zero_offset_iana_zones_are_valid(client, zone_id):
    response = client.post("/v2/research-runs", json=_body(
        {"kind": "iana", "zone_id": zone_id}, civil="2024-01-15T12:00:00",
        longitude=0,
    ))
    assert response.status_code == 201, response.text
    assert response.json()["timezone_resolution"]["resolved_offset_minutes"] == 0
    assert response.json()["timezone_resolution"]["utc_instant"] == "2024-01-15T12:00:00Z"


def test_historical_subminute_offset_fails_explicitly(client):
    response = client.post("/v2/research-runs", json=_body(
        {"kind": "iana", "zone_id": "Europe/Paris"},
        civil="1900-01-01T12:00:00", longitude=2.35,
    ))
    assert response.status_code == 422
    assert response.json()["error_code"] == "TIMEZONE_OFFSET_SUBMINUTE_UNSUPPORTED"


def _plan(client, created):
    screened = client.post(
        f"/v2/research-runs/{created['run_id']}/screen",
        json={"operation_id": f"op_{uuid.uuid4()}", "expected_revision": 1},
    ).json()
    return client.post(
        f"/v2/research-runs/{created['run_id']}/plan",
        json={"operation_id": f"op_{uuid.uuid4()}",
              "expected_revision": screened["revision"],
              "intent": {"family": "career_factors_and_timing",
                         "explicit_annual_scope": False},
              "classifier": {"classifier_model": "fixture", "classifier_version": "1",
                             "prompt_hash": hashlib.sha256(b"fixture").hexdigest()}},
    ).json()


def test_sensitivity_re_resolves_shifted_iana_civil_time_and_rejects_gap(client, monkeypatch):
    body = _body({"kind": "iana", "zone_id": "America/New_York"},
                 civil="2024-03-10T01:55:00")
    body["birth_profile"]["birth_time_confidence"] = "approximate"
    created = client.post("/v2/research-runs", json=body).json()
    planned = _plan(client, created)
    monkeypatch.setattr("jyotish_agent.research_service.compute_chart", lambda *a, **k: {
        "normalized_input": {}, "calculation_config": {},
        "facts": {"ascendant": {"sign": "Pisces"}}, "provenance": {},
    })
    response = client.post(
        f"/v2/research-runs/{created['run_id']}/calculate",
        json={"operation_id": f"op_{uuid.uuid4()}",
              "expected_revision": planned["revision"]},
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "NONEXISTENT_LOCAL_TIME"


def test_sensitivity_requires_fold_when_shift_enters_ambiguous_time(client, monkeypatch):
    def calculate(zone):
        body = _body(zone, civil="2024-11-03T00:55:00")
        body["birth_profile"]["birth_time_confidence"] = "approximate"
        created = client.post("/v2/research-runs", json=body).json()
        planned = _plan(client, created)
        return client.post(
            f"/v2/research-runs/{created['run_id']}/calculate",
            json={"operation_id": f"op_{uuid.uuid4()}",
                  "expected_revision": planned["revision"]},
        )

    monkeypatch.setattr("jyotish_agent.research_service.compute_chart", lambda *a, **k: {
        "normalized_input": {}, "calculation_config": {},
        "facts": {"ascendant": {"sign": "Pisces"}}, "provenance": {},
    })
    ambiguous = calculate({"kind": "iana", "zone_id": "America/New_York"})
    assert ambiguous.status_code == 422
    assert ambiguous.json()["error_code"] == "AMBIGUOUS_LOCAL_TIME"
    folded = calculate({"kind": "iana", "zone_id": "America/New_York", "fold": 1})
    assert folded.status_code == 200, folded.text


def test_calculation_rejects_changed_pinned_tzif_material(client, monkeypatch):
    created = client.post("/v2/research-runs", json=_body(
        {"kind": "iana", "zone_id": "America/New_York"}
    )).json()
    planned = _plan(client, created)
    store = client.app.state.research_service.store
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("UPDATE research_runs SET timezone_fingerprint=? WHERE run_id=?",
                           ("sha256:" + "0" * 64, created["run_id"]))
    monkeypatch.setattr("jyotish_agent.research_service.compute_chart",
                        lambda *a, **k: pytest.fail("calculation used changed tzif"))
    response = client.post(
        f"/v2/research-runs/{created['run_id']}/calculate",
        json={"operation_id": f"op_{uuid.uuid4()}",
              "expected_revision": planned["revision"]},
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "TIMEZONE_MATERIAL_MISMATCH"


def test_calculation_rejects_divergent_persisted_iana_resolution(client, monkeypatch):
    created = client.post("/v2/research-runs", json=_body(
        {"kind": "iana", "zone_id": "America/New_York"}
    )).json()
    planned = _plan(client, created)
    store = client.app.state.research_service.store
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("UPDATE research_runs SET resolved_offset_minutes=0 WHERE run_id=?",
                           (created["run_id"],))
    monkeypatch.setattr("jyotish_agent.research_service.compute_chart",
                        lambda *a, **k: pytest.fail("calculation used divergent resolution"))
    response = client.post(
        f"/v2/research-runs/{created['run_id']}/calculate",
        json={"operation_id": f"op_{uuid.uuid4()}",
              "expected_revision": planned["revision"]},
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "TIMEZONE_RESOLUTION_MISMATCH"
