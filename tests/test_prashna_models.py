from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from jyotish_agent.event_models import EventAnchor, EventPlace
from jyotish_agent.prashna_models import PrashnaRequest


def _place(**changes):
    payload = {
        "name": "Moscow",
        "latitude": 55.7558,
        "longitude": 37.6173,
        "zone_id": "Europe/Moscow",
    }
    payload.update(changes)
    return payload


def test_event_anchor_requires_aware_rfc3339_and_matching_iana_zone():
    with pytest.raises(ValidationError, match="timezone-aware"):
        EventAnchor(asked_at="2026-07-14T12:00:00", place=_place())
    with pytest.raises(ValidationError, match="IANA"):
        EventPlace.model_validate(_place(zone_id="UTC+3"))
    with pytest.raises(ValidationError, match="TIMEZONE_OFFSET_MISMATCH"):
        EventAnchor(
            asked_at="2026-07-14T12:00:00+02:00",
            place=_place(),
        )


def test_event_anchor_dst_fold_and_gap_are_explicit():
    london = _place(name="London", latitude=51.5, longitude=-0.12, zone_id="Europe/London")
    with pytest.raises(ValidationError, match="AMBIGUOUS_LOCAL_TIME"):
        EventAnchor(asked_at="2026-10-25T01:30:00+01:00", place=london)
    folded = EventAnchor(
        asked_at="2026-10-25T01:30:00+00:00",
        place={**london, "fold": 1},
    )
    assert folded.resolved_fold == 1
    assert folded.normalized_utc == dt.datetime(2026, 10, 25, 1, 30, tzinfo=dt.UTC)
    with pytest.raises(ValidationError, match="NONEXISTENT_LOCAL_TIME"):
        EventAnchor(
            asked_at="2026-03-29T01:30:00+00:00",
            place={**london, "fold": 0},
        )


def test_request_requires_exactly_one_new_anchor_or_token():
    anchor = {"asked_at": "2026-07-14T12:00:00+03:00", "place": _place()}
    with pytest.raises(ValidationError, match="anchor or capture_now"):
        PrashnaRequest(question="Что мешает проекту?")
    with pytest.raises(ValidationError, match="never both"):
        PrashnaRequest(question="Что мешает проекту?", anchor=anchor, anchor_token="a" * 64)
    with pytest.raises(ValidationError, match="capture_now"):
        PrashnaRequest(question="Что мешает проекту?", anchor=anchor, capture_now=True)
    assert PrashnaRequest(question="Что мешает проекту?", anchor=anchor).rule_profile == "prashna_work_v1"
