from __future__ import annotations

import logging
import math
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from jyotish_agent.api import app
from jyotish_agent.research_models import ResearchPlace
from jyotish_agent.research_service import ResearchService
from jyotish_agent.research_store import ResearchStore


def _operation_id() -> str:
    return f"op_{uuid.uuid4()}"


def _body(operation_id: str | None = None) -> dict:
    return {
        "operation_id": operation_id or _operation_id(),
        "expected_revision": 0,
        "question": "Which career factors should be investigated?",
        "birth_profile": {
            "name": "Authored Fixture",
            "date": "1990-01-01",
            "time": "12:30:00",
            "place": {
                "name": "Chennai",
                "latitude": 13.0827,
                "longitude": 80.2707,
                "timezone": 5.5,
            },
        },
        "calculation_config": {"reference_date": "2026-07-12"},
        "model_version": "test-model-v1",
        "planner_version": "provisional-v1",
        "corpus_version": "test-corpus-v1",
        "contract_version": "2.0",
    }


def _client(tmp_path: Path) -> TestClient:
    app.state.research_service = ResearchService(
        ResearchStore(tmp_path / "data")
    )
    return TestClient(app)


def test_create_get_and_list_events_survive_service_restart(tmp_path: Path):
    client = _client(tmp_path)
    created = client.post("/v2/research-runs", json=_body())
    assert created.status_code == 201, created.text
    run = created.json()
    assert run["run_id"].startswith("rr_")
    assert run["revision"] == 1
    assert run["timezone_resolution"]["mode"] == "fixed_offset_legacy"
    assert run["timezone_resolution"]["resolved_offset_minutes"] == 330
    assert run["timezone_resolution"]["utc_instant"] == "1990-01-01T07:00:00Z"
    assert run["reference_date"] == "2026-07-12"
    assert len(run["request_hash"]) == 64

    # A new service/store instance proves persistence rather than in-memory caching.
    client = _client(tmp_path)
    fetched = client.get(f"/v2/research-runs/{run['run_id']}")
    assert fetched.status_code == 200
    assert fetched.json() == run
    events = client.get(f"/v2/research-runs/{run['run_id']}/events")
    assert events.status_code == 200
    assert len(events.json()["events"]) == 1
    assert events.json()["events"][0]["event_type"] == "research_run.created"


def test_create_is_idempotent_by_operation_id(tmp_path: Path):
    client = _client(tmp_path)
    operation_id = _operation_id()
    body = _body(operation_id)
    first = client.post("/v2/research-runs", json=body)
    second = client.post("/v2/research-runs", json=body)
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()

    changed = {**body, "question": "A changed question"}
    conflict = client.post("/v2/research-runs", json=changed)
    assert conflict.status_code == 409
    assert conflict.headers["content-type"].startswith("application/problem+json")


def test_client_assigned_run_id_survives_restart_and_exact_replay(tmp_path: Path):
    client = _client(tmp_path)
    run_id = f"rr_{uuid.uuid4()}"
    operation_id = _operation_id()
    body = {**_body(operation_id), "run_id": run_id}

    created = client.post("/v2/research-runs", json=body)
    assert created.status_code == 201, created.text
    assert created.json()["run_id"] == run_id

    restarted = _client(tmp_path)
    fetched = restarted.get(f"/v2/research-runs/{run_id}")
    replayed = restarted.post("/v2/research-runs", json=body)
    assert fetched.status_code == 200
    assert replayed.status_code == 201
    assert fetched.json() == replayed.json() == created.json()


def test_client_assigned_run_id_collision_is_409_and_preserves_original_ledger(
    tmp_path: Path,
):
    client = _client(tmp_path)
    run_id = f"rr_{uuid.uuid4()}"
    original_body = {**_body(), "run_id": run_id}
    original = client.post("/v2/research-runs", json=original_body)
    assert original.status_code == 201, original.text

    collision_body = {
        **original_body,
        "operation_id": _operation_id(),
    }
    collision = client.post("/v2/research-runs", json=collision_body)
    assert collision.status_code == 409
    assert collision.headers["content-type"].startswith("application/problem+json")

    fetched = client.get(f"/v2/research-runs/{run_id}")
    events = client.get(f"/v2/research-runs/{run_id}/events")
    assert fetched.status_code == events.status_code == 200
    assert fetched.json() == original.json()
    assert len(events.json()["events"]) == 1
    assert events.json()["events"][0]["operation_id"] == original_body["operation_id"]


def test_numeric_and_explicit_fixed_offsets_remain_distinct_client_payloads(tmp_path: Path):
    client = _client(tmp_path)
    numeric = client.post("/v2/research-runs", json=_body()).json()
    explicit_body = _body()
    explicit_body["birth_profile"]["place"]["timezone"] = {
        "kind": "fixed_offset_legacy",
        "offset_hours": 5.5,
    }
    explicit = client.post("/v2/research-runs", json=explicit_body).json()
    assert explicit["request_hash"] != numeric["request_hash"]


def test_v2_boundary_forbids_extra_fields_and_executes_iana(tmp_path: Path):
    client = _client(tmp_path)
    extra = _body()
    extra["secret"] = "must-not-be-reflected"
    response = client.post("/v2/research-runs", json=extra)
    assert response.status_code == 422
    assert "must-not-be-reflected" not in response.text

    iana = _body()
    iana["birth_profile"]["place"]["timezone"] = {
        "kind": "iana",
        "zone_id": "Asia/Kolkata",
    }
    response = client.post("/v2/research-runs", json=iana)
    assert response.status_code == 201
    assert response.json()["timezone_resolution"]["zone_id"] == "Asia/Kolkata"


def test_v2_rejects_timezone_aware_civil_time(tmp_path: Path):
    client = _client(tmp_path)
    body = _body()
    body["birth_profile"]["time"] = "12:30:00+05:30"
    response = client.post("/v2/research-runs", json=body)
    assert response.status_code == 422


def test_numeric_legacy_timezone_accepts_inclusive_bounds():
    for offset in (-12.0, 14.0):
        place = ResearchPlace(
            name="Boundary", latitude=0, longitude=0, timezone=offset
        )
        assert place.timezone == offset


@pytest.mark.parametrize("offset", [-12.0001, 14.0001, math.nan, math.inf, -math.inf])
def test_numeric_legacy_timezone_rejects_out_of_range_and_non_finite(offset: float):
    with pytest.raises(ValidationError):
        ResearchPlace(name="Invalid", latitude=0, longitude=0, timezone=offset)


def test_create_access_log_never_contains_request_body(tmp_path: Path, caplog):
    client = _client(tmp_path)
    body = _body()
    body["question"] = "PRIVATE_QUESTION_SENTINEL"
    body["birth_profile"]["name"] = "PRIVATE_NAME_SENTINEL"
    with caplog.at_level(logging.INFO, logger="jyotish_agent.api"):
        response = client.post("/v2/research-runs", json=body)
    assert response.status_code == 201
    assert "PRIVATE_QUESTION_SENTINEL" not in caplog.text
    assert "PRIVATE_NAME_SENTINEL" not in caplog.text


def test_unknown_run_is_problem_json_404(tmp_path: Path):
    client = _client(tmp_path)
    response = client.get(f"/v2/research-runs/rr_{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
