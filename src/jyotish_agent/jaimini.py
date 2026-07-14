"""Pure deterministic geometry and timing for the frozen Jaimini Core v1 profile.

Signs are zero based (Aries=0).  Degrees passed to karaka and special-lagna
helpers are ordinary zodiac/sign degrees; no PyJHora prediction routine is used.
Only :func:`capture_birth_snapshots` crosses the engine boundary, through the
already locked D1/D9 session callback.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN
from itertools import combinations
from typing import Callable, Literal, Mapping, Sequence
from zoneinfo import ZoneInfo

from .config import CalculationConfig
from .jaimini_models import ApproximateJaiminiBirthInput, ExactJaiminiBirthInput
from .pyjhora_facade import BirthProfile, _run_engine_session

_SEVEN_PLANETS = ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn")
_PLANET_INDICES = {name: index for index, name in enumerate((*_SEVEN_PLANETS, "Rahu", "Ketu"))}
_KARAKAS_7 = ("AK", "AmK", "BK", "MK", "PK", "GK", "DK")
_KARAKAS_8 = ("AK", "AmK", "BK", "MK", "PiK", "PK", "GK", "DK")
_FIXED_ORDER = ("Mars", "Ketu", "Saturn", "Rahu")
_YEAR_DAYS = Decimal("365.2425")
_DAY_MICROSECONDS = Decimal(86_400_000_000)


class ExactKarakaTieError(ValueError):
    """The frozen profile requires human adjudication for a one-arcsecond tie."""


@dataclass(frozen=True)
class KarakaResult:
    assignments: dict[str, str]
    scores_arcseconds: dict[str, int]
    near_ties: tuple[tuple[str, str], ...]


def _arcseconds(degrees: float) -> int:
    return int((Decimal(str(degrees % 30)) * 3600).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))


def chara_karakas(longitudes: Mapping[str, float], *, scheme: Literal[7, 8] = 7) -> KarakaResult:
    """Rank frozen-profile chara karakas, reversing Rahu within its sign."""
    if scheme not in {7, 8}:
        raise ValueError("scheme must be 7 or 8")
    planets = _SEVEN_PLANETS if scheme == 7 else (*_SEVEN_PLANETS, "Rahu")
    missing = [planet for planet in planets if planet not in longitudes]
    if missing:
        raise ValueError(f"missing karaka longitudes: {', '.join(missing)}")
    scores = {planet: _arcseconds(longitudes[planet]) for planet in planets}
    if scheme == 8:
        scores["Rahu"] = 30 * 3600 - scores["Rahu"]

    exact = [(a, b) for a, b in combinations(planets, 2) if scores[a] == scores[b]]
    if exact:
        names = ", ".join(f"{a}/{b}" for a, b in exact)
        raise ExactKarakaTieError(f"exact karaka tie requires adjudication: {names}")

    ranked = sorted(planets, key=lambda planet: scores[planet], reverse=True)
    labels = _KARAKAS_7 if scheme == 7 else _KARAKAS_8
    near = tuple(
        (ranked[index], ranked[index + 1])
        for index in range(len(ranked) - 1)
        if scores[ranked[index]] - scores[ranked[index + 1]] <= 60
    )
    return KarakaResult(
        assignments=dict(zip(labels, ranked, strict=True)),
        scores_arcseconds=scores,
        near_ties=near,
    )


def _sign(sign: int) -> int:
    if isinstance(sign, bool) or not isinstance(sign, int) or not 0 <= sign < 12:
        raise ValueError("sign must be an integer from 0 through 11")
    return sign


def rasi_drishti(source_sign: int) -> tuple[int, ...]:
    """Return Jaimini sign aspects in zodiac order for a zero-based source sign."""
    source = _sign(source_sign)
    movable = {0, 3, 6, 9}
    fixed = {1, 4, 7, 10}
    dual = {2, 5, 8, 11}
    if source in movable:
        targets = fixed - {(source + 1) % 12}
    elif source in fixed:
        targets = movable - {(source - 1) % 12}
    else:
        targets = dual - {source}
    return tuple(sorted(targets))


def arudha_pada(house_sign: int, lord_sign: int) -> int:
    """Count inclusively twice, applying the same/seventh -> tenth exception."""
    house, lord = _sign(house_sign), _sign(lord_sign)
    distance_minus_one = (lord - house) % 12
    pada = (lord + distance_minus_one) % 12
    if pada in {house, (house + 6) % 12}:
        return (house + 9) % 12
    return pada


def arudha_padas(lagna_sign: int, house_lord_signs: Sequence[int]) -> dict[str, int]:
    """Calculate A1-A12 and their AL/UL aliases from lord placements."""
    lagna = _sign(lagna_sign)
    if len(house_lord_signs) != 12:
        raise ValueError("house_lord_signs must contain exactly twelve signs")
    result = {
        f"A{house}": arudha_pada((lagna + house - 1) % 12, house_lord_signs[house - 1])
        for house in range(1, 13)
    }
    result["AL"] = result["A1"]
    result["UL"] = result["A12"]
    return result


def resolve_co_lord(
    candidates: Sequence[str],
    rashi_durations: Mapping[str, int | float],
    degrees: Mapping[str, int | float],
) -> str:
    """Resolve a Scorpio/Aquarius co-lord by the profile's three comparators."""
    if set(candidates) not in ({"Mars", "Ketu"}, {"Saturn", "Rahu"}) or len(candidates) != 2:
        raise ValueError("candidates must be the frozen Scorpio or Aquarius co-lord pair")
    order = {name: index for index, name in enumerate(_FIXED_ORDER)}
    return max(candidates, key=lambda name: (rashi_durations[name], degrees[name], -order[name]))


@dataclass(frozen=True)
class ArgalaPair:
    house: int
    obstruction_house: int
    contributors: tuple[str, ...]
    obstructors: tuple[str, ...]


def argala(source_sign: int, occupants: Mapping[int, Sequence[str]]) -> tuple[ArgalaPair, ...]:
    """Return primary 2/4/11 and secondary 5 argala with 12/10/3/9 obstruction."""
    source = _sign(source_sign)
    pairs = ((2, 12), (4, 10), (11, 3), (5, 9))

    def bodies(house: int) -> tuple[str, ...]:
        return tuple(occupants.get((source + house - 1) % 12, ()))

    return tuple(ArgalaPair(house, opposite, bodies(house), bodies(opposite)) for house, opposite in pairs)


def _chart_sign(chart: object, body: str) -> int:
    if isinstance(chart, Mapping):
        try:
            return _sign(int(chart[body][0]))
        except KeyError as exc:
            raise ValueError(f"D9 is missing {body}") from exc
    try:
        planet_index = None if body == "Lagna" else _PLANET_INDICES[body]
    except KeyError as exc:
        raise ValueError(f"unsupported D9 body: {body}") from exc
    for position in chart:  # type: ignore[union-attr]
        if position.planet_index == planet_index:
            return _sign(position.sign_index)
    raise ValueError(f"D9 is missing {body}")


def svamsa(d9: object) -> int:
    return _chart_sign(d9, "Lagna")


def karakamsa(d9: object, karakas: Mapping[str, str]) -> int:
    if "AK" not in karakas:
        raise ValueError("karakas are missing AK")
    return _chart_sign(d9, karakas["AK"])


def special_lagnas(*, sun_longitude: float, minutes_since_sunrise: float) -> dict[str, float]:
    """Compute selected BL/HL/GL at 120/60/24-minute-per-sign rates."""
    if not 0 <= sun_longitude < 360:
        raise ValueError("sun_longitude must be in [0, 360)")
    if minutes_since_sunrise < 0:
        raise ValueError("minutes_since_sunrise cannot be negative")
    return {
        "bhava_lagna": (sun_longitude + minutes_since_sunrise / 120 * 30) % 360,
        "hora_lagna": (sun_longitude + minutes_since_sunrise / 60 * 30) % 360,
        "ghati_lagna": (sun_longitude + minutes_since_sunrise / 24 * 30) % 360,
    }


@dataclass(frozen=True)
class AntardashaPeriod:
    sign: int
    start: dt.datetime
    end: dt.datetime

    def contains(self, instant: dt.datetime) -> bool:
        return self.start <= instant < self.end


@dataclass(frozen=True)
class CharaDashaPeriod:
    sign: int
    years: int
    start: dt.datetime
    end: dt.datetime
    antardashas: tuple[AntardashaPeriod, ...]

    def contains(self, instant: dt.datetime) -> bool:
        return self.start <= instant < self.end


def _add_years(start: dt.datetime, years: int) -> dt.datetime:
    micros = (Decimal(years) * _YEAR_DAYS * _DAY_MICROSECONDS).quantize(
        Decimal("1"), rounding=ROUND_HALF_EVEN
    )
    return start + dt.timedelta(microseconds=int(micros))


def _antardashas(sign: int, start: dt.datetime, end: dt.datetime) -> tuple[AntardashaPeriod, ...]:
    forward = sign % 2 == 0
    direction = 1 if forward else -1
    total_micros = int((end - start) / dt.timedelta(microseconds=1))
    boundaries = [
        start + dt.timedelta(
            microseconds=int((Decimal(total_micros) * index / 12).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))
        )
        for index in range(13)
    ]
    return tuple(
        AntardashaPeriod((sign + direction * (index + 1)) % 12, boundaries[index], boundaries[index + 1])
        for index in range(12)
    )


def chara_dasha(
    lagna_sign: int,
    lord_signs: Sequence[int],
    *,
    gender: Literal["female", "male"] | str,
    start: dt.datetime,
) -> tuple[CharaDashaPeriod, ...]:
    """Build the frozen maha/antardasha timeline from its gender-selected seed."""
    lagna = _sign(lagna_sign)
    if gender not in {"female", "male"}:
        raise ValueError("gender must be 'female' or 'male'")
    if start.tzinfo is None or start.utcoffset() is None:
        raise ValueError("start must be timezone-aware")
    if len(lord_signs) != 12:
        raise ValueError("lord_signs must contain exactly twelve signs")
    lords = tuple(_sign(sign) for sign in lord_signs)
    seed = lagna if gender == "male" else (lagna + 6) % 12
    direction = 1 if seed % 2 == 0 else -1
    signs = tuple((seed + direction * index) % 12 for index in range(12))
    periods: list[CharaDashaPeriod] = []
    cursor = start
    for sign in signs:
        sign_direction = 1 if sign % 2 == 0 else -1
        duration = (sign_direction * (lords[sign] - sign)) % 12
        years = max(1, duration)
        end = _add_years(cursor, years)
        periods.append(CharaDashaPeriod(sign, years, cursor, end, _antardashas(sign, cursor, end)))
        cursor = end
    return tuple(periods)


@dataclass(frozen=True)
class SensitivityResult:
    instants: tuple[dt.datetime, ...]
    samples: tuple[Mapping[str, object], ...]
    stability: dict[str, Literal["stable", "unstable"]]

    @property
    def sample_count(self) -> int:
        return len(self.instants)


def sensitivity_sweep(
    *,
    confidence: str,
    start: dt.datetime,
    end: dt.datetime | None,
    calculate: Callable[[dt.datetime], Mapping[str, object]],
) -> SensitivityResult:
    """Evaluate exact once or an inclusive, bounded five-minute approximate range."""
    if confidence == "exact":
        if end is not None:
            raise ValueError("exact confidence does not accept an end")
        instants = (start,)
    elif confidence == "approximate":
        if end is None or end <= start:
            raise ValueError("approximate confidence requires an ordered end")
        minutes = (end - start).total_seconds() / 60
        if minutes > 120:
            raise ValueError("approximate range cannot exceed 120 minutes")
        if minutes % 5:
            raise ValueError("approximate range boundaries must align to five minutes")
        instants = tuple(start + dt.timedelta(minutes=offset) for offset in range(0, int(minutes) + 1, 5))
    else:
        raise ValueError("unknown birth-time confidence is unsupported")
    samples = tuple(dict(calculate(instant)) for instant in instants)
    keys = set().union(*(sample.keys() for sample in samples))
    stability = {
        key: "stable" if all(key in sample and sample[key] == samples[0].get(key) for sample in samples) else "unstable"
        for key in sorted(keys)
    }
    return SensitivityResult(instants, samples, stability)


def _local_datetimes(
    birth: ExactJaiminiBirthInput | ApproximateJaiminiBirthInput,
) -> tuple[dt.datetime, ...]:
    zone = ZoneInfo(birth.place.timezone)
    if isinstance(birth, ExactJaiminiBirthInput):
        return (dt.datetime.combine(birth.date, birth.time, zone),)
    start = dt.datetime.combine(birth.date, birth.earliest_time, zone)
    end = dt.datetime.combine(birth.date, birth.latest_time, zone)
    minutes = int((end - start).total_seconds() // 60)
    return tuple(start + dt.timedelta(minutes=offset) for offset in range(0, minutes + 1, 5))


def capture_birth_snapshots(
    birth: ExactJaiminiBirthInput | ApproximateJaiminiBirthInput,
    *,
    reference_date: tuple[int, int, int],
) -> tuple[object, ...]:
    """Capture immutable natal D1/D9 snapshots only through the locked callback."""
    captured: list[object] = []
    for local in _local_datetimes(birth):
        offset = local.utcoffset()
        if offset is None:
            raise ValueError("birth timezone has no UTC offset")
        profile = BirthProfile(
            name=birth.place.name,
            date=(local.year, local.month, local.day),
            time=(local.hour, local.minute, local.second),
            latitude=birth.place.latitude,
            longitude=birth.place.longitude,
            timezone=offset.total_seconds() / 3600,
        )
        result = _run_engine_session(
            profile,
            reference_date,
            CalculationConfig(charts=("D1",)),
            domain_callback=lambda snapshot: snapshot,
        )
        captured.append(result.domain)
    return tuple(captured)
