"""Birth-data normalization and non-fatal warnings.

Hard validation (types, ranges, required fields) is enforced by the Pydantic models
and surfaces as 422. This module produces the *normalized* view of valid input plus
soft warnings: things that don't block a computation but should temper trust in the
result, such as a non-exact or on-the-hour birth time. (Unknown divisional charts are
a hard error from the engine, not a soft warning.)
"""

from __future__ import annotations

from .models import BirthProfileRequest, BirthTimeConfidence


def normalized_profile(req: BirthProfileRequest) -> dict:
    """Stable, echo-safe normalized representation of a valid birth profile."""
    return {
        "name": req.name,
        "date": req.date.isoformat(),
        "time": req.time.isoformat(),
        "place": {
            "name": req.place.name,
            "latitude": req.place.latitude,
            "longitude": req.place.longitude,
            "timezone": req.place.timezone,
        },
        "birth_time_confidence": req.birth_time_confidence.value,
    }


def profile_warnings(req: BirthProfileRequest) -> list[str]:
    warnings: list[str] = []
    if req.birth_time_confidence != BirthTimeConfidence.exact:
        warnings.append(
            f"Birth time confidence is '{req.birth_time_confidence.value}'. The "
            "ascendant, house placements, and Vimshottari timing are sensitive to "
            "birth time and may be imprecise."
        )
    # Only nag about an on-the-hour time when precision wasn't already asserted —
    # an 'exact' 06:00:00 birth is fine and shouldn't train users to ignore warnings.
    if (
        req.birth_time_confidence != BirthTimeConfidence.exact
        and req.time.second == 0
        and req.time.minute == 0
    ):
        warnings.append(
            "Birth time is on the hour (HH:00:00); confirm this is the exact time, "
            "not a rounded estimate."
        )
    return warnings
