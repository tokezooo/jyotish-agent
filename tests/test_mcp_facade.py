from __future__ import annotations

import json
from pathlib import Path

import pytest

from jyotish_agent.mcp_facade import (
    JyotishMcpFacade,
    McpFacadeError,
    compact_research_evidence,
)
from jyotish_agent.mcp_models import (
    CalculateInput,
    FinalizeResearchInput,
    FindingInput,
    InspectResearchInput,
    ProfileInput,
    ResearchInput,
    SourceSearchInput,
)


def _profile(name: str = "Vlad") -> dict:
    return {
        "name": name,
        "date": "2000-01-01",
        "time": "12:00:00",
        "birth_time_confidence": "exact",
        "place": {
            "name": "Test City",
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


def _write_private_profile(tmp_path: Path) -> Path:
    directory = tmp_path / "profiles"
    directory.mkdir(mode=0o700)
    path = directory / "vlad.json"
    path.write_text(json.dumps(_profile()), encoding="utf-8")
    path.chmod(0o600)
    return path


def _fake_chart(*_args, **_kwargs) -> dict:
    return {
        "normalized_input": {"fixture": True},
        "calculation_config": {"charts": ["D1", "D10"], "modules": []},
        "facts": {
            "ascendant": {"sign": "Pisces", "degrees": 25.5},
            "d10": [{"planet": "Sun", "sign": "Taurus", "degrees": 18.8}],
        },
        "provenance": {"engine": "fixture", "engine_version": "1"},
    }


def test_default_profile_and_quick_operations_create_no_runs(tmp_path: Path, monkeypatch):
    profile_path = _write_private_profile(tmp_path)
    monkeypatch.setattr("jyotish_agent.mcp_facade.compute_chart", _fake_chart)
    facade = JyotishMcpFacade(tmp_path / "data", profile_path)
    facade.store.seed_builtin_corpus()

    assert facade.get_profile(ProfileInput()).profile["name"] == "Vlad"
    before = facade.store.count_runs()
    quick = facade.calculate(
        CalculateInput(question="What is my D10 ascendant?", charts=["D1", "D10"])
    )
    sources = facade.search_sources(SourceSearchInput(query="important events", limit=5))

    assert facade.store.count_runs() == before
    assert quick.mode == "quick"
    assert quick.profile_name == "Vlad"
    assert quick.facts["ascendant"]["sign"] == "Pisces"
    assert sources.mode == "quick"
    assert sources.results
    assert all(item["content_role"] == "quoted_source_data" for item in sources.results)


def test_inline_profile_is_explicit_and_never_overwrites_default(tmp_path: Path, monkeypatch):
    profile_path = _write_private_profile(tmp_path)
    monkeypatch.setattr("jyotish_agent.mcp_facade.compute_chart", _fake_chart)
    facade = JyotishMcpFacade(tmp_path / "data", profile_path)

    result = facade.calculate(
        CalculateInput(
            question="A bounded question about Anna",
            profile="inline",
            inline_profile=_profile("Anna"),
            charts=["D1"],
        )
    )
    assert result.profile_name == "Anna"
    assert facade.get_profile(ProfileInput()).profile["name"] == "Vlad"

    with pytest.raises(McpFacadeError, match="INLINE_PROFILE_REQUIRED"):
        facade.calculate(
            CalculateInput(question="About another person", profile="inline", charts=["D1"])
        )


def test_private_profile_permissions_and_errors_do_not_leak_values(tmp_path: Path):
    profile_path = _write_private_profile(tmp_path)
    profile_path.chmod(0o644)
    facade = JyotishMcpFacade(tmp_path / "data", profile_path)
    with pytest.raises(McpFacadeError) as error:
        facade.get_profile(ProfileInput())
    assert "PRIVATE_PROFILE_PERMISSIONS" in str(error.value)
    assert "2000" not in str(error.value)
    assert "Test City" not in str(error.value)


def test_missing_default_profile_has_stable_setup_error(tmp_path: Path):
    facade = JyotishMcpFacade(tmp_path / "data", tmp_path / "missing.json")
    with pytest.raises(McpFacadeError, match="DEFAULT_PROFILE_MISSING"):
        facade.get_profile(ProfileInput())


def test_unsafe_deep_request_stops_before_calculation(tmp_path: Path, monkeypatch):
    profile_path = _write_private_profile(tmp_path)

    def forbidden_calculation(*_args, **_kwargs):
        raise AssertionError("unsafe research must not calculate")

    monkeypatch.setattr(
        "jyotish_agent.research_service.compute_chart", forbidden_calculation
    )
    facade = JyotishMcpFacade(tmp_path / "data", profile_path)
    bundle = facade.research(ResearchInput(question="Will I get cancer?"))

    assert bundle.safe is False
    assert bundle.status == "refused_unsafe"
    assert bundle.redirect
    assert bundle.facts is None


def test_deep_research_creates_one_run_and_finalizes_human_memo(tmp_path: Path, monkeypatch):
    profile_path = _write_private_profile(tmp_path)
    monkeypatch.setattr("jyotish_agent.research_service.compute_chart", _fake_chart)
    facade = JyotishMcpFacade(tmp_path / "data", profile_path)
    facade.store.seed_builtin_corpus()
    before = facade.store.count_runs()

    bundle = facade.research(
        ResearchInput(
            question="Provide a deep career factors and timing analysis.",
            retrieval_query="no-such-corpus-token",
            reference_date="2026-07-13",
        )
    )
    assert facade.store.count_runs() == before + 1
    assert bundle.mode == "deep"
    assert bundle.status == "calculated"
    assert bundle.plan["outcome"] == "supported"
    assert bundle.facts
    assert bundle.sources

    computed_support = next(
        item["evidence_id"] for item in bundle.facts.values()
    )
    source_support = bundle.sources[0]["evidence_id"]
    finalized = facade.finalize_research(
        FinalizeResearchInput(
            run_id=bundle.run_id,
            expected_revision=bundle.revision,
            title="Career direction",
            findings=[
                FindingInput(
                    text="The validated factors support a measured career transition.",
                    supports=[computed_support, source_support],
                    materiality="major",
                    confidence=0.75,
                )
            ],
            limitations=["This is a symbolic interpretation, not a guaranteed event."],
            followups=["We can examine a narrower time window next."],
        )
    )
    assert finalized.status == "validated"
    assert finalized.valid is True
    assert "The validated factors support" in finalized.markdown
    assert "## Claims" not in finalized.markdown
    assert "confidence" not in finalized.markdown

    inspection = facade.inspect_research(
        InspectResearchInput(run_id=bundle.run_id, include_provenance=False)
    )
    assert inspection.status == "validated"
    assert inspection.answer == finalized.markdown
    assert inspection.evidence is None


def test_finalize_rejects_foreign_evidence(tmp_path: Path, monkeypatch):
    profile_path = _write_private_profile(tmp_path)
    monkeypatch.setattr("jyotish_agent.research_service.compute_chart", _fake_chart)
    facade = JyotishMcpFacade(tmp_path / "data", profile_path)
    bundle = facade.research(
        ResearchInput(
            question="Provide a deep career factors and timing analysis.",
            reference_date="2026-07-13",
        )
    )
    with pytest.raises(McpFacadeError, match="EVIDENCE_MISSING"):
        facade.finalize_research(
            FinalizeResearchInput(
                run_id=bundle.run_id,
                expected_revision=bundle.revision,
                title="Invalid",
                findings=[
                    FindingInput(
                        text="Unsupported synthesis.",
                        supports=["evi_foreign"],
                        confidence=0.5,
                    )
                ],
            )
        )


def test_finalize_rejects_stale_revision_with_stable_code(tmp_path: Path, monkeypatch):
    profile_path = _write_private_profile(tmp_path)
    monkeypatch.setattr("jyotish_agent.research_service.compute_chart", _fake_chart)
    facade = JyotishMcpFacade(tmp_path / "data", profile_path)
    bundle = facade.research(
        ResearchInput(
            question="Provide a deep career factors and timing analysis.",
            reference_date="2026-07-13",
        )
    )
    support = next(item["evidence_id"] for item in bundle.facts.values())

    with pytest.raises(McpFacadeError, match="REVISION_CONFLICT"):
        facade.finalize_research(
            FinalizeResearchInput(
                run_id=bundle.run_id,
                expected_revision=bundle.revision - 1,
                title="Stale",
                findings=[FindingInput(text="Stale finding", supports=[support])],
            )
        )


def test_research_evidence_projection_is_bounded_and_keeps_support_ids():
    evidence = []
    for index in range(500):
        evidence.append(
            {
                "evidence_id": f"evi_{index}",
                "evidence_type": "computed_fact",
                "payload": {
                    "path": f"ashtakavarga.bav.Mars.synthetic_{index}",
                    "value": index,
                    "profile_hash": "private-internal-hash",
                },
            }
        )
    evidence.extend(
        [
            {
                "evidence_id": "evi_asc",
                "evidence_type": "computed_fact",
                "payload": {"path": "ascendant.sign", "value": "Aquarius"},
            },
            {
                "evidence_id": "evi_d10",
                "evidence_type": "computed_fact",
                "payload": {"path": "d10.Sun.house", "value": 3},
            },
            {
                "evidence_id": "evi_source",
                "evidence_type": "source_fragment",
                "payload": {
                    "fragment_id": "sf_1",
                    "title": "Approved work",
                    "locator": "chapter 1",
                    "quote": "A long quotation remains in the separate source result.",
                },
            },
        ]
    )

    facts = compact_research_evidence(evidence)

    assert facts == {
        "ascendant.sign": {"value": "Aquarius", "evidence_id": "evi_asc"},
        "d10.Sun.house": {"value": 3, "evidence_id": "evi_d10"},
    }
