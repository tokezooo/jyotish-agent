from __future__ import annotations

import sqlite3
import uuid
import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jyotish_agent.api import app
from jyotish_agent.research_service import ResearchService
from jyotish_agent.research_store import OptimisticConflict, ResearchStore
from jyotish_agent.research_models import CreateResearchRunRequest


def _operation_id() -> str:
    return f"op_{uuid.uuid4()}"


def _run_body(question: str = "Which career factors should be investigated?") -> dict:
    return {
        "operation_id": _operation_id(),
        "expected_revision": 0,
        "question": question,
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


def _client(tmp_path: Path) -> tuple[TestClient, ResearchStore]:
    store = ResearchStore(tmp_path / "data")
    app.state.research_service = ResearchService(store)
    return TestClient(app), store


def _create(client: TestClient, question: str = "Which career factors?") -> dict:
    response = client.post("/v2/research-runs", json=_run_body(question))
    assert response.status_code == 201, response.text
    return response.json()


def test_create_idempotency_uses_client_payload_across_date_rollover(tmp_path: Path):
    now = [dt.datetime(2026, 7, 12, 23, 59, tzinfo=dt.UTC)]
    service = ResearchService(ResearchStore(tmp_path / "data"), clock=lambda: now[0])
    body = _run_body()
    body["calculation_config"] = {}
    request = CreateResearchRunRequest.model_validate(body)

    first = service.create_run(request)
    now[0] = dt.datetime(2026, 7, 13, 0, 1, tzinfo=dt.UTC)
    replayed = service.create_run(request)

    assert replayed == first
    assert first.reference_date.isoformat() == "2026-07-12"
    changed = request.model_copy(
        update={
            "calculation_config": request.calculation_config.model_copy(
                update={"reference_date": dt.date(2026, 7, 13)}
            )
        }
    )
    with pytest.raises(OptimisticConflict):
        service.create_run(changed)


def test_create_defaults_to_server_owned_contract_2(tmp_path: Path):
    client, _store = _client(tmp_path)
    body = _run_body()
    body.pop("contract_version")
    response = client.post("/v2/research-runs", json=body)
    assert response.status_code == 201
    assert response.json()["contract_version"] == "2.0"


def _plan(client: TestClient, run_id: str, expected_revision: int) -> dict:
    response = client.post(
        f"/v2/research-runs/{run_id}/plan",
        json={
            "operation_id": _operation_id(),
            "expected_revision": expected_revision,
            "intent": {
                "family": "career_factors_and_timing",
                "explicit_annual_scope": False,
            },
            "classifier": {
                "classifier_model": "test-classifier",
                "classifier_version": "1",
                "prompt_hash": "a" * 64,
            },
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_screen_is_idempotent_and_stale_new_operation_conflicts(tmp_path: Path):
    client, store = _client(tmp_path)
    run = _create(client)
    operation_id = _operation_id()
    body = {"operation_id": operation_id, "expected_revision": 1}

    first = client.post(f"/v2/research-runs/{run['run_id']}/screen", json=body)
    second = client.post(f"/v2/research-runs/{run['run_id']}/screen", json=body)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json() == {
        "run_id": run["run_id"],
        "operation_id": operation_id,
        "revision": 2,
        "backend_seq": 2,
        "event_hash": first.json()["event_hash"],
        "status": "screened_safe",
        "safe": True,
        "category": None,
        "redirect": None,
    }
    assert len(store.list_events(run["run_id"])) == 2

    stale = client.post(
        f"/v2/research-runs/{run['run_id']}/screen",
        json={"operation_id": _operation_id(), "expected_revision": 1},
    )
    changed_replay = client.post(
        f"/v2/research-runs/{run['run_id']}/screen",
        json={"operation_id": operation_id, "expected_revision": 2},
    )
    assert stale.status_code == changed_replay.status_code == 409
    assert len(store.list_events(run["run_id"])) == 2


def test_unsafe_screen_is_terminal_and_blocks_calculation(tmp_path: Path, monkeypatch):
    client, store = _client(tmp_path)
    run = _create(client, "When will I die?")
    operation_id = _operation_id()
    screen_body = {"operation_id": operation_id, "expected_revision": 1}
    screened = client.post(
        f"/v2/research-runs/{run['run_id']}/screen",
        json=screen_body,
    )
    assert screened.status_code == 200
    assert screened.json()["safe"] is False
    assert screened.json()["status"] == "refused_unsafe"
    assert screened.json()["category"] == "deterministic_harm"
    assert screened.json()["redirect"]
    repeated = client.post(
        f"/v2/research-runs/{run['run_id']}/screen", json=screen_body
    )
    assert repeated.status_code == 200
    assert repeated.json() == screened.json()

    called = False

    def forbidden_compute(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("unsafe flow must not calculate")

    monkeypatch.setattr("jyotish_agent.research_service.compute_chart", forbidden_compute)
    calculated = client.post(
        f"/v2/research-runs/{run['run_id']}/calculate",
        json={"operation_id": _operation_id(), "expected_revision": 2},
    )
    assert calculated.status_code == 409
    assert called is False
    assert len(store.list_events(run["run_id"])) == 2


def test_calculation_persists_typed_immutable_evidence_once(tmp_path: Path, monkeypatch):
    client, store = _client(tmp_path)
    run = _create(client)
    screened = client.post(
        f"/v2/research-runs/{run['run_id']}/screen",
        json={"operation_id": _operation_id(), "expected_revision": 1},
    ).json()
    planned = _plan(client, run["run_id"], screened["revision"])

    calls = 0

    def fake_compute(_profile, *, reference_date, config):
        nonlocal calls
        calls += 1
        assert reference_date == (2026, 7, 12)
        assert config.ayanamsa == "LAHIRI"
        return {
            "normalized_input": {"fixture": True},
            "calculation_config": {"ayanamsa": "LAHIRI"},
            "facts": {
                "ascendant": {"sign": "Pisces", "degrees": 1e-7},
                "aspects": {"Saturn": {"aspects_planets": ["Moon"]}},
            },
            "provenance": {"engine": "PyJHora", "engine_version": "4.8.6"},
        }

    monkeypatch.setattr("jyotish_agent.research_service.compute_chart", fake_compute)
    operation_id = _operation_id()
    body = {"operation_id": operation_id, "expected_revision": planned["revision"]}
    first = client.post(f"/v2/research-runs/{run['run_id']}/calculate", json=body)
    second = client.post(f"/v2/research-runs/{run['run_id']}/calculate", json=body)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    result = first.json()
    assert result["status"] == "calculated"
    assert result["revision"] == 4
    assert result["backend_seq"] == 4
    assert result["facts"]["ascendant"]["sign"] == "Pisces"
    assert calls == 1

    evidence = store.list_evidence(run["run_id"])
    assert len(evidence) == 3
    by_path = {item["payload"]["path"]: item["payload"] for item in evidence}
    assert by_path["ascendant.sign"]["value"] == "Pisces"
    assert by_path["ascendant.sign"]["value_type"] == "string"
    assert by_path["ascendant.degrees"]["value"] == 1e-7
    assert by_path["ascendant.degrees"]["value_type"] == "number"
    assert by_path["aspects.Saturn.Moon"]["value"] is True
    assert by_path["aspects.Saturn.Moon"]["value_type"] == "boolean"
    for payload in by_path.values():
        assert len(payload["profile_hash"]) == 64
        assert len(payload["config_hash"]) == 64
        assert len(payload["engine_hash"]) == 64

    with sqlite3.connect(store.database_path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE evidence_items SET evidence_type='tampered' WHERE run_id=?",
                (run["run_id"],),
            )
