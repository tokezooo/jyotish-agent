"""Strict Pydantic v2 boundary models for persisted research runs."""

from __future__ import annotations

import datetime as dt
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import BirthTimeConfidence, CalculationConfigRequest

_ID_RE = re.compile(r"^op_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


class FixedOffsetLegacy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["fixed_offset_legacy"]
    offset_hours: float = Field(ge=-12, le=14)


class IanaTimezone(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["iana"]
    zone_id: str = Field(min_length=1, max_length=100)


class IanaWithAssertedOffset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["iana_with_asserted_offset"]
    zone_id: str = Field(min_length=1, max_length=100)
    asserted_offset_hours: float = Field(ge=-12, le=14)


TimezoneSpec = Annotated[
    FixedOffsetLegacy | IanaTimezone | IanaWithAssertedOffset,
    Field(discriminator="kind"),
]


class ResearchPlace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timezone: float | TimezoneSpec


class ResearchBirthProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    date: dt.date
    time: dt.time
    place: ResearchPlace
    birth_time_confidence: BirthTimeConfidence = BirthTimeConfidence.exact

    @field_validator("date")
    @classmethod
    def supported_year(cls, value: dt.date) -> dt.date:
        if not 1800 <= value.year <= 2200:
            raise ValueError("year must be between 1800 and 2200")
        return value

    @field_validator("time")
    @classmethod
    def civil_time_has_no_embedded_offset(cls, value: dt.time) -> dt.time:
        if value.tzinfo is not None:
            raise ValueError("civil birth time must not include a UTC offset")
        return value


class CreateResearchRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str
    expected_revision: int = Field(default=0, ge=0)
    question: str = Field(min_length=1, max_length=10_000)
    birth_profile: ResearchBirthProfileRequest
    calculation_config: CalculationConfigRequest = Field(
        default_factory=CalculationConfigRequest
    )
    model_version: str = Field(min_length=1, max_length=200)
    planner_version: str = Field(min_length=1, max_length=200)
    corpus_version: str = Field(min_length=1, max_length=200)
    contract_version: str = Field(min_length=1, max_length=50)

    @field_validator("operation_id")
    @classmethod
    def valid_operation_id(cls, value: str) -> str:
        if not _ID_RE.fullmatch(value):
            raise ValueError("operation_id must be an op_ prefixed UUID4")
        return value


class TimezoneResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    original_civil_datetime: str
    mode: Literal["fixed_offset_legacy", "iana", "iana_with_asserted_offset"]
    resolved_offset_minutes: int
    utc_instant: str


class ResearchRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    revision: int
    status: str
    question: str
    birth_profile: dict
    calculation_config: dict
    reference_date: dt.date
    timezone_resolution: TimezoneResolution
    engine_name: str
    engine_version: str
    model_version: str
    planner_version: str
    corpus_version: str
    contract_version: str
    request_hash: str
    created_at: str
    updated_at: str


class ResearchEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    seq: int
    event_id: str
    operation_id: str | None
    event_type: str
    event_version: int
    schema_version: int
    payload: dict
    payload_hash: str
    previous_event_hash: str | None
    event_hash: str
    producer: str
    producer_version: str
    created_at: str


class ResearchEventsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[ResearchEventResponse]
