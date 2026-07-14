from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from jyotish_agent.jaimini import (
    ExactKarakaTieError,
    argala,
    arudha_pada,
    arudha_padas,
    capture_birth_snapshots,
    chara_dasha,
    chara_karakas,
    karakamsa,
    rasi_drishti,
    resolve_co_lord,
    sensitivity_sweep,
    special_lagnas,
    svamsa,
)
from jyotish_agent.jaimini_models import (
    ApproximateJaiminiBirthInput,
    ExactJaiminiBirthInput,
    JaiminiInput,
    JaiminiPlace,
)
from jyotish_agent.rule_profiles import load_jaimini_rule_profile

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/jaimini_core_hand_checked_v1.json").read_text()
)


def test_chara_karakas_hand_ranked_seven_and_eight_schemes():
    longitudes = FIXTURE["karakas"]["longitudes"]
    assert chara_karakas(longitudes, scheme=7).assignments == FIXTURE["karakas"]["seven"]
    eight = chara_karakas(longitudes, scheme=8)
    assert eight.assignments == FIXTURE["karakas"]["eight"]
    assert eight.scores_arcseconds["Rahu"] == 2 * 3600


def test_chara_karakas_exact_tie_errors_and_near_tie_only_flags():
    values = {"Sun": 20, "Moon": 19, "Mars": 18, "Mercury": 17, "Jupiter": 16, "Venus": 15, "Saturn": 14}
    values["Moon"] = values["Sun"]
    with pytest.raises(ExactKarakaTieError, match="Sun.*Moon|Moon.*Sun"):
        chara_karakas(values, scheme=7)

    values["Moon"] = 20 - 30 / 3600
    result = chara_karakas(values, scheme=7)
    assert result.assignments["AK"] == "Sun"
    assert result.near_ties == (("Sun", "Moon"),)

    values["Moon"] = 20 - 61 / 3600
    assert chara_karakas(values, scheme=7).near_ties == ()
    with pytest.raises(ValueError, match="scheme"):
        chara_karakas(values, scheme=9)


@pytest.mark.parametrize(
    "source,expected",
    [
        (0, (4, 7, 10)),  # movable Aries -> fixed except adjacent Taurus
        (4, (0, 6, 9)),   # fixed Leo -> movable except adjacent Cancer
        (2, (5, 8, 11)),  # dual Gemini -> the other dual signs
    ],
)
def test_rasi_drishti_modal_geometry(source, expected):
    profile = load_jaimini_rule_profile()
    assert rasi_drishti(source, profile=profile) == expected
    assert all(source in rasi_drishti(target, profile=profile) for target in expected)


def test_arudha_all_twelve_and_same_or_seventh_exception_are_hand_counted():
    data = FIXTURE["arudha"]
    assert [arudha_pada(h, l) for h, l in zip(data["house_signs"], data["lord_signs"])] == data["padas"]
    assert arudha_pada(0, 0) == 9
    assert arudha_pada(0, 6) == 9
    padas = arudha_padas(0, data["lord_signs"])
    assert padas["AL"] == padas["A1"]
    assert padas["UL"] == padas["A12"]
    assert len({key for key in padas if key[1:].isdigit()}) == 12


def test_co_lord_resolution_uses_duration_then_degree_then_frozen_order():
    assert resolve_co_lord(("Mars", "Ketu"), {"Mars": 4, "Ketu": 7}, {"Mars": 29, "Ketu": 1}) == "Ketu"
    assert resolve_co_lord(("Mars", "Ketu"), {"Mars": 7, "Ketu": 7}, {"Mars": 2, "Ketu": 3}) == "Ketu"
    assert resolve_co_lord(("Mars", "Ketu"), {"Mars": 7, "Ketu": 7}, {"Mars": 3, "Ketu": 3}) == "Mars"


def test_argala_and_virodhargala_pair_each_counted_house():
    # From Aries: primary argala houses 2/4/11, obstructed by 12/10/3; secondary 5 by 9.
    occupants = {1: ("Moon",), 3: ("Mars",), 10: ("Jupiter",), 11: ("Saturn",), 9: ("Venus",), 2: ("Sun",), 4: ("Mercury",), 8: ("Rahu",)}
    result = argala(0, occupants, profile=load_jaimini_rule_profile())
    assert [(item.house, item.obstruction_house) for item in result] == [(2, 12), (4, 10), (11, 3), (5, 9)]
    assert result[0].contributors == ("Moon",) and result[0].obstructors == ("Saturn",)
    assert result[3].contributors == ("Mercury",) and result[3].obstructors == ("Rahu",)
    assert result[0].status == "obstructed"  # equal counts


def test_argala_obstruction_status_empty_equal_and_unequal_counts():
    profile = load_jaimini_rule_profile()
    empty = argala(0, {}, profile=profile)[0]
    unobstructed = argala(0, {1: ("Moon",)}, profile=profile)[0]
    partial = argala(0, {1: ("Moon", "Mars"), 11: ("Saturn",)}, profile=profile)[0]
    overwhelmed = argala(0, {1: ("Moon",), 11: ("Saturn", "Rahu")}, profile=profile)[0]
    assert (empty.status, unobstructed.status, partial.status, overwhelmed.status) == (
        "absent", "unobstructed", "partial", "obstructed"
    )


def test_svamsa_is_d9_lagna_and_karakamsa_is_d9_ak_sign():
    d9 = {"Lagna": (8, 11.0), "Sun": (3, 5.0), "Saturn": (10, 2.0)}
    assert svamsa(d9) == 8
    assert karakamsa(d9, {"AK": "Saturn"}) == 10


def test_svamsa_and_karakamsa_accept_locked_snapshot_positions():
    @dataclass(frozen=True)
    class Position:
        planet_index: int | None
        sign_index: int
        degrees: float

    d9 = (Position(None, 8, 11), Position(0, 3, 5), Position(6, 10, 2), Position(7, 4, 7))
    assert svamsa(d9) == 8
    assert karakamsa(d9, {"AK": "Saturn"}) == 10
    assert karakamsa(d9, {"AK": "Rahu"}) == 4


def test_selected_special_lagnas_use_elapsed_sunrise_rates_and_wrap():
    # At 120 minutes after sunrise: BL advances 1, HL 2, GL 5 signs from Sun.
    assert special_lagnas(sun_longitude=350.0, minutes_since_sunrise=120, profile=load_jaimini_rule_profile()) == {
        "bhava_lagna": pytest.approx(20.0),
        "hora_lagna": pytest.approx(50.0),
        "ghati_lagna": pytest.approx(140.0),
    }


def test_chara_dasha_profile_branches_and_exact_half_open_boundaries():
    f = FIXTURE["dasha"]
    birth = dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)
    male = chara_dasha(f["lagna"], f["lords"], gender="male", start=birth)
    female = chara_dasha(f["lagna"], f["lords"], gender="female", start=birth)
    assert [p.sign for p in male] == f["male_signs"]
    assert [p.years for p in male] == f["male_years"]
    assert [p.sign for p in female] == f["female_signs"]
    assert [p.years for p in female] == f["female_years"]
    assert all(a.end == b.start for a, b in zip(male, male[1:]))
    assert all(a.start < a.end for a in male)
    boundary = male[0].end
    assert boundary == dt.datetime(2000, 12, 31, 5, 49, 12, tzinfo=dt.timezone.utc)
    assert not male[0].contains(boundary)
    assert male[1].contains(boundary)
    assert len(male[0].antardashas) == 12
    assert male[0].antardashas[0].sign == 1
    assert male[0].antardashas[0].end == dt.datetime(2000, 1, 31, 10, 29, 6, tzinfo=dt.timezone.utc)
    assert male[0].antardashas[-1].end == male[0].end


def test_chara_dasha_requires_binary_gender_and_aware_start():
    with pytest.raises(ValueError, match="gender"):
        chara_dasha(0, list(range(12)), gender="unknown", start=dt.datetime.now(dt.timezone.utc))
    with pytest.raises(ValueError, match="timezone-aware"):
        chara_dasha(0, list(range(12)), gender="male", start=dt.datetime(2000, 1, 1))


def test_geometry_and_timing_invariants_cover_all_signs():
    assert all(all(source in rasi_drishti(target) for target in rasi_drishti(source)) for source in range(12))
    assert all(0 <= arudha_pada(house, lord) < 12 for house in range(12) for lord in range(12))
    start = dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)
    periods = chara_dasha(1, tuple(range(12)), gender="male", start=start)
    assert all(left.end == right.start for left, right in zip(periods, periods[1:]))
    assert all(
        left.end == right.start
        for period in periods
        for left, right in zip(period.antardashas, period.antardashas[1:])
    )
    assert all(period.antardashas[0].start == period.start and period.antardashas[-1].end == period.end for period in periods)


def test_exact_and_approximate_sensitivity_are_bounded_inclusive_five_minutes():
    exact = sensitivity_sweep(
        confidence="exact",
        start=dt.datetime(2000, 1, 1, 10, tzinfo=dt.timezone.utc),
        end=None,
        calculate=lambda instant: {"lagna": instant.minute // 5},
    )
    assert exact.sample_count == 1 and exact.stability == {"lagna": "stable"}

    start = dt.datetime(2000, 1, 1, 10, tzinfo=dt.timezone.utc)
    sweep = sensitivity_sweep(confidence="approximate", start=start, end=start + dt.timedelta(minutes=10), calculate=lambda instant: {"lagna": instant.minute // 10})
    assert sweep.instants == (start, start + dt.timedelta(minutes=5), start + dt.timedelta(minutes=10))
    assert sweep.stability == {"lagna": "unstable"}
    with pytest.raises(ValueError, match="120"):
        sensitivity_sweep(confidence="approximate", start=start, end=start + dt.timedelta(minutes=125), calculate=lambda _: {})
    with pytest.raises(ValueError, match="unknown"):
        sensitivity_sweep(confidence="unknown", start=start, end=None, calculate=lambda _: {})
    with pytest.raises(ValueError, match="five minutes"):
        sensitivity_sweep(confidence="approximate", start=start, end=start + dt.timedelta(minutes=12), calculate=lambda _: {})


def test_approximate_model_rejects_non_five_minute_width_and_gender_matches_scope():
    place = {"name": "UTC", "latitude": 0, "longitude": 0, "timezone": "Etc/UTC"}
    with pytest.raises(ValueError, match="divisible by 5"):
        ApproximateJaiminiBirthInput.model_validate({
            "confidence": "approximate", "date": "2000-01-01",
            "earliest_time": "10:00:00", "latest_time": "10:12:00", "place": place,
        })
    common = {
        "profile": "synthetic", "birth": {
            "confidence": "exact", "date": "2000-01-01", "time": "10:00:00", "place": place,
        }
    }
    with pytest.raises(ValueError, match="gender.*required"):
        JaiminiInput.model_validate({**common, "analysis_scope": "core_with_chara_dasha"})
    with pytest.raises(ValueError, match="gender.*not accepted"):
        JaiminiInput.model_validate({**common, "analysis_scope": "core", "gender": "male"})
    assert JaiminiInput.model_validate({**common, "analysis_scope": "core"}).gender is None
    assert JaiminiInput.model_validate({**common, "analysis_scope": "core_with_chara_dasha", "gender": "female"}).gender == "female"


def test_capture_birth_snapshots_uses_locked_session_callback_for_every_sample(monkeypatch):
    calls = []

    class Result:
        domain = "captured-D1-D9"

    def session(profile, reference_date, config, domain_callback):
        calls.append((profile.time, profile.timezone, reference_date))
        return Result()

    monkeypatch.setattr("jyotish_agent.jaimini._run_engine_session", session)
    place = JaiminiPlace(name="UTC", latitude=0, longitude=0, timezone="Etc/UTC")
    birth = ApproximateJaiminiBirthInput(confidence="approximate", date=dt.date(2000, 1, 1), earliest_time=dt.time(10), latest_time=dt.time(10, 10), place=place)
    captured = capture_birth_snapshots(birth, reference_date=(2026, 1, 1))
    assert captured == ("captured-D1-D9",) * 3
    assert [call[0] for call in calls] == [(10, 0, 0), (10, 5, 0), (10, 10, 0)]
    assert all(call[1] == 0 for call in calls)

    exact_birth = ExactJaiminiBirthInput(confidence="exact", date=dt.date(2000, 1, 1), time=dt.time(10), place=place)
    assert capture_birth_snapshots(exact_birth, reference_date=(2026, 1, 1)) == ("captured-D1-D9",)


def test_capture_birth_snapshots_real_kernel_contains_immutable_d1_d9():
    place = JaiminiPlace(name="Chennai", latitude=13.0827, longitude=80.2707, timezone="Asia/Kolkata")
    birth = ExactJaiminiBirthInput(confidence="exact", date=dt.date(1990, 1, 1), time=dt.time(12, 30), place=place)
    (snapshot,) = capture_birth_snapshots(birth, reference_date=(2026, 6, 7))
    assert len(snapshot.d1) == len(snapshot.d9) == 10
    assert svamsa(snapshot.d9) == snapshot.d9[0].sign_index
