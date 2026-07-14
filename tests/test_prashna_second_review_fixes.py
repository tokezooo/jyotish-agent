from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from jyotish_agent import interpretations, prashna as prashna_module, prashna_profiles
from jyotish_agent.mcp_facade import JyotishMcpFacade
from jyotish_agent.mcp_server import build_server
from jyotish_agent.prashna import PrashnaFacade
from jyotish_agent.prashna_models import PrashnaAnswerSubmission, PrashnaRequest


PLACE = {
    "name": "Private Orion Office",
    "latitude": 55.7558,
    "longitude": 37.6173,
    "zone_id": "Europe/Moscow",
}
ANCHOR = {"asked_at": "2026-07-14T12:00:00+03:00", "place": PLACE}


def _result(question: str = "What blocks project Alpha?"):
    return PrashnaFacade().calculate(PrashnaRequest(question=question, anchor=ANCHOR))


def test_discovery_keeps_strict_prashna_schema_while_runtime_adapter_is_total(tmp_path: Path):
    tools = asyncio.run(build_server(JyotishMcpFacade(tmp_path / "data", None)).list_tools())
    schema = next(tool.inputSchema for tool in tools if tool.name == "prashna")
    assert schema["required"] == ["request"]
    assert schema["additionalProperties"] is False
    request_ref = schema["properties"]["request"]["$ref"].split("/")[-1]
    request_schema = schema["$defs"][request_ref]
    assert request_schema["additionalProperties"] is False
    assert {"question", "anchor", "capture_now", "place", "anchor_token", "idempotency_key"} <= set(request_schema["properties"])


def test_all_outer_and_nested_mcp_validation_is_sanitized(tmp_path: Path):
    asyncio.run(_invalid_stdio(tmp_path))


async def _invalid_stdio(tmp_path: Path):
    env = {**os.environ, "JYOTISH_AGENT_DATA_ROOT": str(tmp_path / "data")}
    params = StdioServerParameters(command=sys.executable, args=["-m", "jyotish_agent.mcp_server"], env=env)
    calls = (
        {"request": "SECRET WRONG TOP LEVEL"},
        {},
        {"request": {"question": "work project"}, "SECRET_EXTRA": "PRIVATE EXTRA"},
        {"request": {
            "question": "SECRET PROJECT NEBULA work project",
            "capture_now": True,
            "idempotency_key": "second-review-secret-0001",
            "place": {"name": "SECRET PLACE", "latitude": 12.3456, "longitude": 65.4321},
        }},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            results = [await session.call_tool("prashna", call) for call in calls]
    for result in results:
        assert result.isError is False
        assert result.structuredContent["status"] == "needs_input"
        assert result.structuredContent["error_code"] == "INPUT_INVALID"
        serialized = result.model_dump_json()
        for secret in (
            "SECRET WRONG TOP LEVEL", "SECRET_EXTRA", "PRIVATE EXTRA",
            "SECRET PROJECT NEBULA", "SECRET PLACE", "12.3456", "65.4321",
        ):
            assert secret not in serialized


def test_token_replay_rejects_rule_profile_config_and_timezone_drift(monkeypatch):
    facade = PrashnaFacade()
    initial = facade.calculate(PrashnaRequest(question="What blocks project Alpha?", anchor=ANCHOR))

    monkeypatch.setattr(prashna_module, "prashna_rule_profile_sha256", lambda: "0" * 64)
    stale_rule = facade.calculate(PrashnaRequest(question="What blocks project Alpha?", anchor_token=initial.anchor_token))
    assert stale_rule.status == "needs_input" and stale_rule.error_code == "ANCHOR_STALE"
    monkeypatch.undo()

    monkeypatch.setattr(prashna_module, "_prashna_config_sha256", lambda: "1" * 64)
    stale_config = facade.calculate(PrashnaRequest(question="What blocks project Alpha?", anchor_token=initial.anchor_token))
    assert stale_config.status == "needs_input" and stale_config.error_code == "ANCHOR_STALE"
    monkeypatch.undo()

    original = prashna_module._anchor_payload
    def drifted(anchor):
        payload = original(anchor)
        payload["tzdb_fingerprint"] = "sha256:" + "2" * 64
        return payload
    monkeypatch.setattr(prashna_module, "_anchor_payload", drifted)
    stale_tzdb = facade.calculate(PrashnaRequest(question="What blocks project Alpha?", anchor_token=initial.anchor_token))
    assert stale_tzdb.status == "needs_input" and stale_tzdb.error_code == "ANCHOR_STALE"
    assert stale_tzdb.next_action == "create_new_anchor"


def _submission(result, claims, visible_text):
    return PrashnaAnswerSubmission(
        artifact_id=result.artifact_id,
        artifact_sha256=result.artifact_sha256,
        artifact_token=result.artifact_token,
        anchor_token=result.anchor_token,
        normalized_anchor_sha256=result.normalized_anchor_sha256,
        question_fingerprint=result.question_fingerprint,
        current_question_fingerprint=result.current_question_fingerprint,
        question_relation=result.question_relation,
        claims=claims,
        visible_text=visible_text,
    )


def test_complete_answer_submission_requires_every_binding_and_all_visible_text():
    first = _result()
    second = _result("What blocks project Beta?")
    claim = {
        "claim_type": "computed_fact",
        "path": "prashna.topic.primary_house",
        "value": "10",
        "text": "prashna.topic.primary_house = 10",
    }
    valid = _submission(first, [claim], claim["text"])
    assert interpretations.validate_prashna_answer(valid) == []

    omitted = valid.model_dump(mode="json")
    omitted.pop("anchor_token")
    assert interpretations.validate_prashna_answer(omitted) == ["INVALID_ANSWER_SUBMISSION"]

    predictive_empty = valid.model_dump(mode="json")
    predictive_empty["claims"] = []
    predictive_empty["visible_text"] = "Project Alpha will definitely succeed."
    assert interpretations.validate_prashna_answer(predictive_empty) == ["INVALID_ANSWER_SUBMISSION"]

    duplicate = _submission(first, [claim, claim], claim["text"] + "\n" + claim["text"])
    assert interpretations.validate_prashna_answer(duplicate) == ["DUPLICATE_CLAIM:prashna.topic.primary_house"]

    substituted = valid.model_copy(update={
        "artifact_id": second.artifact_id,
        "artifact_sha256": second.artifact_sha256,
        "artifact_token": second.artifact_token,
    })
    assert interpretations.validate_prashna_answer(substituted) == ["ANCHOR_TOKEN_MISMATCH"]


def test_approved_adjudication_cannot_use_duplicate_or_irrelevant_cases(monkeypatch):
    fixtures = prashna_profiles.load_prashna_adjudication_fixtures()
    sources = prashna_profiles.load_prashna_source_map()
    approved_sources = sources.model_copy(update={
        "interpretation_status": "available",
        "review": sources.review.model_copy(update={
            "status": "approved", "reviewer": "reviewer", "reviewer_role": "practitioner",
        }),
    })
    approved = fixtures.model_copy(update={
        "gate_status": "approved", "reviewer": "reviewer", "reviewer_role": "practitioner",
        "cases": tuple(case.model_copy(update={"review_status": "approved"}) for case in fixtures.cases),
    })
    duplicate = approved.model_copy(update={"cases": (approved.cases[0],) * len(approved.cases)})
    irrelevant_case = approved.cases[0].model_copy(update={"criterion": "irrelevant"})
    irrelevant = approved.model_copy(update={"cases": (irrelevant_case, *approved.cases[1:])})
    assert prashna_profiles._adjudication_semantics_valid(duplicate.cases) is False
    assert prashna_profiles._adjudication_semantics_valid(irrelevant.cases) is False
    monkeypatch.setattr(prashna_profiles, "load_prashna_source_map", lambda: approved_sources)
    monkeypatch.setattr(prashna_profiles, "load_prashna_adjudication_fixtures", lambda: duplicate)
    assert prashna_profiles.prashna_source_admission_evidence()["verified"] is False
    monkeypatch.setattr(prashna_profiles, "load_prashna_adjudication_fixtures", lambda: irrelevant)
    assert prashna_profiles.prashna_source_admission_evidence()["verified"] is False
