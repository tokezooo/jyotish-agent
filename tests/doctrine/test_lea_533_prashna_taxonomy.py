from __future__ import annotations

from jyotish_agent.doctrine.prashna_pack import (
    PrashnaQuestionProfile,
    classify_prashna_question,
    validate_prashna_significator_claim,
)


def test_ru_en_wording_variants_route_to_four_safe_profiles() -> None:
    variants = {
        PrashnaQuestionProfile.WORK_PROJECT_STATUS: (
            "What is blocking my work project?",
            "Что сейчас мешает моему рабочему проекту?",
        ),
        PrashnaQuestionProfile.COMMUNICATION_CONTACT: (
            "Will this person contact me about the non-critical message?",
            "Свяжется ли этот человек со мной по обычному сообщению?",
        ),
        PrashnaQuestionProfile.LOST_OBJECT: (
            "Where is my lost notebook?",
            "Где моя потерянная записная книжка?",
        ),
        PrashnaQuestionProfile.GENERAL_LOW_RISK_OUTCOME: (
            "Will this low-risk plan work out?",
            "Получится ли этот безрисковый план?",
        ),
    }
    for expected, questions in variants.items():
        results = [classify_prashna_question(question) for question in questions]
        assert all(result.status == "supported" for result in results)
        assert {result.profile for result in results} == {expected}
        assert results[0].primary_house == results[1].primary_house
        assert results[0].significators == results[1].significators
        assert results[0].source_refs == results[1].source_refs


def test_supported_routes_have_source_bound_significators_and_fact_requirements() -> (
    None
):
    result = classify_prashna_question("What blocks this work project?")
    assert result.primary_house == 10
    assert result.secondary_houses == (1, 6, 11)
    assert result.significators == ("lagna_lord", "primary_house_lord", "moon")
    assert {
        "prashna.lagna.sign",
        "prashna.moon.sign",
        "prashna.topic.primary_house",
    } <= set(result.required_fact_paths)
    assert result.source_refs


def test_composite_high_stakes_ambiguous_and_unsupported_fail_with_safe_guidance() -> (
    None
):
    composite = classify_prashna_question("Will my project work and where are my keys?")
    high_stakes = classify_prashna_question("Will my cancer surgery succeed?")
    ambiguous = classify_prashna_question("Will it happen?")
    unsupported = classify_prashna_question("What color should I paint the wall?")
    assert composite.status == "composite"
    assert high_stakes.status == "high_stakes"
    assert ambiguous.status == "ambiguous"
    assert unsupported.status == "unsupported"
    assert composite.guidance_code == "ASK_ONE_MATERIAL_QUESTION"
    assert high_stakes.guidance_code == "CONSULT_QUALIFIED_PROFESSIONAL"
    assert not high_stakes.significators


def test_adversarial_negation_does_not_downgrade_high_stakes_or_mix_profiles() -> None:
    result = classify_prashna_question(
        "This is not medical advice: will the surgery work, and where are my keys?"
    )
    assert result.status == "high_stakes"
    assert result.profile is None
    assert result.primary_house is None


def test_significator_substitution_is_rejected_by_firewall() -> None:
    route = classify_prashna_question("What blocks my work project?")
    assert (
        validate_prashna_significator_claim(
            route,
            claimed_primary_house=10,
            claimed_significators=("lagna_lord", "primary_house_lord", "moon"),
        )
        == ()
    )
    assert validate_prashna_significator_claim(
        route,
        claimed_primary_house=7,
        claimed_significators=("venus",),
    ) == ("PRIMARY_HOUSE_SUBSTITUTED", "SIGNIFICATORS_SUBSTITUTED")


def test_router_is_deterministic_and_does_not_echo_private_wording() -> None:
    question = "What blocks project Secret-Codename-Argon?"
    first = classify_prashna_question(question)
    second = classify_prashna_question(question)
    assert first == second
    assert "Argon" not in first.model_dump_json()
