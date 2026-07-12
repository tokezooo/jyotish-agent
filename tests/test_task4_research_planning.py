from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from jyotish_agent import cli
from jyotish_agent.api import app
from jyotish_agent.planner import build_question_plan, question_plan_bytes
from jyotish_agent.research_models import QuestionIntent
from jyotish_agent.research_service import ResearchService
from jyotish_agent.research_store import ResearchStore, canonical_json


def _op() -> str:
    return f"op_{uuid.uuid4()}"


def _create_body() -> dict:
    return {
        "operation_id": _op(),
        "expected_revision": 0,
        "question": "What career factors and timing should I consider?",
        "birth_profile": {
            "name": "Task 4 Fixture",
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
        "model_version": "answer-model-v1",
        "planner_version": "career-planner-v1",
        "corpus_version": "classics-2026-07-12",
        "contract_version": "2.0",
    }


def _client(tmp_path: Path) -> TestClient:
    app.state.research_service = ResearchService(ResearchStore(tmp_path / "data"))
    return TestClient(app)


def test_career_plan_is_byte_deterministic_and_has_exact_modules():
    intent = QuestionIntent(
        family="career_factors_and_timing", explicit_annual_scope=False
    )

    first = build_question_plan(intent)
    second = build_question_plan(intent)

    assert question_plan_bytes(first) == question_plan_bytes(second)
    assert first.outcome == "supported"
    assert first.charts == ("D1", "D9", "D10")
    assert first.modules == ("shadbala", "transits", "ashtakavarga")
    assert "varshaphal" not in first.modules
    assert "yogas_engine" not in first.modules


def test_explicit_annual_scope_adds_only_varshaphal():
    plan = build_question_plan(
        QuestionIntent(
            family="career_factors_and_timing", explicit_annual_scope=True
        )
    )
    assert plan.modules == (
        "shadbala",
        "transits",
        "ashtakavarga",
        "varshaphal",
    )


def test_unknown_and_composite_intents_do_not_create_executable_plans():
    unknown = build_question_plan(QuestionIntent(family="unknown"))
    composite = build_question_plan(QuestionIntent(family="composite"))
    unsupported = build_question_plan(QuestionIntent(family="unsupported"))
    assert unknown.outcome == composite.outcome == "needs_clarification"
    assert unsupported.outcome == "unsupported"
    assert unknown.charts == composite.charts == unsupported.charts == ()
    assert unknown.modules == composite.modules == unsupported.modules == ()


def test_plan_endpoint_persists_classifier_and_plan_separately(tmp_path: Path):
    client = _client(tmp_path)
    run = client.post("/v2/research-runs", json=_create_body()).json()
    screened = client.post(
        f"/v2/research-runs/{run['run_id']}/screen",
        json={"operation_id": _op(), "expected_revision": run["revision"]},
    ).json()
    prompt_hash = hashlib.sha256(b"career-classifier-prompt-v1").hexdigest()
    response = client.post(
        f"/v2/research-runs/{run['run_id']}/plan",
        json={
            "operation_id": _op(),
            "expected_revision": screened["revision"],
            "intent": {
                "family": "career_factors_and_timing",
                "explicit_annual_scope": False,
            },
            "classifier": {
                "classifier_model": "classifier-model",
                "classifier_version": "2026-07-12",
                "prompt_hash": prompt_hash,
            },
        },
    )
    assert response.status_code == 200, response.text
    planned = response.json()
    assert planned["plan"]["charts"] == ["D1", "D9", "D10"]
    assert planned["classifier"]["prompt_hash"] == prompt_hash

    store = app.state.research_service.store
    intent_row = store.get_question_intent(run["run_id"])
    plan_row = store.get_question_plan(run["run_id"])
    assert intent_row["classifier_model"] == "classifier-model"
    assert intent_row["classifier_version"] == "2026-07-12"
    assert intent_row["classifier_prompt_hash"] == prompt_hash
    assert "classifier" not in plan_row["plan"]
    assert plan_row["plan_hash"] == hashlib.sha256(
        question_plan_bytes(build_question_plan(QuestionIntent(family="career_factors_and_timing")))
    ).hexdigest()


def test_planned_calculation_executes_exact_plan_not_creation_modules(tmp_path: Path):
    client = _client(tmp_path)
    body = _create_body()
    body["calculation_config"] = {
        "reference_date": "2026-07-12",
        "charts": ["D1"],
        "modules": ["yogas_engine", "varshaphal"],
    }
    run = client.post("/v2/research-runs", json=body).json()
    screened = client.post(
        f"/v2/research-runs/{run['run_id']}/screen",
        json={"operation_id": _op(), "expected_revision": run["revision"]},
    ).json()
    planned = client.post(
        f"/v2/research-runs/{run['run_id']}/plan",
        json={
            "operation_id": _op(),
            "expected_revision": screened["revision"],
            "intent": {
                "family": "career_factors_and_timing",
                "explicit_annual_scope": False,
            },
            "classifier": {
                "classifier_model": "fixture",
                "classifier_version": "1",
                "prompt_hash": hashlib.sha256(b"fixture").hexdigest(),
            },
        },
    ).json()
    response = client.post(
        f"/v2/research-runs/{run['run_id']}/calculate",
        json={"operation_id": _op(), "expected_revision": planned["revision"]},
    )
    assert response.status_code == 200, response.text
    calculated = response.json()
    assert calculated["calculation_config"]["charts"] == ["D1", "D9", "D10"]
    assert calculated["calculation_config"]["modules"] == [
        "ashtakavarga",
        "shadbala",
        "transits",
    ]
    assert {"d1", "d9", "d10", "shadbala", "transits", "ashtakavarga"} <= set(
        calculated["facts"]
    )
    assert "yogas_engine" not in calculated["facts"]
    assert "varshaphal" not in calculated["facts"]
    executed_hash = hashlib.sha256(
        canonical_json(calculated["calculation_config"]).encode()
    ).hexdigest()
    evidence = app.state.research_service.store.list_evidence(run["run_id"])
    assert evidence
    assert {item["payload"]["config_hash"] for item in evidence} == {executed_hash}


def test_legacy_calculated_run_without_persisted_plan_cannot_retrieve(tmp_path: Path):
    client = _client(tmp_path)
    run = client.post("/v2/research-runs", json=_create_body()).json()
    screened = client.post(
        f"/v2/research-runs/{run['run_id']}/screen",
        json={"operation_id": _op(), "expected_revision": run["revision"]},
    ).json()
    calculated = client.post(
        f"/v2/research-runs/{run['run_id']}/calculate",
        json={"operation_id": _op(), "expected_revision": screened["revision"]},
    ).json()
    before_events = app.state.research_service.store.list_events(run["run_id"])

    response = client.post(
        f"/v2/research-runs/{run['run_id']}/retrieve",
        json={
            "operation_id": _op(),
            "expected_revision": calculated["revision"],
            "query": "career timing",
            "limit": 8,
        },
    )

    assert response.status_code == 409
    assert "supported plan" in response.json()["detail"]
    assert app.state.research_service.store.list_events(run["run_id"]) == before_events


def test_cli_run_inspect_has_human_and_json_output(tmp_path: Path, monkeypatch, capsys):
    store = ResearchStore(tmp_path / "data")
    service = ResearchService(store)
    request = _create_body()
    from jyotish_agent.research_models import CreateResearchRunRequest

    run = service.create_run(CreateResearchRunRequest.model_validate(request))
    monkeypatch.setenv("JYOTISH_AGENT_DATA_ROOT", str(tmp_path / "data"))

    assert cli.main(["run", "inspect", run.run_id, "--json"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["run"]["run_id"] == run.run_id
    assert body["events"][0]["event_type"] == "research_run.created"

    assert cli.main(["run", "inspect", run.run_id]) == 0
    text = capsys.readouterr().out
    assert run.run_id in text
    assert "revision: 1" in text
