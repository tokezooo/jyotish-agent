from __future__ import annotations

import hashlib
import sqlite3
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jyotish_agent.answer_contract import (
    adapt_v1_answer,
    render_answer_markdown,
    validate_answer_contract,
)
from jyotish_agent.api import app
from jyotish_agent.models import AnswerContract, FactRef
from jyotish_agent.research_models import AnswerContractV2
from jyotish_agent.research_service import ResearchService
from jyotish_agent.research_store import ResearchStore


def _id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4()}"


def _run_body() -> dict:
    return {
        "run_id": _id("rr_"),
        "operation_id": _id("op_"),
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


def _client(tmp_path: Path, monkeypatch) -> tuple[TestClient, ResearchStore, dict]:
    store = ResearchStore(tmp_path / "data")
    app.state.research_service = ResearchService(store)
    client = TestClient(app)
    created = client.post("/v2/research-runs", json=_run_body()).json()
    screened = client.post(
        f"/v2/research-runs/{created['run_id']}/screen",
        json={"operation_id": _id("op_"), "expected_revision": 1},
    ).json()
    planned = client.post(
        f"/v2/research-runs/{created['run_id']}/plan",
        json={
            "operation_id": _id("op_"),
            "expected_revision": screened["revision"],
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
    ).json()

    def fake_compute(_profile, *, reference_date, config):
        return {
            "normalized_input": {"fixture": True},
            "calculation_config": {"ayanamsa": config.ayanamsa},
            "facts": {"ascendant": {"sign": "Pisces", "degrees": 25.5}},
            "provenance": {"engine": "PyJHora", "engine_version": "4.8.6"},
        }

    monkeypatch.setattr("jyotish_agent.research_service.compute_chart", fake_compute)
    calculated = client.post(
        f"/v2/research-runs/{created['run_id']}/calculate",
        json={
            "operation_id": _id("op_"),
            "expected_revision": planned["revision"],
        },
    ).json()
    return client, store, calculated


def _answer(evidence_id: str, *, run_status: str = "calculated") -> dict:
    computed_id = _id("cl_")
    return {
        "schema_version": "2.0",
        "run_status": run_status,
        "title": "Career research memo",
        "claims": [
            {
                "claim_type": "computed",
                "claim_id": computed_id,
                "materiality": "major",
                "confidence": 0.95,
                "supports": [evidence_id],
                "caveats": [],
                "conflicts": [],
            },
            {
                "claim_type": "synthesis",
                "claim_id": _id("cl_"),
                "materiality": "supporting",
                "confidence": 0.7,
                "supports": [computed_id],
                "caveats": ["Symbolic interpretation, not a deterministic outcome."],
                "conflicts": [],
                "text": "The computed ascendant can frame a reflective career inquiry.",
            },
        ],
        "limitations": ["This provisional memo uses computed evidence only."],
        "followups": ["Compare the D10 evidence next."],
    }


def test_claim_dag_validates_support_types_cycles_and_leaf_termination():
    computed_evidence = {
        "evidence_id": _id("evi_"),
        "evidence_type": "computed_fact",
        "payload": {"path": "ascendant.sign", "value": "Pisces", "value_type": "string"},
    }
    valid = AnswerContractV2.model_validate(_answer(computed_evidence["evidence_id"]))
    assert validate_answer_contract(valid, [computed_evidence]) == []

    missing = AnswerContractV2.model_validate(_answer(_id("evi_")))
    assert any("support does not exist" in item for item in validate_answer_contract(missing, [computed_evidence]))

    wrong_type = _answer(computed_evidence["evidence_id"])
    source_evidence = {**computed_evidence, "evidence_type": "source_fragment"}
    wrong = AnswerContractV2.model_validate(wrong_type)
    assert any("computed_fact" in item for item in validate_answer_contract(wrong, [source_evidence]))

    cycle = _answer(computed_evidence["evidence_id"])
    first, second = cycle["claims"]
    first["claim_type"] = "synthesis"
    first["text"] = "First synthesis."
    first["supports"] = [second["claim_id"]]
    second["supports"] = [first["claim_id"]]
    cyclic = AnswerContractV2.model_validate(cycle)
    violations = validate_answer_contract(cyclic, [computed_evidence])
    assert any("cycle" in item for item in violations)
    assert any("terminate" in item for item in violations)


def test_renderer_uses_structured_computed_evidence_and_is_deterministic():
    evidence_id = _id("evi_")
    answer = AnswerContractV2.model_validate(_answer(evidence_id))
    evidence = [{
        "evidence_id": evidence_id,
        "evidence_type": "computed_fact",
        "payload": {"path": "ascendant.sign", "value": "Pisces", "value_type": "string"},
    }]
    first = render_answer_markdown(answer, evidence)
    second = render_answer_markdown(answer, evidence)
    assert first == second
    assert "# Career research memo" in first.markdown
    assert "`ascendant.sign` = `Pisces`" in first.markdown
    assert "The computed ascendant can frame" in first.markdown
    assert first.sha256 == hashlib.sha256(first.markdown.encode()).hexdigest()


def test_v1_adapter_only_emits_legacy_computed_claim_with_missing_provenance():
    legacy = AnswerContract(
        summary="Pisces rising.",
        facts_used=[FactRef(path="ascendant.sign", value="Pisces")],
        uncertainty=["Legacy contract."],
        followups=[],
    )
    records = adapt_v1_answer(legacy)
    assert {record["claim_type"] for record in records} == {"legacy_computed_claim"}
    assert all(record["provenance_status"] == "missing" for record in records)


def test_submit_answer_persists_immutable_canonical_artifact(tmp_path: Path, monkeypatch):
    client, store, calculated = _client(tmp_path, monkeypatch)
    evidence_id = calculated["evidence_ids"][0]
    operation_id = _id("op_")
    body = {
        "operation_id": operation_id,
        "expected_revision": calculated["revision"],
        "answer": _answer(evidence_id),
    }
    first = client.post(
        f"/v2/research-runs/{calculated['run_id']}/answers", json=body
    )
    second = client.post(
        f"/v2/research-runs/{calculated['run_id']}/answers", json=body
    )
    assert first.status_code == second.status_code == 200, first.text
    assert first.json() == second.json()
    result = first.json()
    assert result["valid"] is True
    assert result["status"] == "validated"
    assert result["answer_id"].startswith("ans_")
    assert result["markdown"].startswith("# Career research memo")
    assert result["markdown_sha256"] == hashlib.sha256(
        result["markdown"].encode()
    ).hexdigest()
    assert result["repair_remaining"] == 1
    assert len(store.list_answer_attempts(calculated["run_id"])) == 1
    assert len(store.list_answers(calculated["run_id"])) == 1

    with sqlite3.connect(store.database_path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE answers SET schema_version='tampered' WHERE answer_id=?",
                (result["answer_id"],),
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE claim_supports SET support_type='tampered' WHERE claim_id=?",
                (body["answer"]["claims"][0]["claim_id"],),
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "DELETE FROM claim_supports WHERE claim_id=?",
                (body["answer"]["claims"][0]["claim_id"],),
            )


def test_one_repair_budget_is_persisted_and_exhausted(tmp_path: Path, monkeypatch):
    client, store, calculated = _client(tmp_path, monkeypatch)
    bad = _answer(_id("evi_"))
    first = client.post(
        f"/v2/research-runs/{calculated['run_id']}/answers",
        json={
            "operation_id": _id("op_"),
            "expected_revision": calculated["revision"],
            "answer": bad,
        },
    )
    assert first.status_code == 200
    assert first.json()["valid"] is False
    assert first.json()["status"] == "answer_needs_repair"
    assert first.json()["repair_remaining"] == 1

    bad["run_status"] = "answer_needs_repair"
    second = client.post(
        f"/v2/research-runs/{calculated['run_id']}/answers",
        json={
            "operation_id": _id("op_"),
            "expected_revision": first.json()["revision"],
            "answer": bad,
        },
    )
    assert second.status_code == 200
    assert second.json()["valid"] is False
    assert second.json()["status"] == "answer_repair_exhausted"
    assert second.json()["repair_remaining"] == 0
    assert len(store.list_answer_attempts(calculated["run_id"])) == 2
    assert store.list_answers(calculated["run_id"]) == []

    third = client.post(
        f"/v2/research-runs/{calculated['run_id']}/answers",
        json={
            "operation_id": _id("op_"),
            "expected_revision": second.json()["revision"],
            "answer": {**bad, "run_status": "answer_repair_exhausted"},
        },
    )
    assert third.status_code == 409
    assert len(store.list_answer_attempts(calculated["run_id"])) == 2


def test_unknown_major_schema_version_has_stable_error_code(tmp_path: Path, monkeypatch):
    client, _store, calculated = _client(tmp_path, monkeypatch)
    answer = _answer(calculated["evidence_ids"][0])
    answer["schema_version"] = "3.0"
    response = client.post(
        f"/v2/research-runs/{calculated['run_id']}/answers",
        json={
            "operation_id": _id("op_"),
            "expected_revision": calculated["revision"],
            "answer": answer,
        },
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "UNSUPPORTED_SCHEMA_VERSION"
