"""Canonical index -> name tables for Jyotish facts.

PyJHora returns calculations as bare integer indices (planet 0..8, sign 0..11,
nakshatra 0..26, etc.). Its human-readable names come from locale resource files
that can change and are not stable for a machine-readable contract. We own the
English names here so chart facts are deterministic and self-describing.

Every lookup is index-safe: out-of-range indices return ``None`` rather than
raising, and the raw index is always preserved alongside the name in facade output.
"""

from __future__ import annotations

# PyJHora planet indices. 'L' (Lagna/Ascendant) is handled separately.
PLANETS = (
    "Sun",
    "Moon",
    "Mars",
    "Mercury",
    "Jupiter",
    "Venus",
    "Saturn",
    "Rahu",
    "Ketu",
)

# Rasi (zodiac sign) 0..11.
SIGNS = (
    "Aries",
    "Taurus",
    "Gemini",
    "Cancer",
    "Leo",
    "Virgo",
    "Libra",
    "Scorpio",
    "Sagittarius",
    "Capricorn",
    "Aquarius",
    "Pisces",
)

# Nakshatra 0..26.
NAKSHATRAS = (
    "Ashwini",
    "Bharani",
    "Krittika",
    "Rohini",
    "Mrigashira",
    "Ardra",
    "Punarvasu",
    "Pushya",
    "Ashlesha",
    "Magha",
    "Purva Phalguni",
    "Uttara Phalguni",
    "Hasta",
    "Chitra",
    "Swati",
    "Vishakha",
    "Anuradha",
    "Jyeshtha",
    "Mula",
    "Purva Ashadha",
    "Uttara Ashadha",
    "Shravana",
    "Dhanishta",
    "Shatabhisha",
    "Purva Bhadrapada",
    "Uttara Bhadrapada",
    "Revati",
)

# Weekday (vaara). PyJHora vaara is 0=Sunday..6=Saturday.
WEEKDAYS = (
    "Sunday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
)

# Tithi 1..30 (Shukla 1-15 ending in Purnima, Krishna 16-30 ending in Amavasya).
_TITHI_BASE = (
    "Pratipada",
    "Dwitiya",
    "Tritiya",
    "Chaturthi",
    "Panchami",
    "Shashthi",
    "Saptami",
    "Ashtami",
    "Navami",
    "Dashami",
    "Ekadashi",
    "Dwadashi",
    "Trayodashi",
    "Chaturdashi",
)
TITHIS = (
    tuple(f"Shukla {t}" for t in _TITHI_BASE)
    + ("Purnima",)
    + tuple(f"Krishna {t}" for t in _TITHI_BASE)
    + ("Amavasya",)
)

# Yoga 0..26.
YOGAS = (
    "Vishkambha",
    "Priti",
    "Ayushman",
    "Saubhagya",
    "Shobhana",
    "Atiganda",
    "Sukarma",
    "Dhriti",
    "Shula",
    "Ganda",
    "Vriddhi",
    "Dhruva",
    "Vyaghata",
    "Harshana",
    "Vajra",
    "Siddhi",
    "Vyatipata",
    "Variyana",
    "Parigha",
    "Shiva",
    "Siddha",
    "Sadhya",
    "Shubha",
    "Shukla",
    "Brahma",
    "Indra",
    "Vaidhriti",
)

# Karana: 11 distinct types (7 movable repeat + 4 fixed).
KARANAS = (
    "Bava",
    "Balava",
    "Kaulava",
    "Taitila",
    "Gara",
    "Vanija",
    "Vishti",
    "Shakuni",
    "Chatushpada",
    "Naga",
    "Kimstughna",
)


def _lookup(table: tuple[str, ...], index: int) -> str | None:
    """Return table[index] or None if out of range. Never raises."""
    return table[index] if isinstance(index, int) and 0 <= index < len(table) else None


def planet_name(i: int) -> str | None:
    return _lookup(PLANETS, i)


def sign_name(i: int) -> str | None:
    return _lookup(SIGNS, i)


def nakshatra_name(i: int) -> str | None:
    return _lookup(NAKSHATRAS, i)


def weekday_name(i: int) -> str | None:
    return _lookup(WEEKDAYS, i)


def yoga_name(i: int) -> str | None:
    return _lookup(YOGAS, i)


def karana_name(i: int) -> str | None:
    return _lookup(KARANAS, i)


def tithi_name(i: int) -> str | None:
    """Tithi tables are 1-based in PyJHora (1..30); convert to 0-based index."""
    if isinstance(i, int) and 1 <= i <= len(TITHIS):
        return TITHIS[i - 1]
    return None
