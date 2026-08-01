from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from jyotish_agent.api import app
from jyotish_agent.doctrine.jaimini_pack import (
    JaiminiReleaseAudit,
    jaimini_compiled_profile_sha256,
    load_jaimini_private_baseline_profile,
    load_jaimini_release_audit,
)
from jyotish_agent.doctrine.jaimini_release import (
    JaiminiRenderedReport,
    validate_jaimini_visible_report,
)
from jyotish_agent.mcp_facade import JyotishMcpFacade
from jyotish_agent.mcp_models import JaiminiFullMcpInput
from jyotish_agent.mcp_server import build_server


ROOT = Path(__file__).parents[2]
AUDIT = ROOT / "docs/evidence/doctrine/jaimini-release.json"


def _profile() -> dict[str, object]:
    return {
        "name": "Private test profile",
        "date": "2000-01-01",
        "time": "12:00:00",
        "birth_time_confidence": "exact",
        "place": {
            "name": "London",
            "latitude": 51.5,
            "longitude": -0.12,
            "timezone": {
                "kind": "iana_with_asserted_offset",
                "zone_id": "Europe/London",
                "asserted_offset_hours": 0,
                "fold": 0,
            },
        },
    }


def _write_private_profile(root: Path) -> Path:
    directory = root / "profiles"
    directory.mkdir(parents=True, mode=0o700)
    path = directory / "vlad.json"
    path.write_text(json.dumps(_profile()), encoding="utf-8")
    path.chmod(0o600)
    return path


def _request(mode: str, locale: str) -> dict[str, object]:
    return {
        "profile": "inline",
        "inline_profile": _profile(),
        "question": "Give a bounded source-bound Jaimini analysis.",
        "mode": mode,
        "locale": locale,
        "topics": ["self", "career", "relationships", "timing"],
        "include_evidence": mode == "inspection",
    }


def _admit_source_bytes(monkeypatch) -> None:
    from jyotish_agent.doctrine import jaimini_pack

    monkeypatch.setattr(
        jaimini_pack.SourceVerifier,
        "verify",
        staticmethod(lambda manifest, root: SimpleNamespace(ok=True)),
    )


def test_available_audit_requires_every_automated_gate_to_pass() -> None:
    payload = json.loads(AUDIT.read_text(encoding="utf-8"))
    JaiminiReleaseAudit.model_validate(payload)
    required = {
        "rule_fixtures",
        "hand_worked_cases",
        "school_conflict_cases",
        "metamorphic_tests",
        "held_out_cases",
        "conversational_e2e_ru",
        "conversational_e2e_en",
        "privacy_adversarial",
        "payload_performance",
        "deep_conversational_e2e",
        "source_bound_private_profile",
    }
    for gate_id in sorted(required):
        for status in ("missing", "failed"):
            candidate = json.loads(json.dumps(payload))
            gate = next(item for item in candidate["gates"] if item["gate_id"] == gate_id)
            gate.update(status=status, evidence=None if status == "missing" else "failure")
            with pytest.raises(ValueError, match="incomplete required gates"):
                JaiminiReleaseAudit.model_validate(candidate)

    candidate = json.loads(json.dumps(payload))
    candidate["external_review_missing"] = False
    with pytest.raises(ValueError, match="specialist gate"):
        JaiminiReleaseAudit.model_validate(candidate)

    candidate = json.loads(json.dumps(payload))
    candidate["public_release_blockers"] = [
        item
        for item in candidate["public_release_blockers"]
        if not item.startswith("timing:")
    ]
    with pytest.raises(ValueError, match="timing must remain"):
        JaiminiReleaseAudit.model_validate(candidate)


def test_release_audit_admits_only_the_restricted_private_profile() -> None:
    packaged = json.loads(
        (ROOT / "src/jyotish_agent/data/doctrine/jaimini-release.json").read_text()
    )
    assert packaged == json.loads(AUDIT.read_text())
    audit = load_jaimini_release_audit(verify_source_bytes=False)
    profile = load_jaimini_private_baseline_profile()

    assert audit.release_id == "full_jaimini_v1"
    assert audit.admission_state == "experimental_full"
    assert audit.compiled_profile_sha256 == jaimini_compiled_profile_sha256()
    assert audit.available is True
    assert audit.blockers == ()
    assert audit.external_review_missing is True
    assert audit.public_release_blockers
    assert profile.karaka_scheme == 7
    assert {claim.topic for claim in profile.claims} == {
        "self",
        "career",
        "relationships",
    }
    assert {item.topic for item in profile.unavailable_topics} == {"timing"}
    assert set(profile.quarantined_rule_ids) == {
        "karakas.tie_policy",
        "svamsa.d9_lagna",
        "special_lagnas.regular_anchor_policy",
        "special_lagnas.regular_rates",
        "special_lagnas.regular_savayava_separation",
        "special_lagnas.sun_epoch",
        "special_lagnas.sunrise_definition",
        "co_lords.resolution",
        "chara_dasha.progression",
        "chara_dasha.gender_semantics",
        "time.boundaries",
    }
    specialist = next(gate for gate in audit.gates if gate.gate_id == "specialist_review")
    assert specialist.status == "missing"


def test_private_profile_rejects_school_blending_duplicates_and_confidence_escape() -> None:
    profile = load_jaimini_private_baseline_profile()
    payload = profile.model_dump(mode="json")
    payload["claims"][0]["source_refs"][0]["source_id"] = (
        "jaimini_sanjay_rath_upadesa_sutras_1997"
    )
    with pytest.raises(ValueError, match="silently blend"):
        type(profile).model_validate(payload)

    payload = profile.model_dump(mode="json")
    payload["required_source_ids"].append(payload["required_source_ids"][0])
    with pytest.raises(ValueError, match="must be unique"):
        type(profile).model_validate(payload)

    payload = profile.model_dump(mode="json")
    payload["confidence_ceiling"] = 0.5
    with pytest.raises(ValueError, match="confidence exceeds"):
        type(profile).model_validate(payload)


def test_quick_full_deep_and_inspection_ru_en_are_additive_private_surfaces(
    tmp_path: Path, monkeypatch
) -> None:
    _admit_source_bytes(monkeypatch)
    facade = JyotishMcpFacade(tmp_path, None)
    results = {}
    for mode in ("quick", "full", "deep", "inspection"):
        for locale in ("ru", "en"):
            parsed = JaiminiFullMcpInput.model_validate(_request(mode, locale))
            result = facade.jaimini_full(parsed)
            results[(mode, locale)] = result
            assert result.surface == "experimental_full"
            assert result.status == "completed"
            assert result.request_mode == mode
            assert result.locale == locale
            assert result.admission_state == "experimental_full"
            assert result.profile == "full_jaimini_private_baseline_v1"
            assert result.report is not None
            assert result.error_code is None
            assert result.external_review_missing is True
            assert len(result.model_dump_json()) < 16_000
            sections = {item["topic"]: item for item in result.report["sections"]}
            assert sections["self"]["status"] == "completed"
            assert sections["career"]["status"] == "completed"
            assert sections["relationships"]["status"] == "completed"
            assert sections["timing"]["status"] == "unavailable"
            assert sections["timing"]["reason_code"] == "CHARA_DASHA_SCHOOL_CONFLICT"
            values = [
                factor["value"]
                for section in sections.values()
                for factor in section["factors"]
            ]
            assert len(values) == 6
            assert all(value for value in values)

    quick = results[("quick", "en")].report
    full = results[("full", "en")].report
    deep = results[("deep", "en")].report
    inspected = results[("inspection", "en")].report
    assert quick is not None and full is not None and deep is not None and inspected is not None
    assert quick["method_notes"] == []
    assert quick["quarantined_rule_ids"] == []
    assert all(
        "symbolic_role" not in factor
        for section in quick["sections"]
        for factor in section["factors"]
    )
    assert full["method_notes"]
    assert full["quarantined_rule_ids"] == []
    assert deep["quarantined_rule_ids"]
    assert "inspection" not in deep
    assert inspected["inspection"]["claims"]
    assert "artifact_token" not in json.dumps(inspected)


def test_inspection_is_the_only_mode_that_accepts_evidence_appendix() -> None:
    invalid = _request("full", "en")
    invalid["include_evidence"] = True
    with pytest.raises(Exception, match="include_evidence"):
        JaiminiFullMcpInput.model_validate(invalid)


def test_malformed_or_secret_input_is_sanitized_and_not_reflected(tmp_path: Path) -> None:
    facade = JyotishMcpFacade(tmp_path, None)
    secret = "private_sources/secret.pdf token=super-secret"
    result = facade.jaimini_full_payload(
        {"question": secret, "mode": "invalid", "unexpected": secret}
    )
    rendered = result.model_dump_json()

    assert result.status == "needs_input"
    assert result.error_code == "INPUT_INVALID"
    assert secret not in rendered
    assert "private_sources" not in rendered
    assert "super-secret" not in rendered


def test_high_stakes_question_stops_before_sources_and_calculation(
    tmp_path: Path, monkeypatch
) -> None:
    from jyotish_agent.doctrine import jaimini_pack

    facade = JyotishMcpFacade(tmp_path, None)
    monkeypatch.setattr(
        jaimini_pack.SourceVerifier,
        "verify",
        staticmethod(lambda *_args: pytest.fail("source bytes were accessed")),
    )
    monkeypatch.setattr(
        facade,
        "jaimini",
        lambda *_args: pytest.fail("chart calculation was executed"),
    )
    payload = _request("deep", "en")
    payload["question"] = "Should I buy stocks for a guaranteed return?"
    result = facade.jaimini_full(JaiminiFullMcpInput.model_validate(payload))

    assert result.status == "unavailable"
    assert result.error_code == "HIGH_STAKES_TOPIC"
    assert result.report is None


def test_private_release_fails_closed_when_source_bytes_do_not_verify(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("JYOTISH_PRIVATE_SOURCES_ROOT", str(tmp_path / "missing"))
    facade = JyotishMcpFacade(tmp_path, None)
    result = facade.jaimini_full(
        JaiminiFullMcpInput.model_validate(_request("full", "en"))
    )
    assert result.status == "unavailable"
    assert result.admission_state == "experimental_full"
    assert result.error_code == "SOURCE_BYTES_UNVERIFIED"
    assert result.report is None


def test_timezone_mismatch_is_a_sanitized_input_result(
    tmp_path: Path, monkeypatch
) -> None:
    _admit_source_bytes(monkeypatch)
    payload = _request("full", "en")
    profile = payload["inline_profile"]
    assert isinstance(profile, dict)
    place = profile["place"]
    assert isinstance(place, dict)
    timezone = place["timezone"]
    assert isinstance(timezone, dict)
    timezone["asserted_offset_hours"] = 5
    result = JyotishMcpFacade(tmp_path, None).jaimini_full(
        JaiminiFullMcpInput.model_validate(payload)
    )

    assert result.status == "needs_input"
    assert result.error_code == "TIMEZONE_OFFSET_MISMATCH"
    assert result.report is None


def test_runtime_verifies_only_the_two_private_profile_sources(monkeypatch) -> None:
    from jyotish_agent.doctrine import jaimini_pack

    verified_ids: set[str] = set()

    def verify(manifest, root):
        del root
        verified_ids.update(source.source_id for source in manifest.sources)
        return SimpleNamespace(ok=True)

    monkeypatch.setattr(
        jaimini_pack.SourceVerifier,
        "verify",
        staticmethod(verify),
    )
    load_jaimini_release_audit()
    assert verified_ids == {
        "jaimini_sutras_b_suryanarain_rao_1949",
        "jaimini_sanjay_rath_upadesa_sutras_1997",
    }


def test_release_loader_rejects_compiled_profile_substitution(monkeypatch) -> None:
    from jyotish_agent.doctrine import jaimini_pack

    monkeypatch.setattr(
        jaimini_pack,
        "jaimini_compiled_profile_sha256",
        lambda: "f" * 64,
    )
    with pytest.raises(ValueError, match="JAIMINI_COMPILED_PROFILE_SUBSTITUTED"):
        jaimini_pack.load_jaimini_release_audit(verify_source_bytes=False)


def test_mcp_discovery_and_report_identity_are_strict_private_and_fast(
    tmp_path: Path, monkeypatch
) -> None:
    _admit_source_bytes(monkeypatch)
    facade = JyotishMcpFacade(tmp_path, None)
    server = build_server(facade)
    tool = server._tool_manager.get_tool("jaimini_full")
    assert tool is not None
    schema = tool.parameters["properties"]["request"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]["mode"]["enum"]) == {
        "quick",
        "full",
        "deep",
        "inspection",
    }
    assert "birth" in schema["properties"]

    request = JaiminiFullMcpInput.model_validate(_request("inspection", "ru"))
    started = time.perf_counter()
    results = [facade.jaimini_full(request) for _ in range(2)]
    assert time.perf_counter() - started < 5.0
    assert results[0] == results[1]
    rendered = json.dumps(results[0].model_dump(mode="json"), sort_keys=True)
    assert ".pdf" not in rendered
    assert "private_sources" not in rendered
    assert "artifact_token" not in rendered


def test_visible_report_mutation_is_detected(tmp_path: Path, monkeypatch) -> None:
    _admit_source_bytes(monkeypatch)
    facade = JyotishMcpFacade(tmp_path, None)
    result = facade.jaimini_full(
        JaiminiFullMcpInput.model_validate(_request("deep", "en"))
    )
    assert result.report is not None
    report = JaiminiRenderedReport.model_validate(result.report)
    assert validate_jaimini_visible_report(report) == []
    changed = report.model_copy(update={"headline": "substituted"})
    assert validate_jaimini_visible_report(changed) == ["VISIBLE_REPORT_MISMATCH"]


def test_http_adapter_exposes_the_same_private_release(
    tmp_path: Path, monkeypatch
) -> None:
    _admit_source_bytes(monkeypatch)
    _write_private_profile(tmp_path)
    monkeypatch.setenv("JYOTISH_AGENT_DATA_ROOT", str(tmp_path))
    payload = _request("inspection", "en")
    payload.pop("inline_profile")
    payload["profile"] = "default"
    response = TestClient(app).post("/v2/doctrine/jaimini/full", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["surface"] == "experimental_full"
    assert body["status"] == "completed"
    assert body["admission_state"] == "experimental_full"
    assert body["profile"] == "full_jaimini_private_baseline_v1"
    assert body["report"]["inspection"]["claims"]
