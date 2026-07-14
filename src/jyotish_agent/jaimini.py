"""Pure deterministic geometry and timing for the frozen Jaimini Core v1 profile.

Signs are zero based (Aries=0).  Degrees passed to karaka and special-lagna
helpers are ordinary zodiac/sign degrees; no PyJHora prediction routine is used.
Only :func:`capture_birth_snapshots` crosses the engine boundary, through the
already locked D1/D9 session callback.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN
from itertools import combinations
from typing import Callable, Literal, Mapping, Sequence
from zoneinfo import ZoneInfo

from . import ENGINE_VERSION, names
from .config import CalculationConfig
from .jaimini_models import (
    ApproximateJaiminiBirthInput,
    ExactJaiminiBirthInput,
    JaiminiCompletedResult,
    JaiminiFact,
    JaiminiInput,
    JaiminiLimitation,
    JaiminiProvenance,
    JaiminiRuleProfile,
    JaiminiSection,
    JaiminiTruncation,
)
from .pyjhora_facade import BirthProfile, _run_engine_session
from .rule_profiles import (
    jaimini_rule_profile_sha256,
    jaimini_source_admission_verified,
    jaimini_source_map_sha256,
    load_jaimini_rule_profile,
    load_jaimini_source_map,
)
from .signing import cache_domain_artifact

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


def _rules(profile: JaiminiRuleProfile | None) -> JaiminiRuleProfile:
    return profile if profile is not None else load_jaimini_rule_profile()


def rasi_drishti(
    source_sign: int, *, profile: JaiminiRuleProfile | None = None
) -> tuple[int, ...]:
    """Return Jaimini sign aspects in zodiac order for a zero-based source sign."""
    source = _sign(source_sign)
    rules = _rules(profile).rasi_drishti
    movable = {0, 3, 6, 9}
    fixed = {1, 4, 7, 10}
    dual = {2, 5, 8, 11}
    if source in movable:
        if rules.movable != "non_adjacent_fixed":
            raise ValueError("unsupported rasi drishti movable variant")
        targets = fixed - {(source + 1) % 12}
    elif source in fixed:
        if rules.fixed != "non_adjacent_movable":
            raise ValueError("unsupported rasi drishti fixed variant")
        targets = movable - {(source - 1) % 12}
    else:
        if rules.dual != "other_dual":
            raise ValueError("unsupported rasi drishti dual variant")
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
    status: Literal["absent", "unobstructed", "partial", "obstructed"]


def argala(
    source_sign: int,
    occupants: Mapping[int, Sequence[str]],
    *,
    profile: JaiminiRuleProfile | None = None,
) -> tuple[ArgalaPair, ...]:
    """Return primary 2/4/11 and secondary 5 argala with 12/10/3/9 obstruction."""
    source = _sign(source_sign)
    rules = _rules(profile).argala
    pairs = rules.obstruction_pairs

    def bodies(house: int) -> tuple[str, ...]:
        return tuple(occupants.get((source + house - 1) % 12, ()))

    def pair(house: int, opposite: int) -> ArgalaPair:
        contributors, obstructors = bodies(house), bodies(opposite)
        if not contributors:
            status = rules.empty_status
        elif not obstructors:
            status = rules.zero_obstructors_status
        elif len(obstructors) < len(contributors):
            status = rules.fewer_obstructors_status
        else:
            status = rules.equal_or_more_obstructors_status
        return ArgalaPair(house, opposite, contributors, obstructors, status)

    return tuple(pair(house, opposite) for house, opposite in pairs)


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


def svamsa(d9: object, *, profile: JaiminiRuleProfile | None = None) -> int:
    rules = _rules(profile).svamsa
    if rules.svamsa != "d9_lagna_sign":
        raise ValueError("unsupported svamsa variant")
    return _chart_sign(d9, "Lagna")


def karakamsa(
    d9: object,
    karakas: Mapping[str, str],
    *,
    profile: JaiminiRuleProfile | None = None,
) -> int:
    rules = _rules(profile).svamsa
    if rules.karakamsa != "d9_atmakaraka_sign":
        raise ValueError("unsupported karakamsa variant")
    if "AK" not in karakas:
        raise ValueError("karakas are missing AK")
    return _chart_sign(d9, karakas["AK"])


def special_lagnas(
    *,
    sun_longitude: float,
    minutes_since_sunrise: float,
    profile: JaiminiRuleProfile | None = None,
) -> dict[str, float]:
    """Compute selected BL/HL/GL at 120/60/24-minute-per-sign rates."""
    if not 0 <= sun_longitude < 360:
        raise ValueError("sun_longitude must be in [0, 360)")
    if minutes_since_sunrise < 0:
        raise ValueError("minutes_since_sunrise cannot be negative")
    rules = _rules(profile).special_lagnas
    rates = rules.rates_minutes_per_sign
    return {
        name: (sun_longitude + minutes_since_sunrise / getattr(rates, name) * 30) % 360
        for name in rules.included
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


def _sample_instants(
    *, confidence: str, start: dt.datetime, end: dt.datetime | None
) -> tuple[dt.datetime, ...]:
    if confidence == "exact":
        if end is not None:
            raise ValueError("exact confidence does not accept an end")
        return (start,)
    if confidence != "approximate":
        raise ValueError("unknown birth-time confidence is unsupported")
    if end is None or end <= start:
        raise ValueError("approximate confidence requires an ordered end")
    seconds = (end - start).total_seconds()
    if seconds > 120 * 60:
        raise ValueError("approximate range cannot exceed 120 minutes")
    if seconds % (5 * 60):
        raise ValueError("approximate range width must be divisible by five minutes")
    return tuple(
        start + dt.timedelta(seconds=offset)
        for offset in range(0, int(seconds) + 1, 5 * 60)
    )


def sensitivity_sweep(
    *,
    confidence: str,
    start: dt.datetime,
    end: dt.datetime | None,
    calculate: Callable[[dt.datetime], Mapping[str, object]],
) -> SensitivityResult:
    """Evaluate exact once or an inclusive, bounded five-minute approximate range."""
    instants = _sample_instants(confidence=confidence, start=start, end=end)
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
        start = dt.datetime.combine(birth.date, birth.time, zone)
        return _sample_instants(confidence="exact", start=start, end=None)
    start = dt.datetime.combine(birth.date, birth.earliest_time, zone)
    end = dt.datetime.combine(birth.date, birth.latest_time, zone)
    return _sample_instants(confidence="approximate", start=start, end=end)


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


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _position_map(chart: object) -> tuple[int, dict[int, tuple[int, float]]]:
    lagna: int | None = None
    planets: dict[int, tuple[int, float]] = {}
    for position in chart:  # type: ignore[union-attr]
        if position.planet_index is None:
            lagna = int(position.sign_index)
        else:
            planets[int(position.planet_index)] = (
                int(position.sign_index),
                float(position.degrees),
            )
    if lagna is None or any(index not in planets for index in range(9)):
        raise ValueError("Jaimini snapshot is incomplete")
    return lagna, planets


def _facts_for_snapshot(
    snapshot: object,
    request: JaiminiInput,
    *,
    birth_start: dt.datetime,
) -> tuple[tuple[str, tuple[JaiminiFact, ...]], ...]:
    profile = load_jaimini_rule_profile()
    lagna, planets = _position_map(snapshot.d1)  # type: ignore[union-attr]
    _d9_lagna, _d9_planets = _position_map(snapshot.d9)  # type: ignore[union-attr]
    longitudes = {
        names.PLANETS[index]: sign * 30 + degrees
        for index, (sign, degrees) in planets.items()
    }
    seven = chara_karakas(longitudes, scheme=7)
    eight = chara_karakas(longitudes, scheme=8)

    karaka_facts = tuple(
        JaiminiFact(fact_id=f"jaimini.karakas.7.{label}", value=planet)
        for label, planet in seven.assignments.items()
    ) + tuple(
        JaiminiFact(fact_id=f"jaimini.karakas.8.{label}", value=planet)
        for label, planet in eight.assignments.items()
    )

    lord_signs = tuple(
        planets[names.sign_lord_index(sign)][0]  # type: ignore[index]
        for sign in range(12)
    )
    padas = arudha_padas(lagna, lord_signs)
    occupants: dict[int, list[str]] = {}
    for index, (sign, _degrees) in planets.items():
        occupants.setdefault(sign, []).append(names.PLANETS[index])
    geometry = [
        JaiminiFact(fact_id="jaimini.lagna.sign", value=names.SIGNS[lagna]),
        JaiminiFact(
            fact_id="jaimini.svamsa.sign",
            value=names.SIGNS[svamsa(snapshot.d9, profile=profile)],  # type: ignore[union-attr]
        ),
        JaiminiFact(
            fact_id="jaimini.karakamsa.sign",
            value=names.SIGNS[
                karakamsa(snapshot.d9, seven.assignments, profile=profile)  # type: ignore[union-attr]
            ],
        ),
    ]
    geometry.extend(
        JaiminiFact(fact_id=f"jaimini.arudha.{key}", value=names.SIGNS[value])
        for key, value in sorted(padas.items())
    )
    geometry.extend(
        JaiminiFact(
            fact_id=f"jaimini.rasi_drishti.{names.SIGNS[sign]}",
            value=",".join(names.SIGNS[target] for target in rasi_drishti(sign, profile=profile)),
        )
        for sign in range(12)
    )
    geometry.extend(
        JaiminiFact(
            fact_id=f"jaimini.argala.lagna.{pair.house}_vs_{pair.obstruction_house}",
            value=pair.status,
        )
        for pair in argala(lagna, occupants, profile=profile)
    )

    sections: list[tuple[str, tuple[JaiminiFact, ...]]] = [
        ("chara_karakas", karaka_facts),
        ("core_geometry", tuple(geometry)),
    ]
    if request.analysis_scope == "core_with_chara_dasha":
        periods = chara_dasha(
            lagna,
            lord_signs,
            gender=request.gender or "male",
            start=birth_start,
        )
        dasha: list[JaiminiFact] = []
        reference = dt.datetime.combine(
            request.reference_date or request.birth.date,
            dt.time(12),
            dt.timezone.utc,
        )
        for index, period in enumerate(periods, 1):
            prefix = f"jaimini.chara_dasha.{index}"
            dasha.extend(
                (
                    JaiminiFact(fact_id=f"{prefix}.sign", value=names.SIGNS[period.sign]),
                    JaiminiFact(fact_id=f"{prefix}.start", value=period.start.isoformat()),
                    JaiminiFact(fact_id=f"{prefix}.end", value=period.end.isoformat()),
                    JaiminiFact(fact_id=f"{prefix}.active", value=period.contains(reference)),
                )
            )
        sections.append(("chara_dasha", tuple(dasha)))
    return tuple(sections)


class JaiminiFacade:
    """Pure deterministic Jaimini Core facade over immutable engine snapshots."""

    def calculate(self, request: JaiminiInput) -> JaiminiCompletedResult:
        reference_date = request.reference_date or request.birth.date
        snapshots = capture_birth_snapshots(
            request.birth,
            reference_date=(reference_date.year, reference_date.month, reference_date.day),
        )
        local_instants = _local_datetimes(request.birth)
        if len(snapshots) != len(local_instants):
            raise ValueError("Jaimini sensitivity sample count mismatch")
        samples = tuple(
            _facts_for_snapshot(snapshot, request, birth_start=instant.astimezone(dt.UTC))
            for snapshot, instant in zip(snapshots, local_instants, strict=True)
        )
        sample_maps = tuple(
            {
                fact.fact_id: fact.value
                for _section_id, facts in sample
                for fact in facts
            }
            for sample in samples
        )
        stability = {
            path: "stable"
            if all(sample.get(path) == sample_maps[0].get(path) for sample in sample_maps)
            else "unstable"
            for path in sample_maps[0]
        }
        sections = tuple(
            JaiminiSection(
                section_id=section_id,
                facts=tuple(
                    fact.model_copy(update={"stability": stability[fact.fact_id]})
                    for fact in facts
                ),
            )
            for section_id, facts in samples[0]
        )
        all_facts = [
            fact.model_dump(mode="json")
            for section in sections
            for fact in section.facts
        ]

        source_map = load_jaimini_source_map()
        source_available = jaimini_source_admission_verified()
        normalized_anchor = {
            "confidence": request.birth.confidence,
            "timezone": request.birth.place.timezone,
            "utc_instants": [instant.astimezone(dt.UTC).isoformat() for instant in local_instants],
        }
        profile_payload = {
            "profile": request.profile,
            "birth": request.birth.model_dump(mode="json"),
        }
        effective_config = {
            "rule_profile": request.rule_profile,
            "analysis_scope": request.analysis_scope,
            "gender": request.gender,
            "reference_date": reference_date.isoformat(),
            "include_trace": request.include_trace,
            "engine_config": snapshots[0].config.__dict__,
        }
        provenance = JaiminiProvenance(
            rule_profile_version=source_map.rule_profile_version,
            rule_profile_sha256=jaimini_rule_profile_sha256(),
            source_map_sha256=jaimini_source_map_sha256(),
            source_review_status=source_map.review.status,
            source_reviewer=source_map.review.reviewer,
            source_reviewer_role=source_map.review.reviewer_role,
            engine_version=ENGINE_VERSION,
            ephemeris="moshier-or-installed-swiss",
            tzdb_version="system-zoneinfo",
        )
        artifact = cache_domain_artifact(
            {
                "mode": "jaimini",
                "normalized_anchor_sha256": _canonical_hash(normalized_anchor),
                "profile_sha256": _canonical_hash(profile_payload),
                "config_sha256": _canonical_hash(effective_config),
                "rule_profile_sha256": provenance.rule_profile_sha256,
                "source_map_sha256": provenance.source_map_sha256,
                "facts": all_facts,
                "provenance": provenance.model_dump(mode="json"),
            }
        )
        unstable_count = sum(value == "unstable" for value in stability.values())
        limitations = [
            JaiminiLimitation(
                code="SPECIAL_LAGNAS_NOT_COMPUTED",
                message="Special lagnas require a separately verified sunrise primitive.",
            )
        ]
        if not source_available:
            limitations.append(
                JaiminiLimitation(
                    code="SOURCE_ADMISSION_UNVERIFIED",
                    message="Interpretation is unavailable until every rule/source mapping is admitted.",
                )
            )
        if unstable_count:
            limitations.append(
                JaiminiLimitation(
                    code="BIRTH_TIME_SENSITIVE",
                    message=f"{unstable_count} facts change across the declared birth-time range.",
                )
            )
        sample_count = len(local_instants)
        anchor_summary = (
            "exact birth anchor; 1 sample"
            if request.birth.confidence == "exact"
            else f"approximate birth anchor; {sample_count} samples at 5-minute steps"
        )
        request_hash = _canonical_hash(
            {
                "anchor": artifact["normalized_anchor_sha256"],
                "config": artifact["config_sha256"],
            }
        )
        return JaiminiCompletedResult(
            status="completed",
            request_id=f"req_{request_hash[:24]}",
            profile_name=request.profile,
            anchor_summary=anchor_summary,
            sections=sections,
            truncation=JaiminiTruncation(
                truncated=False,
                total_count=len(all_facts),
                returned_count=len(all_facts),
            ),
            warnings=(),
            limitations=tuple(limitations),
            interpretation_status="available" if source_available else "unavailable",
            interpretation=("Admitted source mappings support the computed facts.",)
            if source_available
            else None,
            provenance=provenance,
            artifact_id=artifact["artifact_id"],
            artifact_sha256=artifact["artifact_sha256"],
            artifact_token=artifact["artifact_token"],
        )
