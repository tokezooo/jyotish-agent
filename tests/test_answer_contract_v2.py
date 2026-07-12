from __future__ import annotations

import hashlib
import json
import sqlite3
import urllib.request
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jyotish_agent.answer_contract import (
    adapt_v1_answer,
    is_house_varga_sensitive_fact_path,
    render_answer_markdown,
    validate_answer_contract,
)
from jyotish_agent.api import app
from jyotish_agent import cli
from jyotish_agent.models import AnswerContract, FactRef
from jyotish_agent.research_models import AnswerContractV2
from jyotish_agent.research_service import ResearchService
from jyotish_agent.research_store import ResearchStore, canonical_json, sha256_text


def _id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4()}"


def _run_body(*, confidence: str = "exact") -> dict:
    return {
        "run_id": _id("rr_"),
        "operation_id": _id("op_"),
        "expected_revision": 0,
        "question": "Which career factors should be investigated?",
        "birth_profile": {
            "name": "Authored Fixture",
            "date": "1990-01-01",
            "time": "12:30:00",
            "birth_time_confidence": confidence,
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


def _client(tmp_path: Path, monkeypatch, *, confidence: str = "exact",
            contract_version: str = "2.0") -> tuple[TestClient, ResearchStore, dict]:
    store = ResearchStore(tmp_path / "data")
    app.state.research_service = ResearchService(store)
    client = TestClient(app)
    body = _run_body(confidence=confidence)
    body["contract_version"] = contract_version
    created = client.post("/v2/research-runs", json=body).json()
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


def test_offline_replay_reproduces_projection_claims_and_memo(tmp_path: Path, monkeypatch, capsys):
    client, store, calculated = _client(tmp_path, monkeypatch)
    submitted = client.post(
        f"/v2/research-runs/{calculated['run_id']}/answers",
        json={"operation_id": _id("op_"), "expected_revision": calculated["revision"],
              "answer": _answer(calculated["evidence_ids"][0])},
    ).json()
    monkeypatch.setattr("jyotish_agent.research_service.compute_chart",
                        lambda *a, **k: pytest.fail("replay invoked calculation"))
    response = client.post(f"/v2/research-runs/{calculated['run_id']}/replay")
    assert response.status_code == 200, response.text
    replay = response.json()
    assert replay["offline"] is True
    assert replay["memo_hash"] == submitted["markdown_sha256"]
    assert len(replay["projection_hash"]) == len(replay["claims_hash"]) == 64

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self): return json.dumps(replay).encode()

    def urlopen(request, timeout):
        assert isinstance(request, urllib.request.Request)
        assert request.full_url.endswith(f"/v2/research-runs/{calculated['run_id']}/replay")
        assert request.get_method() == "POST"
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert not hasattr(cli, "ResearchStore")
    assert cli.main(["run", "replay", calculated["run_id"], "--json"]) == 0
    cli_replay = json.loads(capsys.readouterr().out)
    assert cli_replay == replay


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("evidence_hash", "PINNED_PAYLOAD_HASH_MISMATCH"),
        ("answer_hash", "PINNED_PAYLOAD_HASH_MISMATCH"),
        ("claim_hash", "PINNED_PAYLOAD_HASH_MISMATCH"),
        ("evidence_type", "PINNED_CLAIMS_INVALID"),
        ("missing_support", "MISSING_PINNED_MATERIAL"),
        ("missing_claim", "MISSING_PINNED_MATERIAL"),
        ("extra_evidence", "PINNED_ROW_SET_MISMATCH"),
    ],
)
def test_replay_validates_every_pinned_row_and_graph(
    tmp_path: Path, monkeypatch, mutation, expected_code
):
    client, store, calculated = _client(tmp_path, monkeypatch)
    answer = _answer(calculated["evidence_ids"][0])
    client.post(
        f"/v2/research-runs/{calculated['run_id']}/answers",
        json={"operation_id": _id("op_"), "expected_revision": calculated["revision"],
              "answer": answer},
    )
    with sqlite3.connect(store.database_path) as connection:
        if mutation == "evidence_hash":
            connection.execute("DROP TRIGGER evidence_items_no_update")
            connection.execute("UPDATE evidence_items SET payload_json='{}' WHERE evidence_id=?",
                               (calculated["evidence_ids"][-1],))
        elif mutation == "answer_hash":
            connection.execute("DROP TRIGGER answers_no_update")
            connection.execute("UPDATE answers SET payload_json='{}' WHERE run_id=?",
                               (calculated["run_id"],))
        elif mutation == "claim_hash":
            connection.execute("DROP TRIGGER claims_no_update")
            connection.execute("UPDATE claims SET payload_json='{}' WHERE claim_id=?",
                               (answer["claims"][0]["claim_id"],))
        elif mutation == "evidence_type":
            connection.execute("DROP TRIGGER evidence_items_no_update")
            connection.execute(
                "UPDATE evidence_items SET evidence_type='source_fragment' WHERE evidence_id=?",
                (calculated["evidence_ids"][0],),
            )
        elif mutation == "missing_support":
            connection.execute("DROP TRIGGER claim_supports_no_delete")
            connection.execute("DELETE FROM claim_supports WHERE claim_id=?",
                               (answer["claims"][0]["claim_id"],))
        elif mutation == "missing_claim":
            connection.execute("DROP TRIGGER claims_no_delete")
            connection.execute("DELETE FROM claims WHERE claim_id=?",
                               (answer["claims"][0]["claim_id"],))
        else:
            payload = {"path": "unreferenced.extra", "value": "x"}
            connection.execute(
                "INSERT INTO evidence_items VALUES (?, ?, 'computed_fact', ?, ?, ?)",
                (_id("evi_"), calculated["run_id"], canonical_json(payload),
                 sha256_text(canonical_json(payload)), "2026-07-12T00:00:00Z"),
            )
    response = client.post(f"/v2/research-runs/{calculated['run_id']}/replay")
    assert response.status_code == 409
    assert response.json()["error_code"] == expected_code


def test_replay_distinguishes_unsupported_contract_and_version_mismatch(tmp_path: Path, monkeypatch):
    app.state.research_service = ResearchService(ResearchStore(tmp_path / "unsupported"))
    unsupported_client = TestClient(app)
    unsupported = _run_body()
    unsupported["contract_version"] = "3.0"
    response = unsupported_client.post("/v2/research-runs", json=unsupported)
    assert response.status_code == 422
    assert response.json()["error_code"] == "UNSUPPORTED_CONTRACT_VERSION"

    client, store, calculated = _client(tmp_path / "mismatch", monkeypatch)
    client.post(
        f"/v2/research-runs/{calculated['run_id']}/answers",
        json={"operation_id": _id("op_"), "expected_revision": calculated["revision"],
              "answer": _answer(calculated["evidence_ids"][0])},
    )
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("UPDATE question_plans SET planner_version='other' WHERE run_id=?",
                           (calculated["run_id"],))
    response = client.post(f"/v2/research-runs/{calculated['run_id']}/replay")
    assert response.json()["error_code"] == "PINNED_VERSION_MISMATCH"


def test_replay_requires_available_pinned_corpus_version(tmp_path: Path, monkeypatch):
    client, store, calculated = _client(tmp_path, monkeypatch)
    client.post(
        f"/v2/research-runs/{calculated['run_id']}/answers",
        json={"operation_id": _id("op_"), "expected_revision": calculated["revision"],
              "answer": _answer(calculated["evidence_ids"][0])},
    )
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "DELETE FROM available_versions WHERE run_id=? AND version_type='corpus'",
            (calculated["run_id"],),
        )
    response = client.post(f"/v2/research-runs/{calculated['run_id']}/replay")
    assert response.status_code == 409
    body = response.json()
    assert body["error_code"] == "MISSING_PINNED_VERSION"
    assert body["run_id"] == calculated["run_id"]
    assert body["cause"] == "At least one required immutable runtime or corpus version is absent."


def test_replay_rejects_exact_memo_hash_mismatch(tmp_path: Path, monkeypatch):
    client, store, calculated = _client(tmp_path, monkeypatch)
    client.post(
        f"/v2/research-runs/{calculated['run_id']}/answers",
        json={"operation_id": _id("op_"), "expected_revision": calculated["revision"],
              "answer": _answer(calculated["evidence_ids"][0])},
    )
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("DROP TRIGGER answers_no_update")
        row = connection.execute(
            "SELECT payload_json FROM answers WHERE run_id=?", (calculated["run_id"],)
        ).fetchone()
        payload = json.loads(row[0])
        payload["markdown"] += "\ncorrupt"
        encoded = canonical_json(payload)
        connection.execute(
            "UPDATE answers SET payload_json=?, payload_hash=? WHERE run_id=?",
            (encoded, sha256_text(encoded), calculated["run_id"]),
        )
    response = client.post(f"/v2/research-runs/{calculated['run_id']}/replay")
    assert response.status_code == 409
    body = response.json()
    assert body["error_code"] == "MEMO_HASH_MISMATCH"
    assert body["cause"] == "Re-rendered memo bytes differ from the immutable answer artifact."


@pytest.mark.parametrize("target", ["intent", "plan"])
def test_replay_rejects_coordinated_planning_projection_and_self_hash_tamper(
    tmp_path: Path, monkeypatch, target
):
    client, store, calculated = _client(tmp_path, monkeypatch)
    client.post(
        f"/v2/research-runs/{calculated['run_id']}/answers",
        json={"operation_id": _id("op_"), "expected_revision": calculated["revision"],
              "answer": _answer(calculated["evidence_ids"][0])},
    )
    with sqlite3.connect(store.database_path) as connection:
        if target == "intent":
            value = {"family": "unknown", "explicit_annual_scope": False}
            encoded = canonical_json(value)
            connection.execute(
                """UPDATE question_intents
                   SET intent_json=?, intent_hash=?, classifier_model='tampered',
                       classifier_version='tampered', classifier_prompt_hash=?
                   WHERE run_id=?""",
                (encoded, sha256_text(encoded), "f" * 64, calculated["run_id"]),
            )
        else:
            row = store.get_question_plan(calculated["run_id"])
            value = {**row["plan"], "fact_paths": ["tampered."]}
            encoded = canonical_json(value)
            connection.execute(
                "UPDATE question_plans SET plan_json=?, plan_hash=? WHERE run_id=?",
                (encoded, sha256_text(encoded), calculated["run_id"]),
            )
    response = client.post(f"/v2/research-runs/{calculated['run_id']}/replay")
    assert response.status_code == 409
    assert response.json()["error_code"] == "PINNED_PLANNING_MISMATCH"


def test_replay_requires_exactly_one_hash_chained_planned_event(tmp_path: Path, monkeypatch):
    client, store, calculated = _client(tmp_path, monkeypatch)
    submitted = client.post(
        f"/v2/research-runs/{calculated['run_id']}/answers",
        json={"operation_id": _id("op_"), "expected_revision": calculated["revision"],
              "answer": _answer(calculated["evidence_ids"][0])},
    ).json()
    planned_payload = next(
        json.loads(row["payload_json"])
        for row in store.list_events(calculated["run_id"])
        if row["event_type"] == "research_run.planned"
    )
    store.append_event(
        calculated["run_id"], operation_id=_id("op_"),
        expected_revision=submitted["revision"], event_type="research_run.planned",
        payload={**planned_payload, "status": "validated"}, next_status="validated",
        producer="pytest", producer_version="1",
    )
    response = client.post(f"/v2/research-runs/{calculated['run_id']}/replay")
    assert response.status_code == 409
    assert response.json()["error_code"] == "PINNED_PLANNING_MISMATCH"


def test_approximate_birth_time_records_exact_seven_point_sweep(tmp_path: Path, monkeypatch):
    _client_api, store, calculated = _client(tmp_path, monkeypatch, confidence="approximate")
    assert calculated["sensitivity"]
    assert {tuple(item["offsets_minutes"]) for item in calculated["sensitivity"]} == {
        (-15, -10, -5, 0, 5, 10, 15)
    }
    assert {item["stability"] for item in calculated["sensitivity"]} == {"stable"}
    evidence = store.list_evidence(calculated["run_id"])
    assert any(item["evidence_type"] == "sensitivity_fact" for item in evidence)


def test_offline_replay_detects_projection_divergence(tmp_path: Path, monkeypatch):
    client, store, calculated = _client(tmp_path, monkeypatch)
    client.post(
        f"/v2/research-runs/{calculated['run_id']}/answers",
        json={"operation_id": _id("op_"), "expected_revision": calculated["revision"],
              "answer": _answer(calculated["evidence_ids"][0])},
    )
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("UPDATE research_runs SET question='diverged' WHERE run_id=?",
                           (calculated["run_id"],))
    response = client.post(f"/v2/research-runs/{calculated['run_id']}/replay")
    assert response.status_code == 409
    assert response.json()["error_code"] == "PROJECTION_HASH_MISMATCH"


@pytest.mark.parametrize("phrase", [
    "This is likely.", "Likelihood is high.", "There is a 40% chance.",
    "A rectified time would help.", "After the chart was rectified.",
    "This is probably relevant.", "That outcome is unlikely.", "The odds are high.",
])
def test_answer_policy_rejects_probability_and_rectification_variants(phrase):
    evidence_id = _id("evi_")
    payload = _answer(evidence_id)
    payload["claims"][1]["text"] = phrase
    answer = AnswerContractV2.model_validate(payload)
    evidence = [{"evidence_id": evidence_id, "evidence_type": "computed_fact",
                 "payload": {"path": "d1.Sun.sign", "value": "Aries"}}]
    assert any("prohibited" in item for item in validate_answer_contract(answer, evidence))


@pytest.mark.parametrize("phrase", [
    "This may be relevant.", "This is possible but uncertain.",
    "Confidence is limited by the recorded time.",
])
def test_answer_policy_allows_nonprobabilistic_uncertainty_language(phrase):
    evidence_id = _id("evi_")
    payload = _answer(evidence_id)
    payload["claims"][1]["text"] = phrase
    answer = AnswerContractV2.model_validate(payload)
    evidence = [{"evidence_id": evidence_id, "evidence_type": "computed_fact",
                 "payload": {"path": "d1.Sun.sign", "value": "Aries"}}]
    assert validate_answer_contract(answer, evidence) == []


@pytest.mark.parametrize("path", [
    "d1.Sun.house", "bhava.d1.10.lord", "lagnas.d1.sign",
    "bhava.d9.10.lord", "bhava.d10.10.sign", "lagnas.d9.sign", "lagnas.d10.sign",
])
def test_unknown_time_blocks_all_actual_house_and_varga_path_families(path):
    evidence_id = _id("evi_")
    answer = AnswerContractV2.model_validate(_answer(evidence_id))
    evidence = [{"evidence_id": evidence_id, "evidence_type": "computed_fact",
                 "payload": {"path": path, "value": "Aries"}}]
    violations = validate_answer_contract(answer, evidence, birth_time_confidence="unknown")
    assert any("house/varga" in item for item in violations)


def test_sensitive_fact_path_predicate_is_centralized_and_does_not_overblock_d1_signs():
    assert is_house_varga_sensitive_fact_path("d1.Sun.house")
    assert is_house_varga_sensitive_fact_path("bhava.d1.10.lord")
    assert is_house_varga_sensitive_fact_path("lagnas.d1.sign")
    assert not is_house_varga_sensitive_fact_path("d1.Sun.sign")

    evidence_id = _id("evi_")
    answer = AnswerContractV2.model_validate(_answer(evidence_id))
    evidence = [{"evidence_id": evidence_id, "evidence_type": "computed_fact",
                 "payload": {"path": "d1.Sun.sign", "value": "Aries"}}]
    assert validate_answer_contract(
        answer, evidence, birth_time_confidence="unknown"
    ) == []


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
    body = response.json()
    assert body["error_code"] == "UNSUPPORTED_SCHEMA_VERSION"
    assert body["run_id"] == calculated["run_id"]
    assert body["stage"] == "answer"
    assert body["retryable"] is False
