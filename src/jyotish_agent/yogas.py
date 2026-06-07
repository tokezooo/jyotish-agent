"""A small, deliberately narrow set of geometrically-defined yogas.

Yoga definitions vary widely across texts, which is dangerous for a fact-cited
product. So this module ships ONLY a few yogas whose definition is unambiguous and
purely positional, and it states the exact definition it used in the output. Each
result carries ``present`` plus the ``basis`` (the geometry that decided it), so an
agent can cite both the verdict and why.

Scope (D1 / Rasi chart, whole-sign):
- Gajakesari: Jupiter in a kendra (1/4/7/10) from the Moon.
- Chandra-Mangala: Moon and Mars in the same rasi (conjunction).
- Budha-Aditya: Sun and Mercury in the same rasi (conjunction).

These use same-sign conjunction / whole-sign house distance only — no orbs, no
strength/combustion/debilitation conditions (those vary by school and are out of
scope). The stated ``definition`` makes the convention explicit and reproducible.
"""

from __future__ import annotations

_KENDRAS = frozenset({1, 4, 7, 10})


def _signs_by_planet(d1_placements: list[dict]) -> dict[str, int]:
    return {
        p["planet"]: p["sign_index"]
        for p in d1_placements
        if p.get("planet") is not None and p.get("sign_index") is not None
    }


def _house_from(from_sign: int, to_sign: int) -> int:
    """Whole-sign house of `to_sign` counted from `from_sign` (1..12)."""
    return ((to_sign - from_sign) % 12) + 1


def detect_yogas(d1_placements: list[dict]) -> dict:
    """Return {yoga_name: {present, definition, basis}} for the supported yogas.

    Computed from the D1 (Rasi) chart only. If a yoga's required planets are absent,
    that yoga is OMITTED entirely (the verdict is not asserted false) — we don't claim
    "no Gajakesari" when we couldn't evaluate it."""
    signs = _signs_by_planet(d1_placements)
    results: dict[str, dict] = {}

    # Gajakesari: Jupiter in a kendra (1/4/7/10) from the Moon.
    moon, jup = signs.get("Moon"), signs.get("Jupiter")
    if moon is not None and jup is not None:
        house = _house_from(moon, jup)
        results["Gajakesari"] = {
            "present": house in _KENDRAS,
            "definition": "Jupiter in a kendra (1/4/7/10) from the Moon, whole-sign.",
            "basis": {"jupiter_house_from_moon": house},
        }

    # Chandra-Mangala: Moon and Mars in the same rasi (conjunction).
    mars = signs.get("Mars")
    if moon is not None and mars is not None:
        results["Chandra-Mangala"] = {
            "present": moon == mars,
            "definition": "Moon and Mars in the same rasi (same-sign conjunction).",
            "basis": {"moon_sign": moon, "mars_sign": mars},
        }

    # Budha-Aditya: Sun and Mercury in the same rasi (conjunction).
    sun, mercury = signs.get("Sun"), signs.get("Mercury")
    if sun is not None and mercury is not None:
        results["Budha-Aditya"] = {
            "present": sun == mercury,
            "definition": "Sun and Mercury in the same rasi (same-sign conjunction).",
            "basis": {"sun_sign": sun, "mercury_sign": mercury},
        }

    return results
