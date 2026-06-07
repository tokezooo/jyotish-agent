"""Integration tests for the FastAPI endpoints via TestClient.

Validation / error / health tests run engine-free. Only tests that actually compute
a chart are gated on PyJHora being installed."""

from __future__ import annotations

import importlib.util

import pytest
from fastapi.testclient import TestClient

from jyotish_agent.api import app
from jyotish_agent.config import ephemeris_mode

client = TestClient(app)

_HAS_JHORA = importlib.util.find_spec("jhora") is not None
requires_engine = pytest.mark.skipif(
    not _HAS_JHORA, reason="PyJHora not installed; run `uv sync`"
)

_VALID_PROFILE = {
    "name": "Chennai Test",
    "date": "1990-01-01",
    "time": "12:30:00",
    "place": {
        "name": "Chennai",
        "latitude": 13.0827,
        "longitude": 80.2707,
        "timezone": 5.5,
    },
}

_EXPECTED_TOP_KEYS = {
    "normalized_input",
    "calculation_config",
    "facts",
    "provenance",
    "warnings",
    "facts_token",
}
_EXPECTED_FACT_KEYS = {
    "ascendant",
    "houses",
    "lagnas",
    "bhava",
    "aspects",
    "yogas",
    "d1",
    "d9",
    "panchanga",
    "vimshottari",
}


def _compute_body(**config_over) -> dict:
    config = {"reference_date": "2026-06-07"}
    config.update(config_over)
    return {"birth_profile": _VALID_PROFILE, "config": config}


# --- engine-free: validation, errors, health ---


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "engine_version" in body


def test_validate_endpoint():
    r = client.post("/birth-profiles/validate", json=_VALID_PROFILE)
    assert r.status_code == 200
    body = r.json()
    assert body["normalized_profile"]["date"] == "1990-01-01"
    assert isinstance(body["warnings"], list)


def test_invalid_date_returns_problem_json():
    bad = {**_VALID_PROFILE, "date": "2025-02-30"}
    r = client.post("/birth-profiles/validate", json=bad)
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert {"problem", "cause", "fix"} <= set(body)
    assert "date" in body["invalid_fields"]


def test_missing_timezone_returns_422():
    place = {k: v for k, v in _VALID_PROFILE["place"].items() if k != "timezone"}
    bad = {**_VALID_PROFILE, "place": place}
    r = client.post("/birth-profiles/validate", json=bad)
    assert r.status_code == 422
    assert any("timezone" in f for f in r.json()["invalid_fields"])


def test_extra_field_name_not_reflected():
    bad = {**_VALID_PROFILE, "leaky_secret_field": "x"}
    r = client.post("/birth-profiles/validate", json=bad)
    assert r.status_code == 422
    assert "leaky_secret_field" not in r.text
    assert "(unexpected field)" in r.json()["invalid_fields"]


def test_error_body_does_not_leak_birth_data():
    bad = {**_VALID_PROFILE, "date": "2025-02-30", "name": "SECRET_NAME"}
    r = client.post("/birth-profiles/validate", json=bad)
    assert "SECRET_NAME" not in r.text
    assert "2025-02-30" not in r.text


def test_internal_value_error_is_500_not_422(monkeypatch):
    # A non-ConfigError raised inside compute must NOT be relabeled as a 422, and its
    # message (which could carry birth-derived data) must not reach the body.
    import jyotish_agent.api as api_mod

    def _boom(*a, **k):
        raise ValueError("INTERNAL_SECRET_1990-01-01")

    monkeypatch.setattr(api_mod, "compute_chart", _boom)
    local = TestClient(app, raise_server_exceptions=False)
    r = local.post("/charts/compute", json=_compute_body())
    assert r.status_code == 500
    assert r.headers["content-type"].startswith("application/problem+json")
    assert "INTERNAL_SECRET" not in r.text


_FACTS = {"ascendant": {"sign": "Pisces", "degrees": 25.46}}


def _signed(facts: dict) -> str:
    from jyotish_agent.signing import sign_facts

    return sign_facts(facts)


def test_validate_answer_accepts_grounded_citation():
    r = client.post(
        "/answers/validate",
        json={
            "answer": {
                "summary": "Pisces rising.",
                "facts_used": [{"path": "ascendant.sign", "value": "Pisces"}],
            },
            "facts": _FACTS,
            "facts_token": _signed(_FACTS),
        },
    )
    assert r.status_code == 200
    assert r.json() == {"valid": True, "violations": []}


def test_validate_answer_rejects_invented_citation():
    r = client.post(
        "/answers/validate",
        json={
            "answer": {
                "summary": "Leo rising.",
                "facts_used": [{"path": "ascendant.sign", "value": "Leo"}],
            },
            "facts": _FACTS,
            "facts_token": _signed(_FACTS),
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False
    assert len(body["violations"]) == 1


def test_validate_answer_rejects_prose_contradiction():
    # facts_used is honest (or empty of the bad claim), but the prose contradicts facts.
    facts = {"d1": [{"planet": "Sun", "sign": "Sagittarius", "degrees": 16.0}]}
    r = client.post(
        "/answers/validate",
        json={
            "answer": {
                "summary": "Sun in Leo dominates the chart.",
                "facts_used": [{"path": "d1.Sun.sign", "value": "Sagittarius"}],
            },
            "facts": facts,
            "facts_token": _signed(facts),
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False
    assert any("Sun in Leo" in v for v in body["violations"])


def test_validate_answer_rejects_forged_facts():
    # Agent forges a facts block (Sun in Leo) and cites it; without a valid token for
    # THOSE facts, the integrity check fails. This is the core anti-self-certification.
    forged = {"d1": [{"planet": "Sun", "sign": "Leo", "degrees": 1.0}]}
    r = client.post(
        "/answers/validate",
        json={
            "answer": {
                "summary": "Sun in Leo.",
                "facts_used": [{"path": "d1.Sun.sign", "value": "Leo"}],
            },
            "facts": forged,
            "facts_token": _signed(_FACTS),  # token for different facts
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False
    assert "integrity" in body["violations"][0]


def test_validate_answer_requires_nonempty_citations():
    r = client.post(
        "/answers/validate",
        json={
            "answer": {"summary": "A reading.", "facts_used": []},
            "facts": _FACTS,
            "facts_token": _signed(_FACTS),
        },
    )
    assert r.status_code == 422  # min_length=1 on facts_used


def test_screen_endpoint_flags_unsafe_and_allows_safe():
    bad = client.post("/questions/screen", json={"question": "When will I die?"})
    assert bad.status_code == 200
    body = bad.json()
    assert body["safe"] is False
    assert body["category"] == "deterministic_harm"
    assert body["redirect"]

    ok = client.post("/questions/screen", json={"question": "My career signals?"})
    assert ok.json() == {"safe": True, "category": None, "redirect": None}


# --- engine-backed: real chart computation ---


@requires_engine
def test_compute_happy_path():
    r = client.post("/charts/compute", json=_compute_body())
    assert r.status_code == 200
    body = r.json()
    assert set(body) == _EXPECTED_TOP_KEYS
    assert set(body["facts"]) == _EXPECTED_FACT_KEYS
    assert body["calculation_config"]["ayanamsa"] == "LAHIRI"
    assert body["calculation_config"]["reference_date"] == [2026, 6, 7]
    assert len(body["facts"]["d1"]) == 9
    assert body["facts"]["panchanga"]["weekday"]["name"] == "Monday"
    assert body["facts"]["ascendant"]["sign"] is not None


@requires_engine
def test_compute_default_reference_date():
    # Omit reference_date -> route defaults to today(); must still 200 with a period.
    r = client.post("/charts/compute", json={"birth_profile": _VALID_PROFILE})
    assert r.status_code == 200
    assert "vimshottari" in r.json()["facts"]


@requires_engine
def test_compute_extra_chart_and_token_roundtrips():
    r = client.post("/charts/compute", json=_compute_body(charts=["D9", "D10"]))
    assert r.status_code == 200
    cc = r.json()
    assert "d10" in cc["facts"] and len(cc["facts"]["d10"]) == 9
    assert cc["calculation_config"]["charts"] == ["D1", "D9", "D10"]
    # The signed facts_token round-trips for the multi-chart facts, and a D10 fact
    # is citable end-to-end through /answers/validate.
    v = client.post(
        "/answers/validate",
        json={
            "answer": {
                "summary": "D10 Sun placement.",
                "facts_used": [
                    {"path": "d10.Sun.sign", "value": cc["facts"]["d10"][0]["sign"]}
                ],
            },
            "facts": cc["facts"],
            "facts_token": cc["facts_token"],
        },
    )
    assert v.json() == {"valid": True, "violations": []}


@requires_engine
def test_house_fact_roundtrips_through_validation():
    c = client.post("/charts/compute", json=_compute_body()).json()
    lord = c["facts"]["houses"][9]["lord"]  # 10th-house lord
    v = client.post(
        "/answers/validate",
        json={
            "answer": {
                "summary": "Career lord.",
                "facts_used": [{"path": "houses.10.lord", "value": lord}],
            },
            "facts": c["facts"],
            "facts_token": c["facts_token"],
        },
    )
    assert v.json() == {"valid": True, "violations": []}


@requires_engine
def test_aspect_fact_roundtrips_through_validation():
    c = client.post("/charts/compute", json=_compute_body()).json()
    target = c["facts"]["aspects"]["Saturn"]["aspects_planets"][0]
    v = client.post(
        "/answers/validate",
        json={
            "answer": {
                "summary": "Saturn aspect.",
                "facts_used": [{"path": f"aspects.Saturn.{target}", "value": "true"}],
            },
            "facts": c["facts"],
            "facts_token": c["facts_token"],
        },
    )
    assert v.json() == {"valid": True, "violations": []}


@requires_engine
def test_yoga_fact_roundtrips_through_validation():
    c = client.post("/charts/compute", json=_compute_body()).json()
    val = c["facts"]["yogas"]["Gajakesari"]["present"]
    v = client.post(
        "/answers/validate",
        json={
            "answer": {
                "summary": "Gajakesari status.",
                "facts_used": [
                    {"path": "yogas.Gajakesari.present", "value": "true" if val else "false"}
                ],
            },
            "facts": c["facts"],
            "facts_token": c["facts_token"],
        },
    )
    assert v.json() == {"valid": True, "violations": []}


@requires_engine
def test_unknown_chart_returns_422():
    r = client.post("/charts/compute", json=_compute_body(charts=["D99"]))
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")


@requires_engine
def test_unknown_node_aspects_returns_422():
    r = client.post("/charts/compute", json=_compute_body(node_aspects="nope"))
    assert r.status_code == 422
    assert "node_aspects" in r.json()["problem"]


@requires_engine
def test_low_precision_time_warns_but_succeeds():
    body = _compute_body()
    body["birth_profile"] = {**_VALID_PROFILE, "birth_time_confidence": "approximate"}
    r = client.post("/charts/compute", json=body)
    assert r.status_code == 200
    assert any("confidence" in w for w in r.json()["warnings"])


@requires_engine
def test_unknown_ayanamsa_returns_calculation_problem():
    r = client.post("/charts/compute", json=_compute_body(ayanamsa="NOPE"))
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")
    assert "unknown ayanamsa" in r.json()["problem"].lower()


@requires_engine
def test_star_based_ayanamsa_rejected_on_moshier():
    if ephemeris_mode() != "moshier":
        pytest.skip("Swiss ephemeris present; star-based ayanamsa is accepted")
    r = client.post("/charts/compute", json=_compute_body(ayanamsa="TRUE_CITRA"))
    assert r.status_code == 422
