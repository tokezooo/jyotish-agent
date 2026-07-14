from __future__ import annotations

import datetime as dt
import json
from zoneinfo import ZoneInfo

from jyotish_agent.doctrine.muhurta_pack import (
    MuhurtaActivityProfile,
    MuhurtaRankingCandidate,
    load_muhurta_ranking_profile,
    rank_muhurta_candidates,
    render_muhurta_report,
    validate_muhurta_visible_report,
)


ZONE = ZoneInfo("Europe/London")


def _ranking():
    profile = load_muhurta_ranking_profile(MuhurtaActivityProfile.FOCUSED_WORK)
    candidates = (
        MuhurtaRankingCandidate(
            candidate_id="mc_top",
            start=dt.datetime(2026, 10, 25, 1, 15, tzinfo=ZONE, fold=1),
            end=dt.datetime(2026, 10, 25, 1, 45, tzinfo=ZONE, fold=1),
            eligibility_status="eligible",
            doctrinal_soft_score=2,
            natal_soft_adjustment=1,
            user_preference_score=1,
            confidence=0.9,
        ),
        MuhurtaRankingCandidate(
            candidate_id="mc_alt",
            start=dt.datetime(2026, 10, 25, 2, 15, tzinfo=ZONE),
            end=dt.datetime(2026, 10, 25, 2, 45, tzinfo=ZONE),
            eligibility_status="eligible",
            doctrinal_soft_score=1,
            natal_soft_adjustment=0,
            user_preference_score=1,
            confidence=0.8,
        ),
        MuhurtaRankingCandidate(
            candidate_id="mc_near",
            start=dt.datetime(2026, 10, 25, 3, 15, tzinfo=ZONE),
            end=dt.datetime(2026, 10, 25, 3, 45, tzinfo=ZONE),
            eligibility_status="ineligible",
            hard_failure_ids=("muhurta.eligibility.dosa",),
            doctrinal_soft_score=0,
            natal_soft_adjustment=0,
            user_preference_score=0,
            confidence=0.7,
        ),
    )
    return rank_muhurta_candidates(candidates, profile)


def test_ru_en_reports_include_top_alternatives_near_misses_and_named_overlay() -> None:
    for locale in ("ru", "en"):
        report = render_muhurta_report(
            _ranking(), locale=locale, mode="full", include_inspection=False
        )
        assert len(report.top_windows) == 1
        assert len(report.alternatives) == 1
        assert len(report.near_misses) == 1
        assert report.overlay_comparison.baseline_profile == "classical_baseline_v1"
        assert report.overlay_comparison.overlay_profile == "bv_raman_modern_overlay_v1"
        assert report.overlay_comparison.overlay_status == "unavailable"
        assert report.booking_performed is False
        assert validate_muhurta_visible_report(report) == []


def test_normal_private_report_hides_candidate_ids_and_place_data() -> None:
    report = render_muhurta_report(
        _ranking(), locale="en", mode="quick", include_inspection=False
    )
    rendered = json.dumps(report.model_dump(mode="json"), ensure_ascii=False)
    assert "candidate_id" not in rendered
    assert "mc_top" not in rendered
    assert "London" not in rendered
    assert report.inspection is None


def test_opt_in_inspection_contains_zone_fold_and_utc_without_place_label() -> None:
    report = render_muhurta_report(
        _ranking(), locale="en", mode="deep", include_inspection=True
    )
    assert report.inspection is not None
    first = report.inspection[0]
    assert first.candidate_id == "mc_top"
    assert first.zone_id == "Europe/London"
    assert first.start_fold == 1
    assert first.start_utc == "2026-10-25T01:15:00Z"
    assert "place" not in json.dumps(report.model_dump(mode="json"))


def test_visible_text_firewall_rejects_tampering() -> None:
    report = render_muhurta_report(
        _ranking(), locale="en", mode="full", include_inspection=False
    )
    tampered = report.model_copy(update={"summary": "Book this guaranteed lucky time now."})
    assert validate_muhurta_visible_report(tampered) == ["VISIBLE_REPORT_MISMATCH"]


def test_modes_are_bounded_and_never_create_calendar_side_effects() -> None:
    quick = render_muhurta_report(_ranking(), locale="ru", mode="quick", include_inspection=False)
    deep = render_muhurta_report(_ranking(), locale="ru", mode="deep", include_inspection=False)
    assert len(quick.alternatives) <= len(deep.alternatives)
    assert quick.booking_performed is deep.booking_performed is False
    assert any("календар" in item.casefold() for item in deep.limitations)
