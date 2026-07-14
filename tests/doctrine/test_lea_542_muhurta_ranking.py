from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from jyotish_agent.doctrine.muhurta_pack import (
    MuhurtaActivityProfile,
    MuhurtaRankingCandidate,
    load_muhurta_ranking_profile,
    rank_muhurta_candidates,
)


ZONE = ZoneInfo("Europe/Moscow")


def _candidate(candidate_id: str, hour: int, **overrides) -> MuhurtaRankingCandidate:
    payload = {
        "candidate_id": candidate_id,
        "start": dt.datetime(2026, 7, 15, hour, 0, tzinfo=ZONE),
        "end": dt.datetime(2026, 7, 15, hour + 1, 0, tzinfo=ZONE),
        "eligibility_status": "eligible",
        "hard_failure_ids": (),
        "doctrinal_soft_score": 1,
        "natal_soft_adjustment": 0,
        "user_preference_score": 0,
        "confidence": 0.8,
    }
    payload.update(overrides)
    return MuhurtaRankingCandidate.model_validate(payload)


def test_versioned_weights_and_component_sum_are_explainable() -> None:
    profile = load_muhurta_ranking_profile(MuhurtaActivityProfile.FOCUSED_WORK)
    assert profile.version == "1.0.0"
    result = rank_muhurta_candidates(
        (_candidate("mc_a", 10, doctrinal_soft_score=2, natal_soft_adjustment=1, user_preference_score=2),),
        profile,
    )
    item = result.ranked[0]
    assert item.score_components == {
        "doctrine": 10,
        "natal": 2,
        "user_preference": 2,
    }
    assert item.total_score == sum(item.score_components.values())
    assert item.confidence == 0.8


def test_ineligible_candidate_never_ranks_even_with_maximum_soft_scores() -> None:
    profile = load_muhurta_ranking_profile(MuhurtaActivityProfile.FOCUSED_WORK)
    result = rank_muhurta_candidates(
        (
            _candidate("mc_ok", 10),
            _candidate(
                "mc_blocked",
                11,
                eligibility_status="ineligible",
                hard_failure_ids=("muhurta.eligibility.dosa",),
                doctrinal_soft_score=10,
                natal_soft_adjustment=2,
                user_preference_score=2,
            ),
        ),
        profile,
    )
    assert [item.candidate_id for item in result.ranked] == ["mc_ok"]
    assert [item.candidate_id for item in result.near_misses] == ["mc_blocked"]
    assert result.near_misses[0].hard_failure_ids == ("muhurta.eligibility.dosa",)


def test_pareto_dominance_and_stable_ties_are_visible() -> None:
    profile = load_muhurta_ranking_profile(MuhurtaActivityProfile.FOCUSED_WORK)
    candidates = (
        _candidate("mc_earlier", 9, doctrinal_soft_score=2, confidence=0.9),
        _candidate("mc_later", 10, doctrinal_soft_score=2, confidence=0.9),
        _candidate("mc_dominated", 11, doctrinal_soft_score=1, confidence=0.7),
    )
    first = rank_muhurta_candidates(candidates, profile)
    replay = rank_muhurta_candidates(tuple(reversed(candidates)), profile)
    assert [item.candidate_id for item in first.ranked] == [
        "mc_earlier",
        "mc_later",
        "mc_dominated",
    ]
    assert first == replay
    dominated = next(item for item in first.ranked if item.candidate_id == "mc_dominated")
    assert dominated.pareto_dominated_by == ("mc_earlier", "mc_later")


def test_natal_and_user_preferences_remain_bounded_soft_components() -> None:
    profile = load_muhurta_ranking_profile(MuhurtaActivityProfile.STUDY_LEARNING)
    result = rank_muhurta_candidates(
        (
            _candidate("mc_plain", 9, natal_soft_adjustment=0, user_preference_score=0),
            _candidate("mc_personal", 10, natal_soft_adjustment=2, user_preference_score=2),
        ),
        profile,
    )
    assert result.ranked[0].candidate_id == "mc_personal"
    assert result.ranked[0].score_components["natal"] <= 4
    assert result.ranked[0].score_components["user_preference"] <= 2


def test_all_ineligible_candidates_return_no_window_with_near_misses() -> None:
    profile = load_muhurta_ranking_profile(MuhurtaActivityProfile.GENERAL_PRIVATE_TASK)
    result = rank_muhurta_candidates(
        (
            _candidate("mc_two", 10, eligibility_status="ineligible", hard_failure_ids=("b", "a")),
            _candidate("mc_one", 11, eligibility_status="ineligible", hard_failure_ids=("a",)),
        ),
        profile,
    )
    assert result.status == "no_window"
    assert result.ranked == ()
    assert [item.candidate_id for item in result.near_misses] == ["mc_one", "mc_two"]
