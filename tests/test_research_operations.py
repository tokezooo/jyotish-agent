from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jyotish_agent.api import app
from jyotish_agent.research_service import ResearchService
from jyotish_agent.research_store import ResearchStore


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
        "contract_version": "1.0",
    }


def _client(tmp_path: Path) -> tuple[TestClient, ResearchStore]:
    store = ResearchStore(tmp_path / "data")
    app.state.research_service = ResearchService(store)
    return TestClient(app), store


def _create(client: TestClient, question: str = "Which career factors?") -> dict:
    response = client.post("/v2/research-runs", json=_run_body(question))
    assert response.status_code == 201, response.text
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
                "ascendant": {"sign": "Pisces", "degrees": 12.5},
                "aspects": {"Saturn": {"aspects_planets": ["Moon"]}},
            },
            "provenance": {"engine": "PyJHora", "engine_version": "4.8.6"},
        }

    monkeypatch.setattr("jyotish_agent.research_service.compute_chart", fake_compute)
    operation_id = _operation_id()
    body = {"operation_id": operation_id, "expected_revision": screened["revision"]}
    first = client.post(f"/v2/research-runs/{run['run_id']}/calculate", json=body)
    second = client.post(f"/v2/research-runs/{run['run_id']}/calculate", json=body)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    result = first.json()
    assert result["status"] == "calculated"
    assert result["revision"] == 3
    assert result["backend_seq"] == 3
    assert result["facts"]["ascendant"]["sign"] == "Pisces"
    assert calls == 1

    evidence = store.list_evidence(run["run_id"])
    assert len(evidence) == 3
    by_path = {item["payload"]["path"]: item["payload"] for item in evidence}
    assert by_path["ascendant.sign"]["value"] == "Pisces"
    assert by_path["ascendant.sign"]["value_type"] == "string"
    assert by_path["ascendant.degrees"]["value"] == 12.5
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
