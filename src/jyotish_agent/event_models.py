"""Strict, replayable event anchors for non-natal calculations."""

from __future__ import annotations

import datetime as dt
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from .timezone_resolution import TimezoneResolutionError, resolve_iana


class EventPlace(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=200)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    zone_id: str = Field(min_length=1, max_length=100)
    fold: Literal[0, 1] | None = None

    @field_validator("zone_id")
    @classmethod
    def validate_iana(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("zone_id must be a real IANA timezone identifier") from exc
        return value


class EventAnchor(BaseModel):
    """An explicit civil instant whose offset must agree with its IANA zone."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    asked_at: dt.datetime
    place: EventPlace
    time_confidence: Literal["explicit", "captured_now"] = "explicit"

    @model_validator(mode="after")
    def resolve_and_validate(self) -> "EventAnchor":
        if self.asked_at.tzinfo is None or self.asked_at.utcoffset() is None:
            raise ValueError("asked_at must be timezone-aware RFC3339")
        civil = self.asked_at.replace(tzinfo=None)
        asserted = self.asked_at.utcoffset()
        assert asserted is not None
        try:
            resolve_iana(
                civil,
                mode="iana_with_asserted_offset",
                zone_id=self.place.zone_id,
                fold=self.place.fold,
                asserted_offset_hours=asserted.total_seconds() / 3600,
                longitude=self.place.longitude,
            )
        except TimezoneResolutionError as exc:
            raise ValueError(exc.error_code) from exc
        return self

    def resolved(self):
        offset = self.asked_at.utcoffset()
        assert offset is not None
        return resolve_iana(
            self.asked_at.replace(tzinfo=None),
            mode="iana_with_asserted_offset",
            zone_id=self.place.zone_id,
            fold=self.place.fold,
            asserted_offset_hours=offset.total_seconds() / 3600,
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
