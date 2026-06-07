"""The single place that talks to PyJHora.

Everything PyJHora touches is behind this facade: all ``jhora.*`` imports are local
to functions (so the package imports without the engine), the global-ayanamsa
critical section is held under ``ENGINE_LOCK``, and raw indices are turned into the
stable, self-describing fact structure the agent is allowed to cite.

Output is deterministic: no wall-clock timestamp is emitted, so a given
(birth profile, config, reference date) always serializes to byte-identical JSON.
That is what makes the golden-fixture test meaningful.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from . import ENGINE_VERSION, names
from .config import ENGINE_LOCK, CalculationConfig, apply_config, ephemeris_mode


class EngineOutputError(ValueError):
    """PyJHora returned a shape the facade did not expect (degenerate/changed output)."""

# Degrees are rounded to this many places everywhere, so float noise across
# libm/BLAS builds can't break byte-stability or the golden fixture.
_DEG_PRECISION = 6

DateTuple = tuple[int, int, int]  # (year, month, day)
TimeTuple = tuple[int, int, int]  # (hour, minute, second)


@dataclass(frozen=True)
class BirthProfile:
    """Normalized birth data. Explicit lat/lon/timezone required (no resolver yet)."""

    name: str
    date: DateTuple
    time: TimeTuple
    latitude: float
    longitude: float
    timezone: float  # offset in hours, e.g. 5.5 for IST


def _round_deg(value: float) -> float:
    return round(float(value), _DEG_PRECISION)


def _placements(chart) -> list[dict]:
    """Normalize a PyJHora divisional chart into stable placement dicts.

    PyJHora returns ``[['L', (sign, deg)], [planet_idx, (sign, deg)], ...]`` where the
    position is sometimes a tuple and sometimes a list. Lagna ('L') is excluded here
    and surfaced separately as the ascendant.

    NOTE: each divisional chart has its own lagna (varga lagna), but the MVP surfaces
    only the D1 ascendant and drops per-chart lagnas. Revisit if varga-lagna analysis
    is needed.
    """
    out: list[dict] = []
    for body, pos in chart:
        if body == "L":
            continue
        sign = int(pos[0])
        out.append(
            {
                "planet_index": int(body),
                "planet": names.planet_name(int(body)),
                "sign_index": sign,
                "sign": names.sign_name(sign),
                "degrees": _round_deg(pos[1]),
            }
        )
    return out


def _ascendant(chart) -> dict:
    for body, pos in chart:
        if body == "L":
            sign = int(pos[0])
            return {
                "sign_index": sign,
                "sign": names.sign_name(sign),
                "degrees": _round_deg(pos[1]),
            }
    raise EngineOutputError("no Lagna ('L') in chart output")


def _fmt_dt(dt) -> str:
    """Format a PyJHora date tuple (y, m, d, hour_float) as 'YYYY-MM-DDTHH:MM:SS'.

    Uses datetime+timedelta so an hour fraction near midnight (e.g. 23:59:59.6)
    rolls correctly into the next day/month/year instead of emitting an invalid
    'T24:00:00'. hour_float may be >24 or slightly negative in some PyJHora paths;
    timedelta handles both.
    """
    y, m, d = int(dt[0]), int(dt[1]), int(dt[2])
    hour_float = float(dt[3]) if len(dt) > 3 else 0.0
    base = datetime(y, m, d)
    # Round to whole seconds before adding, so output matches _DEG-style stability.
    moment = base + timedelta(seconds=round(hour_float * 3600))
    return moment.strftime("%Y-%m-%dT%H:%M:%S")


def _panchanga(jd, place) -> dict:
    from jhora.panchanga import drik

    tithi = drik.tithi(jd, place)
    nak = drik.nakshatra(jd, place)
    yoga = drik.yogam(jd, place)
    karana = drik.karana(jd, place)
    # Civil weekday so it always matches the calendar date in normalized_input.
    # PyJHora's default vaara is the Vedic (sunrise-to-sunrise) day, which can be
    # the previous weekday for a pre-sunrise birth — a silent mismatch we avoid.
    vaara = drik.vaara(jd, place, show_vedic_day=False)

    tithi_idx = int(tithi[0])
    nak_idx = int(nak[0])
    nak_pada = int(nak[1]) if len(nak) > 1 else None
    yoga_idx = int(yoga[0])
    karana_idx = int(karana[0])
    weekday_idx = int(vaara)

    return {
        "tithi": {"index": tithi_idx, "name": names.tithi_name(tithi_idx)},
        "nakshatra": {
            "index": nak_idx,
            "name": names.nakshatra_name(nak_idx),
            "pada": nak_pada,
        },
        "yoga": {"index": yoga_idx, "name": names.yoga_name(yoga_idx)},
        "karana": {"index": karana_idx, "name": names.karana_name(karana_idx)},
        "weekday": {"index": weekday_idx, "name": names.weekday_name(weekday_idx)},
    }


def _period_entry(lords_tuple, start, end) -> dict:
    """Build one Vimshottari period level from a running-ladder entry. The lord of a
    level is the last entry in its lords tuple (maha -> (m,), bhukti -> (m, b), ...)."""
    lord = int(lords_tuple[-1])
    return {
        "lord_index": lord,
        "lord": names.planet_name(lord),
        "start": _fmt_dt(start),
        "end": _fmt_dt(end),
    }


# Running-ladder depth (1=maha, 2=bhukti, 3=antara) -> output key.
_DASHA_LEVELS = {1: "mahadasha", 2: "bhukti", 3: "antara"}


def _vimshottari_current(ref_jd, jd, place) -> dict:
    from jhora.horoscope.dhasa.graha import vimsottari

    levels: dict[str, dict | None] = {k: None for k in _DASHA_LEVELS.values()}
    # Request only the 3 levels we surface; PyJHora defaults to 6 (down to deha).
    # A reference date before the dasha span (e.g. before birth) makes PyJHora raise;
    # that is a legitimate "no running period", so degrade to empty levels.
    try:
        ladder = vimsottari.get_running_dhasa_for_given_date(
            ref_jd, jd, place, dhasa_level_index=3
        )
    except ValueError:
        return levels
    if not ladder:
        return levels
    for entry in ladder:
        lords, start, end = entry[0], entry[1], entry[2]
        key = _DASHA_LEVELS.get(len(lords))
        if key is not None:
            levels[key] = _period_entry(lords, start, end)
    return levels


def compute_chart(
    profile: BirthProfile,
    reference_date: DateTuple,
    config: CalculationConfig | None = None,
) -> dict:
    """Compute the MVP fact set for a birth profile at a reference date.

    Returns a deterministic, JSON-serializable dict: ascendant, D1, D9, panchanga
    basics, current Vimshottari period, plus the config and provenance used. Holds
    ENGINE_LOCK across the whole apply+compute so concurrent callers cannot swap
    PyJHora's global ayanamsa mid-computation.
    """
    config = config or CalculationConfig()

    with ENGINE_LOCK:
        from jhora import utils
        from jhora.horoscope.chart import charts
        from jhora.panchanga import drik

        applied = apply_config(config)
        resolved = applied.resolved_charts()  # {name: factor}, always includes D1
        place = drik.Place(profile.name, profile.latitude, profile.longitude, profile.timezone)
        jd = utils.julian_day_number(profile.date, profile.time)
        # Anchor the reference at local noon to avoid date-boundary ambiguity.
        ref_jd = utils.julian_day_number(reference_date, (12, 0, 0))

        raw_charts = {
            name: charts.divisional_chart(jd, place, divisional_chart_factor=factor)
            for name, factor in resolved.items()
        }
        panchanga = _panchanga(jd, place)
        vimshottari = _vimshottari_current(ref_jd, jd, place)

    # Each divisional chart becomes a lowercase fact key (d1, d9, d10, ...). The
    # ascendant is taken from D1, which resolved_charts guarantees is present.
    divisional_facts = {name.lower(): _placements(chart) for name, chart in raw_charts.items()}
    ascendant = _ascendant(raw_charts["D1"])

    return {
        "normalized_input": {
            "name": profile.name,
            "date": list(profile.date),
            "time": list(profile.time),
            "latitude": profile.latitude,
            "longitude": profile.longitude,
            "timezone": profile.timezone,
            "reference_date": list(reference_date),
        },
        "calculation_config": {
            "ayanamsa": applied.ayanamsa,
            "rahu_ketu": applied.rahu_ketu,
            "charts": list(resolved),
            # reference_date drives the running Vimshottari period; surfaced here so a
            # quoted/cached result is fully reproducible from calculation_config alone.
            "reference_date": list(reference_date),
        },
        "facts": {
            "ascendant": ascendant,
            **divisional_facts,
            "panchanga": panchanga,
            "vimshottari": vimshottari,
        },
        "provenance": {
            "engine": "PyJHora",
            "engine_version": ENGINE_VERSION,
            "ephemeris_mode": ephemeris_mode(),
        },
    }
