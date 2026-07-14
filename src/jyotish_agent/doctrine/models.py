"""Shared immutable value objects for the doctrine bounded context."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class FrozenModel(BaseModel):
    """Strict immutable base for deterministic doctrine values."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DoctrineDomain(StrEnum):
    JAIMINI = "jaimini"
    PRASHNA = "prashna"
    MUHURTA = "muhurta"


class SchoolRole(StrEnum):
    ROOT_TEXT = "root_text"
    BASELINE = "baseline"
    COMMENTARY = "commentary"
    OVERLAY = "overlay"
    WORKED_EXAMPLES = "worked_examples"


class LicenseClass(StrEnum):
    PUBLIC_DOMAIN = "public_domain"
    PERMISSIVE = "permissive"
    LICENSED_LOCAL = "licensed_local"
    COPYRIGHTED_LOCAL = "copyrighted_local"


class ScanQuality(StrEnum):
    BORN_DIGITAL = "born_digital"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"


class OcrStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    REQUIRED = "required"
    COMPLETED = "completed"
    REVIEWED = "reviewed"
