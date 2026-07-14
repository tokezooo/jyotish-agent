from __future__ import annotations

import pytest

from jyotish_agent.doctrine.muhurta_pack import (
    MuhurtaActivityProfile,
    MuhurtaProfileCatalog,
    load_muhurta_profile_catalog,
    route_muhurta_activity,
)


@pytest.mark.parametrize(
    ("activity", "locale", "expected"),
    [
        ("focused work", "en", MuhurtaActivityProfile.FOCUSED_WORK),
        ("глубокая работа", "ru", MuhurtaActivityProfile.FOCUSED_WORK),
        ("study session", "en", MuhurtaActivityProfile.STUDY_LEARNING),
        ("обучение", "ru", MuhurtaActivityProfile.STUDY_LEARNING),
        ("creative production", "en", MuhurtaActivityProfile.CREATIVE_PRODUCTION),
        ("творческая работа", "ru", MuhurtaActivityProfile.CREATIVE_PRODUCTION),
        ("product launch communication", "en", MuhurtaActivityProfile.PRODUCT_LAUNCH_COMMUNICATION),
        ("запуск продукта", "ru", MuhurtaActivityProfile.PRODUCT_LAUNCH_COMMUNICATION),
        ("low risk travel planning", "en", MuhurtaActivityProfile.LOW_RISK_TRAVEL_PLANNING),
        ("планирование поездки", "ru", MuhurtaActivityProfile.LOW_RISK_TRAVEL_PLANNING),
        ("general private task", "en", MuhurtaActivityProfile.GENERAL_PRIVATE_TASK),
        ("личная задача", "ru", MuhurtaActivityProfile.GENERAL_PRIVATE_TASK),
    ],
)
def test_ru_en_profiles_route_deterministically(activity, locale, expected) -> None:
    result = route_muhurta_activity(activity, locale=locale)
    assert result.status == "supported"
    assert result.profile == expected


@pytest.mark.parametrize(
    "activity",
    [
        "marriage ceremony",
        "medical procedure",
        "legal filing",
        "investment trade",
        "fertility treatment",
        "dangerous expedition",
        "свадьба",
        "операция",
        "судебная подача",
        "инвестиция",
        "зачатие",
        "опасная экспедиция",
    ],
)
def test_high_stakes_requests_are_blocked(activity: str) -> None:
    result = route_muhurta_activity(activity, locale="ru" if activity[0] > "z" else "en")
    assert result.status == "unsupported_high_stakes"
    assert result.profile is None


def test_every_profile_is_complete_or_explicitly_unavailable() -> None:
    catalog = load_muhurta_profile_catalog()
    assert isinstance(catalog, MuhurtaProfileCatalog)
    assert {item.profile for item in catalog.profiles} == set(MuhurtaActivityProfile)
    for item in catalog.profiles:
        assert item.required_rule_families
        assert item.doctrine_status in {"available", "unavailable_pending_source_admission"}
        if item.doctrine_status == "available":
            assert item.admitted_rule_ids
        else:
            assert not item.admitted_rule_ids


def test_focused_work_legacy_alias_is_backwards_compatible() -> None:
    result = route_muhurta_activity("focused_work_session_v1", locale="en")
    assert result.status == "supported"
    assert result.profile == MuhurtaActivityProfile.FOCUSED_WORK
    assert result.legacy_profile_id == "muhurta_focused_work_v1"


def test_composite_and_ambiguous_requests_do_not_expand_scope() -> None:
    composite = route_muhurta_activity("study session and travel planning", locale="en")
    ambiguous = route_muhurta_activity("pick the best time for everything", locale="en")
    assert composite.status == "needs_input"
    assert composite.reason_code == "COMPOSITE_ACTIVITY_UNSUPPORTED"
    assert ambiguous.status == "needs_input"
    assert ambiguous.profile is None
