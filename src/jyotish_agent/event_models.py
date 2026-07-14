"""Strict, replayable event anchors for non-natal calculations."""

from __future__ import annotations

import datetime as dt
import re
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from .timezone_resolution import TimezoneResolutionError, resolve_iana


class EventPlace(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    name: str = Field(min_length=1, max_length=200)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    zone_id: str = Field(min_length=1, max_length=100)
    fold: Literal[0, 1] | None = None

    @field_validator("zone_id")
    @classmethod
    def validate_iana(cls, value: str) -> str:
        if (
            "/" not in value
            or value.startswith(("Etc/", "GMT", "UTC", "posix/", "right/"))
        ):
            raise ValueError("zone_id must be a regional IANA timezone, not a fixed-offset alias")
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("zone_id must be a real IANA timezone identifier") from exc
        return value


class EventAnchor(BaseModel):
    """An explicit civil instant whose offset must agree with its IANA zone."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    asked_at: dt.datetime
    place: EventPlace
    time_confidence: Literal["explicit", "captured_now"] = "explicit"

    @field_validator("asked_at", mode="before")
    @classmethod
    def strict_rfc3339(cls, value: object) -> object:
        if not isinstance(value, str) or re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",
            value,
        ) is None:
            raise ValueError("asked_at must be a strict timezone-aware RFC3339 string")
        return value

    @model_validator(mode="after")
    def resolve_and_validate(self) -> "EventAnchor":
        if self.asked_at.tzinfo is None or self.asked_at.utcoffset() is None:
            raise ValueError("asked_at must be timezone-aware RFC3339")
        civil = self.asked_at.replace(tzinfo=None)
        try:
            resolved = resolve_iana(
                civil,
                mode="iana",
                zone_id=self.place.zone_id,
                fold=self.place.fold,
                asserted_offset_hours=None,
                longitude=self.place.longitude,
            )
        except TimezoneResolutionError as exc:
            raise ValueError(exc.error_code) from exc
        asserted = self.asked_at.utcoffset()
        assert asserted is not None
        if asserted.total_seconds() != resolved.offset_minutes * 60:
            raise ValueError("TIMEZONE_OFFSET_MISMATCH")
        return self

    def resolved(self):
        offset = self.asked_at.utcoffset()
        assert offset is not None
        return resolve_iana(
            self.asked_at.replace(tzinfo=None),
            mode="iana",
            zone_id=self.place.zone_id,
            fold=self.place.fold,
            asserted_offset_hours=None,
            longitude=self.place.longitude,
        )

    @computed_field(return_type=dt.datetime)
    @property
    def normalized_utc(self) -> dt.datetime:
        return self.resolved().utc_instant

    @computed_field(return_type=int)
    @property
    def resolved_fold(self) -> int:
        return self.resolved().fold

    @computed_field(return_type=str)
    @property
    def tzdb_fingerprint(self) -> str:
        return self.resolved().tzdb_fingerprint
