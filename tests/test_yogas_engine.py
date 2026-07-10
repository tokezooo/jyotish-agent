"""Phase 14: engine yoga verdicts module (two-tier).

Verification strategy: the engine's return shape (dict keyed by stable snake_case
fn keys, values [chart_id, name, description, benefits]) was probed empirically;
these tests pin what we depend on — stable keys, prose exclusion (the engine's
deterministic "You will ..." predictions must never become citable facts), the
stdout capture (the engine print()s per-yoga failures instead of raising), the
error counting that turns silent shrinkage into status="partial", and the
degrade-to-"unavailable" path (the only module allowed to fail without killing
the chart compute — it runs ~284 unaudited functions)."""

from __future__ import annotations

import json
import re

import pytest

pytest.importorskip("jhora", reason="PyJHora not installed; run `uv sync`")

from jyotish_agent.config import CalculationConfig  # noqa: E402
from jyotish_agent.interpretations import iter_fact_atoms, validate_answer  # noqa: E402
from jyotish_agent.pyjhora_facade import (  # noqa: E402
    BirthProfile,
    _yoga_tier_mismatches,
    compute_chart,
)

_PROFILE = BirthProfile(
    name="Chennai Test",
    date=(1990, 1, 1),
    time=(12, 30, 0),
    latitude=13.0827,
    longitude=80.2707,
    timezone=5.5,
)
_REFERENCE = (2026, 6, 7)
_KEY_RE = re.compile(r"^[a-z0-9_]+$")


def _compute(modules=("yogas_engine",), charts=None):
    kwargs = {"modules": modules}
    if charts is not None:
        kwargs["charts"] = charts
    return compute_chart(
        _PROFILE, reference_date=_REFERENCE, config=CalculationConfig(**kwargs)
    )


def _facts(**kw):
    return _compute(**kw)["facts"]


def test_module_off_by_default():
    facts = compute_chart(_PROFILE, reference_date=_REFERENCE)["facts"]
    assert "yogas_engine" not in facts


def test_status_ok_and_zero_engine_errors_for_fixture():
    # Empirically pinned: under the current ephemeris (Moshier) none of the ~284
    # engine yoga checks fails for this fixture. If this starts failing, the engine
    # started silently dropping yogas — investigate, don't just repin.
    ye = _facts()["yogas_engine"]
    assert ye["status"] == "ok"
    assert ye["engine_errors"] == 0


def test_shape_charts_and_stable_keys():
    ye = _facts()["yogas_engine"]
    assert set(ye) == {"status", "engine_errors", "charts", "mismatches"}
    # Default config charts (D1+D9), lowercase keys.
    assert set(ye["charts"]) == {"d1", "d9"}
    assert len(ye["charts"]["d1"]) > 0  # fixture has detected D1 yogas
    for chart_key, entries in ye["charts"].items():
        for entry in entries:
            assert set(entry) == {"key", "name"}, (chart_key, entry)
            assert _KEY_RE.match(entry["key"]), entry["key"]
            assert entry["name"]
    # Empirical pin: this fixture's D1 detects vesi_yoga (stable engine fn key).
    assert "vesi_yoga" in {e["key"] for e in ye["charts"]["d1"]}


def test_per_chart_keys_match_configured_charts():
    ye = _facts(charts=("D9", "D10"))["yogas_engine"]
    assert set(ye["charts"]) == {"d1", "d9", "d10"}


def test_no_prediction_prose_in_payload():
    # The engine's benefit prose is deterministic-outcome text ("You will ...",
    # "like a king ...") and must be excluded entirely. Verified against all 284
    # resource entries: no fn key or display name contains these markers, so a hit
    # here can only be leaked prose.
    payload = json.dumps(_facts()["yogas_engine"])
    assert "You will" not in payload
    assert "king" not in payload.lower()


def test_unavailable_degradation_never_kills_compute(monkeypatch):
    from jhora.horoscope.chart import yoga as engine_yoga

    def boom(*args, **kwargs):
        raise RuntimeError("engine exploded")

    monkeypatch.setattr(engine_yoga, "get_yoga_details", boom)
    out = _compute()
    ye = out["facts"]["yogas_engine"]
    assert ye == {
        "status": "unavailable",
        "engine_errors": -1,
        "charts": {},
        "mismatches": [],  # no detection happened -> no mismatch claims
    }
    # The rest of the chart survived the module failure.
    assert out["facts"]["ascendant"]["sign"]
    assert out["facts"]["d1"]


def test_engine_error_lines_counted_as_partial(monkeypatch):
    # The engine print()s per-yoga failures ("Error executing <fn> ...") and keeps
    # going — a failing yoga silently vanishes. Simulate one failure per chart and
    # assert the capture turns them into engine_errors / status="partial".
    from jhora.horoscope.chart import yoga as engine_yoga

    def fake(jd, place, divisional_chart_factor=1, language="en"):
        print("some harmless engine chatter")
        print(
            "Error executing fake_yoga_from_jd_place for divisional_chart_factor=",
            divisional_chart_factor,
        )
        return {"vesi_yoga": ["D1", "Vesai Yoga", "desc", "benefits"]}, 1, 284

    monkeypatch.setattr(engine_yoga, "get_yoga_details", fake)
    ye = _facts()["yogas_engine"]
    assert ye["status"] == "partial"
    assert ye["engine_errors"] == 2  # one per chart (D1 + D9)
    assert ye["charts"]["d1"] == [{"key": "vesi_yoga", "name": "Vesai Yoga"}]


def test_engine_stdout_is_captured(capsys, monkeypatch):
    # Nothing the engine prints may reach the server's stdout — neither in the
    # clean run nor when yoga checks fail loudly.
    _facts()  # warm engine imports (jhora prints on first import)
    capsys.readouterr()
    _facts()
    assert capsys.readouterr().out == ""

    from jhora.horoscope.chart import yoga as engine_yoga

    def noisy(jd, place, divisional_chart_factor=1, language="en"):
        print("Error executing loud_yoga_from_jd_place")
        return {}, 0, 284

    monkeypatch.setattr(engine_yoga, "get_yoga_details", noisy)
    capsys.readouterr()
    ye = _facts()["yogas_engine"]
    assert capsys.readouterr().out == ""
    assert ye["status"] == "partial"


def test_fixture_tiers_agree_no_mismatch():
    # Two-tier agreement for the fixture: our verified tier says Gajakesari
    # present=false and the engine detects no gajakesari-like key. The field is
    # always present so the agent can rely on it.
    facts = _facts()
    assert facts["yogas"]["Gajakesari"]["present"] is False
    assert facts["yogas_engine"]["mismatches"] == []


def test_yoga_tier_mismatch_both_directions():
    ours_present = {"Gajakesari": {"present": True}}
    ours_absent = {"Gajakesari": {"present": False}}
    engine_with = {
        "status": "ok",
        "charts": {"d1": [{"key": "gaja_kesari_yoga", "name": "Gaja Kesari"}]},
    }
    engine_without = {"status": "ok", "charts": {"d1": [{"key": "vesi_yoga", "name": "V"}]}}

    assert _yoga_tier_mismatches(ours_present, engine_with) == []
    assert _yoga_tier_mismatches(ours_absent, engine_without) == []
    # Ours says present, engine silent -> warning naming the authoritative tier.
    (warn,) = _yoga_tier_mismatches(ours_present, engine_without)
    assert "present=true" in warn and "does not detect" in warn
    # Engine detects, ours says absent -> warning the other way.
    (warn2,) = _yoga_tier_mismatches(ours_absent, engine_with)
    assert "present=false" in warn2 and "detects" in warn2
    # Unavailable engine tier -> never a mismatch claim (absence means nothing).
    assert (
        _yoga_tier_mismatches(
            ours_present, {"status": "unavailable", "charts": {}}
        )
        == []
    )
    # Our tier missing (couldn't evaluate) -> no claim either.
    assert _yoga_tier_mismatches({}, engine_with) == []


def test_atoms_and_citation_roundtrip():
    facts = _facts()
    atoms = iter_fact_atoms(facts)
    assert atoms["yogas_engine.status"] == "ok"
    d1_keys = [e["key"] for e in facts["yogas_engine"]["charts"]["d1"]]
    for key in d1_keys:
        assert atoms[f"yogas_engine.d1.{key}.present"] == "true"
    # engine_errors / mismatches are context, never citable atoms.
    assert not any("engine_errors" in path for path in atoms)
    assert not any("mismatches" in path for path in atoms)

    ok = validate_answer(
        [
            {"path": f"yogas_engine.d1.{d1_keys[0]}.present", "value": "true"},
            {"path": "yogas_engine.status", "value": "ok"},
        ],
        facts,
    )
    assert ok == []
    # A non-detected yoga is NOT citable (detected-only contract: no false atoms).
    absent = validate_answer(
        [{"path": "yogas_engine.d1.gaja_kesari_yoga.present", "value": "true"}], facts
    )
    assert absent
    # Neither is citing a detected yoga as absent.
    forged = validate_answer(
        [{"path": f"yogas_engine.d1.{d1_keys[0]}.present", "value": "false"}], facts
    )
    assert forged


def test_no_engine_yoga_atoms_without_module():
    atoms = iter_fact_atoms(compute_chart(_PROFILE, reference_date=_REFERENCE)["facts"])
    assert not any(path.startswith("yogas_engine.") for path in atoms)


def test_config_echoes_modules():
    out = _compute()
    assert out["calculation_config"]["modules"] == ["yogas_engine"]


def test_all_engine_yoga_names_are_prose_free():
    # Resource-wide (all ~284 entries), not just fixture-detected: no display name
    # may carry prediction prose. Descriptions/benefits are dropped by the facade;
    # this pins that what we DO keep (names) is clean across the whole resource set.
    from jhora.horoscope.chart import yoga as engine_yoga

    resources = engine_yoga.get_yoga_resources(language="en")
    for key, details in resources.items():
        display = str(details[1]) if isinstance(details, (list, tuple)) and len(details) > 1 else ""
        low = display.lower()
        assert "you will" not in low and "king" not in low, (key, display)
