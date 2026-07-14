from __future__ import annotations

from pathlib import Path

from jyotish_agent.doctrine.prashna_pack import (
    PrashnaCaseCatalog,
    PrashnaRadicalityInput,
    PrashnaRadicalityProfile,
    PrashnaTestimony,
    PrashnaTimingSupport,
    classify_prashna_question,
    evaluate_prashna_outcome,
    evaluate_prashna_radicality,
    verify_published_case_judgment,
)
from jyotish_agent.prashna import calculate_prashna_aspect_geometry
from jyotish_agent.prashna_models import PrashnaAspectGeometryInput
from jyotish_agent.doctrine.prashna_pack import prashna_aspect_profile


ROOT = Path(__file__).parents[2]


def _radicality():
    profile = PrashnaRadicalityProfile.model_validate_json(
        (ROOT / "src/jyotish_agent/data/doctrine/prashna-rules.json").read_text()
    )
    return evaluate_prashna_radicality(
        PrashnaRadicalityInput(
            anchor_state="sealed",
            question_relation="new_anchor",
            topic_state="single_safe",
            question_form="proper",
            intent_state="sincere",
            sources_admitted=True,
        ),
        profile,
    )


def _route():
    return classify_prashna_question("What blocks this work project?")


def _geometry(*, applying: bool = True):
    profile = prashna_aspect_profile("tajika_nilakanthi_overlay").model_copy(
        update={"source_admitted": True, "source_refs": ("fixture:tajika",)}
    )
    return calculate_prashna_aspect_geometry(
        PrashnaAspectGeometryInput(
            anchor_sha256="a" * 64,
            body_a="lagna_lord",
            body_b="primary_house_lord",
            longitude_a=10.0,
            longitude_b=68.0 if applying else 72.0,
            speed_a=0.5,
            speed_b=1.0,
            aspect_degrees=60.0,
        ),
        profile,
    )


def _testimony(
    testimony_id: str, polarity: str, confidence: float = 0.5
) -> PrashnaTestimony:
    return PrashnaTestimony(
        testimony_id=testimony_id,
        polarity=polarity,
        confidence=confidence,
        fact_refs=("prashna.lagna.sign",),
        source_refs=("daivajna_vallabha_2003_scan:pdf:3",),
    )


def test_outcome_requires_all_three_gates_and_required_facts() -> None:
    route = _route()
    facts = route.required_fact_paths
    result = evaluate_prashna_outcome(
        _radicality(),
        route,
        _geometry(),
        testimonies=(_testimony("help", "assistance"),),
        available_fact_paths=facts,
    )
    assert result.judgment == "favorable"
    assert result.outcome_allowed
    assert result.gates == (
        ("radicality", "passed"),
        ("significators", "passed"),
        ("geometry", "passed"),
    )

    missing = evaluate_prashna_outcome(
        _radicality(),
        route,
        _geometry(),
        testimonies=(_testimony("help", "assistance"),),
        available_fact_paths=("prashna.lagna.sign",),
    )
    assert missing.judgment == "unavailable"
    assert missing.reason_codes == ("REQUIRED_FACTS_MISSING",)


def test_obstacle_assistance_conflict_remains_visible_and_can_return_mixed() -> None:
    result = evaluate_prashna_outcome(
        _radicality(),
        _route(),
        _geometry(),
        testimonies=(
            _testimony("support", "assistance", 0.4),
            _testimony("obstacle", "obstacle", 0.6),
        ),
        available_fact_paths=_route().required_fact_paths,
    )
    assert result.judgment == "mixed"
    assert result.conflicts == (("obstacle", "support"),)
    assert {node.polarity for node in result.testimonies} == {
        "assistance",
        "obstacle",
    }


def test_no_answer_and_high_stakes_fail_closed() -> None:
    no_answer = evaluate_prashna_outcome(
        _radicality(),
        _route(),
        _geometry(),
        testimonies=(),
        available_fact_paths=_route().required_fact_paths,
    )
    high_stakes = evaluate_prashna_outcome(
        _radicality(),
        classify_prashna_question("Will this surgery succeed?"),
        _geometry(),
        testimonies=(_testimony("support", "assistance"),),
        available_fact_paths=(),
    )
    assert no_answer.judgment == "no_answer"
    assert high_stakes.judgment == "unavailable"
    assert high_stakes.reason_codes == ("QUESTION_PROFILE_NOT_SUPPORTED",)
    assert not high_stakes.outcome_allowed


def test_geometry_cannot_be_bypassed() -> None:
    unavailable = calculate_prashna_aspect_geometry(
        PrashnaAspectGeometryInput(
            anchor_sha256="a" * 64,
            body_a="lagna_lord",
            body_b="primary_house_lord",
            longitude_a=10,
            longitude_b=68,
            speed_a=0.5,
            speed_b=1,
            aspect_degrees=60,
        ),
        prashna_aspect_profile("tajika_nilakanthi_overlay"),
    )
    result = evaluate_prashna_outcome(
        _radicality(),
        _route(),
        unavailable,
        testimonies=(_testimony("support", "assistance"),),
        available_fact_paths=_route().required_fact_paths,
    )
    assert result.judgment == "unavailable"
    assert result.reason_codes == ("GEOMETRY_UNAVAILABLE",)


def test_timing_is_a_bounded_unit_window_never_an_exact_date() -> None:
    result = evaluate_prashna_outcome(
        _radicality(),
        _route(),
        _geometry(),
        testimonies=(_testimony("support", "assistance"),),
        available_fact_paths=_route().required_fact_paths,
        timing_support=PrashnaTimingSupport(
            minimum=2,
            maximum=4,
            unit="weeks",
            source_refs=("fixture:timing-rule",),
        ),
    )
    assert result.timing_window is not None
    assert result.timing_window.minimum == 2
    assert result.timing_window.maximum == 4
    assert "date" not in result.timing_window.model_dump_json().casefold()


def test_published_high_stakes_case_is_reproduced_offline_but_not_product_admitted() -> (
    None
):
    cases = PrashnaCaseCatalog.model_validate_json(
        (ROOT / "src/jyotish_agent/data/doctrine/prashna-cases.json").read_text()
    )
    evaluation = verify_published_case_judgment(
        cases.cases[0],
        declared_school="prasna_marga_baseline",
        computed_judgment="negative",
    )
    assert evaluation.matches_published_judgment
    assert evaluation.observed_outcome_matches
    assert evaluation.product_admissible is False
