"""Pure half-open interval algebra for event searches."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, order=True)
class EventInterval:
    start: dt.datetime
    end: dt.datetime

    def __post_init__(self) -> None:
        if any(value.tzinfo is None or value.utcoffset() is None for value in (self.start, self.end)):
            raise ValueError("interval endpoints must be timezone-aware")
        if _utc(self.end) <= _utc(self.start):
            raise ValueError("interval end must be after start")

    @property
    def duration_seconds(self) -> float:
        return (_utc(self.end) - _utc(self.start)).total_seconds()

    def contains(self, instant: dt.datetime) -> bool:
        value = _utc(instant)
        return _utc(self.start) <= value < _utc(self.end)

    def intersection(self, other: "EventInterval") -> "EventInterval | None":
        start = self.start if _utc(self.start) >= _utc(other.start) else other.start
        end = self.end if _utc(self.end) <= _utc(other.end) else other.end
        return EventInterval(start, end) if _utc(start) < _utc(end) else None


def _utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("instant must be timezone-aware")
    return value.astimezone(dt.UTC)


def normalize_boundaries(bounds: EventInterval, instants: Iterable[dt.datetime]) -> tuple[dt.datetime, ...]:
    """Clip, de-duplicate, and UTC-sort boundaries while preserving endpoint instants."""
    by_utc = {_utc(bounds.start): bounds.start, _utc(bounds.end): bounds.end}
    for value in instants:
        instant = _utc(value)
        if _utc(bounds.start) < instant < _utc(bounds.end):
            by_utc.setdefault(instant, value)
    return tuple(by_utc[key] for key in sorted(by_utc))


def partition_interval(bounds: EventInterval, boundaries: Iterable[dt.datetime]) -> tuple[EventInterval, ...]:
    points = normalize_boundaries(bounds, boundaries)
    return tuple(EventInterval(left, right) for left, right in zip(points, points[1:]) if _utc(left) < _utc(right))


def subtract_intervals(bounds: EventInterval, exclusions: Iterable[EventInterval]) -> tuple[EventInterval, ...]:
    pieces = [bounds]
    for exclusion in sorted(exclusions, key=lambda item: _utc(item.start)):
        next_pieces: list[EventInterval] = []
        for piece in pieces:
            overlap = piece.intersection(exclusion)
            if overlap is None:
                next_pieces.append(piece)
                continue
            if _utc(piece.start) < _utc(overlap.start):
                next_pieces.append(EventInterval(piece.start, overlap.start))
            if _utc(overlap.end) < _utc(piece.end):
                next_pieces.append(EventInterval(overlap.end, piece.end))
        pieces = next_pieces
    return tuple(pieces)
