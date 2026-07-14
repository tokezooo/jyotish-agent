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
        if self.end <= self.start:
            raise ValueError("interval end must be after start")

    @property
    def duration_seconds(self) -> float:
        return (self.end - self.start).total_seconds()

    def contains(self, instant: dt.datetime) -> bool:
        return self.start <= instant < self.end

    def intersection(self, other: "EventInterval") -> "EventInterval | None":
        start, end = max(self.start, other.start), min(self.end, other.end)
        return EventInterval(start, end) if start < end else None


def normalize_boundaries(bounds: EventInterval, instants: Iterable[dt.datetime]) -> tuple[dt.datetime, ...]:
    """Clip, de-duplicate, and UTC-sort boundaries while preserving endpoint instants."""
    values = {bounds.start, bounds.end}
    values.update(value for value in instants if bounds.start < value < bounds.end)
    return tuple(sorted(values, key=lambda value: value.astimezone(dt.UTC)))


def partition_interval(bounds: EventInterval, boundaries: Iterable[dt.datetime]) -> tuple[EventInterval, ...]:
    points = normalize_boundaries(bounds, boundaries)
    return tuple(EventInterval(left, right) for left, right in zip(points, points[1:]) if left < right)


def subtract_intervals(bounds: EventInterval, exclusions: Iterable[EventInterval]) -> tuple[EventInterval, ...]:
    pieces = [bounds]
    for exclusion in sorted(exclusions):
        next_pieces: list[EventInterval] = []
        for piece in pieces:
            overlap = piece.intersection(exclusion)
            if overlap is None:
                next_pieces.append(piece)
                continue
            if piece.start < overlap.start:
                next_pieces.append(EventInterval(piece.start, overlap.start))
            if overlap.end < piece.end:
                next_pieces.append(EventInterval(overlap.end, piece.end))
        pieces = next_pieces
    return tuple(pieces)
