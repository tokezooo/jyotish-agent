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

from . import ENGINE_VERSION, names
from .config import ENGINE_LOCK, CalculationConfig, apply_config, ephemeris_mode

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
    raise ValueError("no Lagna ('L') in chart output")


def _fmt_dt(dt) -> str:
    """Format a PyJHora date tuple (y, m, d, hour_float) as 'YYYY-MM-DDTHH:MM:SS'."""
    y, m, d = int(dt[0]), int(dt[1]), int(dt[2])
    hour_float = float(dt[3]) if len(dt) > 3 else 0.0
    hh = int(hour_float)
    minute_float = (hour_float - hh) * 60
    mm = int(minute_float)
    ss = int(round((minute_float - mm) * 60))
    # Carry rounding overflow (e.g. 59.6s -> next minute) without a datetime dep.
    if ss == 60:
        ss = 0
        mm += 1
    if mm == 60:
        mm = 0
        hh += 1
    return f"{y:04d}-{m:02d}-{d:02d}T{hh:02d}:{mm:02d}:{ss:02d}"


def _panchanga(jd, place) -> dict:
    from jhora.panchanga import drik

    tithi = drik.tithi(jd, place)
    nak = drik.nakshatra(jd, place)
    yoga = drik.yogam(jd, place)
    karana = drik.karana(jd, place)
    vaara = drik.vaara(jd, place)

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


def _period_entry(lords_tuple, start, end, depth: int) -> dict | None:
    """Build one Vimshottari period level from a running-ladder entry."""
    if len(lords_tuple) < depth:
        return None
    lord = int(lords_tuple[depth - 1])
    return {
        "lord_index": lord,
        "lord": names.planet_name(lord),
        "start": _fmt_dt(start),
        "end": _fmt_dt(end),
    }


def _vimshottari_current(ref_jd, jd, place) -> dict:
    from jhora.horoscope.dhasa.graha import vimsottari

    ladder = vimsottari.get_running_dhasa_for_given_date(ref_jd, jd, place)
    # ladder = [[(maha,), start, end], [(maha,bhukti), start, end],
    #           [(maha,bhukti,antara), start, end]]
    levels: dict[str, dict | None] = {
        "mahadasha": None,
        "bhukti": None,
        "antara": None,
    }
    for entry in ladder:
        lords, start, end = entry[0], entry[1], entry[2]
        depth = len(lords)
        if depth == 1:
            levels["mahadasha"] = _period_entry(lords, start, end, 1)
        elif depth == 2:
            levels["bhukti"] = _period_entry(lords, start, end, 2)
        elif depth == 3:
            levels["antara"] = _period_entry(lords, start, end, 3)
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
        place = drik.Place(profile.name, profile.latitude, profile.longitude, profile.timezone)
        jd = utils.julian_day_number(profile.date, profile.time)
        ref_jd = utils.julian_day_number(reference_date, (12, 0, 0))

        d1 = charts.divisional_chart(jd, place, divisional_chart_factor=1)
        d9 = charts.divisional_chart(jd, place, divisional_chart_factor=9)
        panchanga = _panchanga(jd, place)
        vimshottari = _vimshottari_current(ref_jd, jd, place)

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
        },
        "facts": {
            "ascendant": _ascendant(d1),
            "d1": _placements(d1),
            "d9": _placements(d9),
            "panchanga": panchanga,
            "vimshottari": vimshottari,
        },
        "provenance": {
            "engine": "PyJHora",
            "engine_version": ENGINE_VERSION,
            "ephemeris_mode": ephemeris_mode(),
        },
    }
