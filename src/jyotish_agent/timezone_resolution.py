"""Deterministic civil-time resolution using the installed IANA tzdb."""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import TZPATH, ZoneInfo, ZoneInfoNotFoundError


class TimezoneResolutionError(ValueError):
    def __init__(self, error_code: str):
        self.error_code = error_code
        super().__init__(error_code)


@dataclass(frozen=True)
class ResolvedTimezone:
    mode: str
    zone_id: str | None
    tzdb_fingerprint: str
    offset_minutes: int
    utc_instant: dt.datetime
    fold: int
    warnings: tuple[str, ...]


def _fingerprint(zone_id: str) -> str:
    for root in TZPATH:
        path = Path(root) / zone_id
        if path.is_file():
            return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    # A loaded zone can come from the tzdata wheel. Its TZif bytes are still
    # the replay-relevant artifact, not the mutable package version label.
    try:
        from importlib.resources import files
        data = files("tzdata.zoneinfo").joinpath(*zone_id.split("/")).read_bytes()
    except (ImportError, FileNotFoundError, ModuleNotFoundError):
        raise TimezoneResolutionError("MISSING_TIMEZONE_MATERIAL") from None
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _coordinate_warnings(longitude: float, offset_minutes: int) -> tuple[str, ...]:
    solar_offset = longitude * 4.0
    if abs(solar_offset - offset_minutes) > 180:
        return ("COORDINATE_TIMEZONE_MISMATCH",)
    return ()


def resolve_iana(civil: dt.datetime, *, mode: str, zone_id: str,
                 fold: int | None, asserted_offset_hours: float | None,
                 longitude: float) -> ResolvedTimezone:
    try:
        zone = ZoneInfo(zone_id)
    except ZoneInfoNotFoundError:
        raise TimezoneResolutionError("UNKNOWN_TIMEZONE") from None

    candidates: list[tuple[int, dt.datetime, dt.timedelta]] = []
    for candidate_fold in (0, 1):
        aware = civil.replace(tzinfo=zone, fold=candidate_fold)
        utc = aware.astimezone(dt.UTC)
        back = utc.astimezone(zone)
        offset = aware.utcoffset()
        if back.replace(tzinfo=None) == civil and back.fold == candidate_fold and offset:
            candidates.append((candidate_fold, utc, offset))
    if not candidates:
        raise TimezoneResolutionError("NONEXISTENT_LOCAL_TIME")
    distinct = {item[2] for item in candidates}
    if len(distinct) > 1 and fold is None:
        raise TimezoneResolutionError("AMBIGUOUS_LOCAL_TIME")
    selected_fold = 0 if fold is None else fold
    selected = next((item for item in candidates if item[0] == selected_fold), None)
    if selected is None:
        raise TimezoneResolutionError("NONEXISTENT_LOCAL_TIME")
    offset_minutes = round(selected[2].total_seconds() / 60)
    if asserted_offset_hours is not None:
        asserted_minutes = asserted_offset_hours * 60
        if abs(asserted_minutes - offset_minutes) > 1 + 1e-9:
            raise TimezoneResolutionError("TIMEZONE_OFFSET_MISMATCH")
    return ResolvedTimezone(
        mode=mode, zone_id=zone_id, tzdb_fingerprint=_fingerprint(zone_id),
        offset_minutes=offset_minutes, utc_instant=selected[1], fold=selected[0],
        warnings=_coordinate_warnings(longitude, offset_minutes),
    )


def resolve_fixed(civil: dt.datetime, *, offset_hours: float,
                  longitude: float) -> ResolvedTimezone:
    raw = offset_hours * 60
    minutes = round(raw)
    if abs(raw - minutes) > 1e-9:
        raise TimezoneResolutionError("OFFSET_NOT_WHOLE_MINUTES")
    utc = (civil - dt.timedelta(minutes=minutes)).replace(tzinfo=dt.UTC)
    return ResolvedTimezone(
        mode="fixed_offset_legacy", zone_id=None,
        tzdb_fingerprint="fixed-offset:v1", offset_minutes=minutes,
        utc_instant=utc, fold=0,
        warnings=_coordinate_warnings(longitude, minutes),
    )
