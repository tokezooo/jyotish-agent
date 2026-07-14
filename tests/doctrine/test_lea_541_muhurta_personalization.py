from __future__ import annotations

import json

from jyotish_agent.doctrine.muhurta_pack import (
    MuhurtaNatalFactorsInput,
    evaluate_muhurta_natal_factors,
)


def _factors(**overrides):
    payload = {
        "personalization_requested": True,
        "consent_confirmed": True,
        "source_admitted": True,
        "birth_time_accuracy": "exact",
        "birth_nakshatra_stable": True,
        "birth_moon_sign_stable": True,
        "birth_nakshatra_index": 0,
        "candidate_nakshatra_index": 1,
        "birth_moon_sign_index": 0,
        "candidate_moon_sign_index": 2,
    }
    payload.update(overrides)
    return MuhurtaNatalFactorsInput.model_validate(payload)


def test_tara_bala_and_candra_bala_are_source_bound_optional_factors() -> None:
    result = evaluate_muhurta_natal_factors(_factors())
    assert result.status == "available"
    assert result.tara_bala == "favorable"
    assert result.candra_bala == "favorable"
    assert result.soft_adjustment == 2
    assert result.source_locators == (
        "Kalaprakasika, printed pp. 166-168",
        "Kalaprakasika, printed pp. 207-208",
    )


def test_no_natal_opt_in_means_omitted_not_implicitly_applied() -> None:
    result = evaluate_muhurta_natal_factors(
        _factors(personalization_requested=False, consent_confirmed=False)
    )
    assert result.status == "omitted"
    assert result.soft_adjustment == 0
    assert result.tara_bala is None


def test_consent_and_source_admission_fail_closed() -> None:
    no_consent = evaluate_muhurta_natal_factors(_factors(consent_confirmed=False))
    no_source = evaluate_muhurta_natal_factors(_factors(source_admitted=False))
    assert no_consent.status == "unavailable"
    assert no_consent.reason_code == "NATAL_CONSENT_REQUIRED"
    assert no_source.status == "unavailable"
    assert no_source.reason_code == "NATAL_RULES_NOT_ADMITTED"


def test_approximate_unstable_birth_data_is_never_silently_treated_as_exact() -> None:
    result = evaluate_muhurta_natal_factors(
        _factors(
            birth_time_accuracy="approximate",
            birth_nakshatra_stable=False,
        )
    )
    assert result.status == "unavailable"
    assert result.reason_code == "NATAL_FACTORS_UNSTABLE"
    assert result.confidence == "unstable"


def test_unfavorable_personalization_is_bounded_and_never_a_hard_gate() -> None:
    result = evaluate_muhurta_natal_factors(
        _factors(candidate_nakshatra_index=2, candidate_moon_sign_index=1)
    )
    assert result.status == "available"
    assert result.tara_bala == "unfavorable"
    assert result.candra_bala == "unfavorable"
    assert result.soft_adjustment == -2
    assert result.can_override_hard_exclusion is False


def test_result_does_not_echo_raw_natal_inputs() -> None:
    rendered = json.dumps(evaluate_muhurta_natal_factors(_factors()).model_dump(mode="json"))
    for forbidden in (
        "birth_nakshatra_index",
        "birth_moon_sign_index",
        "candidate_nakshatra_index",
        "candidate_moon_sign_index",
    ):
        assert forbidden not in rendered
