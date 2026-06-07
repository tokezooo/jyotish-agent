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

# Karana. PyJHora returns a 1-based index in [1..60] (drik.karana docstring:
# "1 = Kimstugna, 2 = Bava, ..., 60 = Naga"), NOT an 11-type index. The cycle is:
# position 1 = Kimstughna (fixed), positions 2..57 = the 7 movable karanas repeating,
# positions 58/59/60 = Shakuni/Chatushpada/Naga (fixed).
_MOVABLE_KARANAS = (
    "Bava",
    "Balava",
    "Kaulava",
    "Taitila",
    "Gara",
    "Vanija",
    "Vishti",
)
KARANAS_60 = (
    ("Kimstughna",)
    + tuple(_MOVABLE_KARANAS[(pos - 2) % 7] for pos in range(2, 58))
    + ("Shakuni", "Chatushpada", "Naga")
)


# Classical rasi (sign) lords, by sign index -> planet index. Used for house lords.
# MVP uses classical single-lord rulerships only — no exaltation, and no Rahu/Ketu
# co-lordship of Aquarius/Scorpio.
SIGN_LORDS: tuple[int, ...] = (
    2,  # Aries -> Mars
    5,  # Taurus -> Venus
    3,  # Gemini -> Mercury
    1,  # Cancer -> Moon
    0,  # Leo -> Sun
    3,  # Virgo -> Mercury
    5,  # Libra -> Venus
    2,  # Scorpio -> Mars
    4,  # Sagittarius -> Jupiter
    6,  # Capricorn -> Saturn
    6,  # Aquarius -> Saturn
    4,  # Pisces -> Jupiter
)
assert len(SIGN_LORDS) == 12, "SIGN_LORDS must cover all 12 signs"


def _lookup(table: tuple[str, ...], index: int) -> str | None:
    """Return table[index] or None if out of range. Never raises."""
    return table[index] if isinstance(index, int) and 0 <= index < len(table) else None


def sign_lord_index(sign_index: int) -> int | None:
    """Planet index that rules the given sign, or None if out of range."""
    return SIGN_LORDS[sign_index] if 0 <= sign_index < len(SIGN_LORDS) else None


def planet_name(i: int) -> str | None:
    return _lookup(PLANETS, i)


def sign_name(i: int) -> str | None:
    return _lookup(SIGNS, i)


def weekday_name(i: int) -> str | None:
    """Vaara is 0-based in PyJHora (0=Sunday..6=Saturday)."""
    return _lookup(WEEKDAYS, i)


def _lookup_1based(table: tuple[str, ...], i: int) -> str | None:
    """PyJHora returns nakshatra/yoga/karana/tithi as 1-based indices. Map to the
    0-based table; return None if out of [1..len]. Never raises."""
    return table[i - 1] if isinstance(i, int) and 1 <= i <= len(table) else None


def nakshatra_name(i: int) -> str | None:
    """Nakshatra is 1-based in PyJHora (1=Ashwini..27=Revati)."""
    return _lookup_1based(NAKSHATRAS, i)


def yoga_name(i: int) -> str | None:
    """Yoga is 1-based in PyJHora (1=Vishkambha..27=Vaidhriti)."""
    return _lookup_1based(YOGAS, i)


def karana_name(i: int) -> str | None:
    """Karana is 1-based in PyJHora (1=Kimstughna..60=Naga)."""
    return _lookup_1based(KARANAS_60, i)


def tithi_name(i: int) -> str | None:
    """Tithi is 1-based in PyJHora (1..30)."""
    return _lookup_1based(TITHIS, i)
