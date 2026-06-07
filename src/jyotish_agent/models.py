"""Pydantic request/response models — the HTTP boundary.

These live at the API edge only. The engine layer (facade, config) stays on plain
dataclasses with no FastAPI/Pydantic dependency; ``to_birth_profile`` /
``to_calculation_config`` adapt across the boundary. Keeping the engine
Pydantic-free means the calculation code imports and tests without a web stack.

Date/time use ``datetime.date`` / ``datetime.time`` so Pydantic rejects impossible
values (2025-02-30, 25:00) with a 422 before any calculation runs.

MIRROR: the Pi extension's typebox schemas in ``.pi/extensions/jyotish.ts`` duplicate
these field shapes (ranges, enums, date/time formats, year bounds). Change both
together; the extension's drift-guard test only catches divergence it knows about.
"""

from __future__ import annotations

import datetime as _dt
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import DEFAULT_CHARTS, CalculationConfig
from .pyjhora_facade import BirthProfile

# Birth years PyJHora/pyswisseph compute reliably; outside this we'd risk a 500.
_MIN_YEAR = 1800
_MAX_YEAR = 2200
_MAX_NAME = 200


class BirthTimeConfidence(str, Enum):
    exact = "exact"
    approximate = "approximate"
    unknown = "unknown"


class Place(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=_MAX_NAME, description="Place label")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    # Offset in hours from UTC, e.g. 5.5 for IST. Required: no place/tz resolver yet.
    timezone: float = Field(ge=-12, le=14)


class BirthProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=_MAX_NAME)
    date: _dt.date
    time: _dt.time
    place: Place
    birth_time_confidence: BirthTimeConfidence = BirthTimeConfidence.exact

    @field_validator("date")
    @classmethod
    def _year_in_supported_range(cls, v: _dt.date) -> _dt.date:
        if not (_MIN_YEAR <= v.year <= _MAX_YEAR):
            raise ValueError(f"year must be between {_MIN_YEAR} and {_MAX_YEAR}")
        return v

    def to_birth_profile(self) -> BirthProfile:
        return BirthProfile(
            name=self.name,
            date=(self.date.year, self.date.month, self.date.day),
            time=(self.time.hour, self.time.minute, self.time.second),
            latitude=self.place.latitude,
            longitude=self.place.longitude,
            timezone=self.place.timezone,
        )


class CalculationConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ayanamsa: str = "LAHIRI"
    rahu_ketu: str = "true_nodes"
    # Divisional charts to compute. Unknown names are rejected by the engine (422);
    # D1 is always added. Defaults to D1+D9.
    charts: list[str] = Field(default_factory=lambda: list(DEFAULT_CHARTS))
    # Consumed by the route (defaults to today there), NOT by the engine config.
    reference_date: _dt.date | None = None

    def to_calculation_config(self) -> CalculationConfig:
        # ayanamsa / rahu_ketu / charts validity is enforced by the engine (single source).
        return CalculationConfig(
            ayanamsa=self.ayanamsa,
            rahu_ketu=self.rahu_ketu,
            charts=tuple(self.charts),
        )


class ValidateRequest(BirthProfileRequest):
    """Distinct type so the validate endpoint gets its own OpenAPI schema name."""


class ChartComputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    birth_profile: BirthProfileRequest
    config: CalculationConfigRequest = Field(default_factory=CalculationConfigRequest)


class ValidateResponse(BaseModel):
    normalized_profile: dict
    warnings: list[str]


class FactRef(BaseModel):
    """A citation to one computed fact, by its dotted path and the value claimed.
    See interpretations.iter_fact_atoms for valid paths."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, description="e.g. 'd1.Sun.sign', 'vimshottari.mahadasha.lord'")
    value: str | float | int


class AnswerContract(BaseModel):
    """The interpretive-answer shape. `facts_used` is validated against the computed
    facts so an answer can never cite a placement/dasha/panchanga it wasn't given."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    # Non-empty: an interpretive chart answer must cite at least one computed fact.
    # NOTE: this validates the facts the answer CHOSE to cite, not the prose — it
    # cannot detect a claim made in `summary` that was left out of facts_used.
    facts_used: list[FactRef] = Field(min_length=1)
    uncertainty: list[str] = Field(default_factory=list)
    followups: list[str] = Field(default_factory=list)


class ValidateAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: AnswerContract
    # The `facts` block AND `facts_token` from a prior /charts/compute response. The
    # token binds validation to real compute output (see signing.py); a forged or
    # modified facts block fails the integrity check.
    facts: dict
    facts_token: str


class ValidateAnswerResponse(BaseModel):
    valid: bool
    violations: list[str]


class ScreenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)


class ScreenResponse(BaseModel):
    safe: bool
    category: str | None
    redirect: str | None


class ChartComputeResponse(BaseModel):
    """Typed response contract for /charts/compute (what Phase 4 Pi consumes).

    `facts`, `normalized_input`, and `provenance` stay as dicts: their shape is the
    facade's deterministic output, kept in one place rather than duplicated here."""

    normalized_input: dict
    calculation_config: dict
    facts: dict
    provenance: dict
    warnings: list[str]
    # HMAC over `facts`; pass back to /answers/validate to prove the facts are real.
    facts_token: str
