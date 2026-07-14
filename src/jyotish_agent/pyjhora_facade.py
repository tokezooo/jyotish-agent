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

import re
import math
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Generic, TypeVar

from . import ENGINE_VERSION, names
from .config import ENGINE_LOCK, CalculationConfig, ConfigError, apply_config, ephemeris_mode
from .yogas import detect_yogas


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


@dataclass(frozen=True)
class _EnginePosition:
    """Immutable normalized engine position; ``None`` identifies Lagna."""

    planet_index: int | None
    sign_index: int
    degrees: float


@dataclass(frozen=True)
class _EngineConfigSnapshot:
    """Deeply immutable effective configuration exposed to domain callbacks."""

    ayanamsa: str
    rahu_ketu: str
    node_aspects: str
    charts: tuple[str, ...]
    modules: tuple[str, ...]


@dataclass(frozen=True)
class _EngineSnapshot:
    """Domain-safe D1/D9 primitives captured under one applied configuration."""

    config: _EngineConfigSnapshot
    d1: tuple[_EnginePosition, ...]
    d9: tuple[_EnginePosition, ...]
    sun_longitude_at_sunrise: float | None
    minutes_since_sunrise: float | None
    ephemeris_mode: str


_DomainT = TypeVar("_DomainT")


@dataclass(frozen=True)
class _EngineSessionResult(Generic[_DomainT]):
    natal: dict
    snapshot: _EngineSnapshot
    domain: _DomainT | None


class _EngineSessionReentryError(RuntimeError):
    """The current thread tried to enter the non-reentrant engine session twice."""


@dataclass(frozen=True)
class _MuhurtaBoundaryPrimitive:
    kind: str
    start_hour: float
    end_hour: float | None = None


@dataclass(frozen=True)
class _MuhurtaDayPrimitives:
    civil_date: date
    values: tuple[_MuhurtaBoundaryPrimitive, ...]


@dataclass(frozen=True)
class _MuhurtaBoundaryDayResult:
    day: _MuhurtaDayPrimitives
    config: _EngineConfigSnapshot
    ephemeris_mode: str


_ENGINE_SESSION_LOCAL = threading.local()


def _clock_hour(value: object) -> float:
    """Convert PyJHora's local clock strings, including ``(+1)``, to day hours."""
    text = str(value)
    day_offset = 24.0 if "(+1)" in text else 0.0
    clock = text.split()[0]
    hour, minute, second = (int(part) for part in clock.split(":"))
    return day_offset + hour + minute / 60 + second / 3600


def _run_muhurta_boundary_day(
    profile: BirthProfile,
    civil_date: date,
    utc_offset_hours: float,
    config: CalculationConfig | None = None,
) -> _MuhurtaBoundaryDayResult:
    """Collect one civil day's transitions in one configured lock checkpoint.

    Values are copied into immutable, domain-neutral records; raw engine objects do
    not escape. A range caller invokes this once per day so cancellation/deadline
    checks happen while the global engine lock is released.
    """
    config = config or CalculationConfig(charts=("D1",))
    resolved_charts = config.resolved_charts()
    resolved_modules = config.resolved_modules()
    if getattr(_ENGINE_SESSION_LOCAL, "active", False):
        raise _EngineSessionReentryError("engine session re-entry is not allowed")
    _ENGINE_SESSION_LOCAL.active = True
    try:
        with ENGINE_LOCK:
            from . import config as runtime_config
            from jhora import utils
            from jhora.panchanga import drik

            applied = apply_config(config)
            # PyJHora Place carries a numeric offset, so the range caller resolves
            # the IANA offset independently for each civil day (DST-safe).
            place = drik.Place(profile.name, profile.latitude, profile.longitude, utc_offset_hours)
            values: list[_MuhurtaBoundaryPrimitive] = []

            def jd_at(hour: int, minute: int = 0, second: int = 0):
                return utils.julian_day_number(
                    (civil_date.year, civil_date.month, civil_date.day), (hour, minute, second)
                )

            midnight_jd = jd_at(0)
            sunrise, sunset = drik.sunrise(midnight_jd, place), drik.sunset(midnight_jd, place)
            values.extend((
                _MuhurtaBoundaryPrimitive("sunrise", float(sunrise[0])),
                _MuhurtaBoundaryPrimitive("sunset", float(sunset[0])),
            ))

            def add_current_period(kind: str, result: object, start_index: int, end_index: int) -> None:
                if not isinstance(result, (tuple, list)) or len(result) <= max(start_index, end_index):
                    raise EngineOutputError(f"{kind} returned an unsupported transition shape")
                try:
                    start_hour, end_hour = float(result[start_index]), float(result[end_index])
                except (TypeError, ValueError) as exc:
                    raise EngineOutputError(f"{kind} returned a non-numeric transition") from exc
                if not (math.isfinite(start_hour) and math.isfinite(end_hour) and end_hour > start_hour):
                    raise EngineOutputError(f"{kind} returned invalid transition bounds")
                values.extend((
                    _MuhurtaBoundaryPrimitive(kind, start_hour),
                    _MuhurtaBoundaryPrimitive(kind, end_hour),
                ))

            # Six-hour astronomical probes are not minute brute force. Every
            # panchanga period here is longer than the probe step; aggregating its
            # current start/end catches every same-day transition, including the
            # second karana, while independently validating output variants.
            for hour in (0, 6, 12, 18, 23):
                probe = jd_at(hour, 59 if hour == 23 else 0)
                add_current_period("tithi_transition", drik.tithi(probe, place), 1, 2)
                add_current_period("nakshatra_transition", drik.nakshatra(probe, place), 2, 3)
                add_current_period("yoga_transition", drik.yogam(probe, place), 1, 2)
                add_current_period("karana_transition", drik.karana(probe, place), 1, 2)
                varjyam = drik.varjyam(probe, place)
                if not isinstance(varjyam, (tuple, list)) or len(varjyam) % 2:
                    raise EngineOutputError("varjyam returned an unsupported transition shape")
                for index in range(0, len(varjyam), 2):
                    start_hour, end_hour = float(varjyam[index]), float(varjyam[index + 1])
                    if not (math.isfinite(start_hour) and math.isfinite(end_hour) and end_hour > start_hour):
                        raise EngineOutputError("varjyam returned invalid transition bounds")
                    values.append(_MuhurtaBoundaryPrimitive("varjyam", start_hour, end_hour))

            for sign, start_hour, end_hour in drik.udhaya_lagna_muhurtha(midnight_jd, place):
                values.append(_MuhurtaBoundaryPrimitive(f"lagna_{int(sign)}", float(start_hour), float(end_hour)))
            for kind, function in (
                ("rahu_kala", drik.raahu_kaalam),
                ("yamaganda", drik.yamaganda_kaalam),
                ("gulika", drik.gulikai_kaalam),
                ("abhijit", drik.abhijit_muhurta),
            ):
                period = function(midnight_jd, place)
                if not period or len(period) < 2:
                    raise EngineOutputError(f"{kind} returned an unsupported period shape")
                values.append(_MuhurtaBoundaryPrimitive(kind, _clock_hour(period[0]), _clock_hour(period[1])))
            dur = drik.durmuhurtam(midnight_jd, place)
            if len(dur) % 2:
                raise EngineOutputError("durmuhurta returned an unsupported period shape")
            for index in range(0, len(dur), 2):
                values.append(_MuhurtaBoundaryPrimitive("durmuhurta", _clock_hour(dur[index]), _clock_hour(dur[index + 1])))
            for period in drik.amrit_kaalam(midnight_jd, place) or ():
                if not period or len(period) < 2:
                    raise EngineOutputError("amrita returned an unsupported period shape")
                values.append(_MuhurtaBoundaryPrimitive("amrita", _clock_hour(period[0]), _clock_hour(period[1])))

            # Stable de-duplication after all independent probes.
            unique: dict[tuple[str, float, float | None], _MuhurtaBoundaryPrimitive] = {}
            for value in values:
                key = (value.kind, round(value.start_hour, 6), None if value.end_hour is None else round(value.end_hour, 6))
                if key[2] is not None and key[2] <= key[1]:
                    continue
                unique.setdefault(key, _MuhurtaBoundaryPrimitive(*key))
            snapshot = _EngineConfigSnapshot(
                ayanamsa=applied.ayanamsa.upper(), rahu_ketu=applied.rahu_ketu,
                node_aspects=applied.node_aspects, charts=tuple(resolved_charts),
                modules=tuple(sorted(resolved_modules)),
            )
            return _MuhurtaBoundaryDayResult(
                day=_MuhurtaDayPrimitives(
                    civil_date,
                    tuple(unique[key] for key in sorted(unique, key=lambda item: (item[0], item[1], float("-inf") if item[2] is None else item[2]))),
                ),
                config=snapshot, ephemeris_mode=runtime_config.ephemeris_mode(),
            )
    finally:
        _ENGINE_SESSION_LOCAL.active = False


def _round_deg(value: float) -> float:
    return round(float(value), _DEG_PRECISION)


def _immutable_positions(chart) -> tuple[_EnginePosition, ...]:
    """Copy a mutable PyJHora chart into a stable immutable representation."""
    return tuple(
        _EnginePosition(
            planet_index=None if body == "L" else int(body),
            sign_index=int(pos[0]),
            degrees=_round_deg(pos[1]),
        )
        for body, pos in chart
    )


def _special_lagna_primitive(drik, jd, place, profile: BirthProfile) -> tuple[float | None, float | None]:
    """Capture sunrise-anchored inputs; caller owns the configured engine lock."""
    birth_hour = profile.time[0] + profile.time[1] / 60 + profile.time[2] / 3600
    sunrise = drik.sunrise(jd, place)
    if not sunrise or birth_hour < float(sunrise[0]):
        return None, None
    sunrise_jd_utc = float(sunrise[2]) - profile.timezone / 24
    return (
        _round_deg(drik.solar_longitude(sunrise_jd_utc)),
        round((birth_hour - float(sunrise[0])) * 60, 6),
    )


def _placements(chart) -> list[dict]:
    """Normalize a PyJHora divisional chart into stable placement dicts.

    PyJHora returns ``[['L', (sign, deg)], [planet_idx, (sign, deg)], ...]`` where the
    position is sometimes a tuple and sometimes a list. Lagna ('L') is excluded here
    and surfaced separately as the ascendant.

    NOTE: each divisional chart has its own lagna (varga lagna); ``house`` below is
    whole-sign and computed relative to THAT chart's own lagna, so D9 houses are from
    the navamsa lagna, etc. The MVP surfaces the D1 ascendant as the top-level
    ascendant but drops the other charts' lagna sign/degree.
    """
    lagna_sign = _lagna_sign(chart)
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
                # Whole-sign house: 1 = lagna sign, counted forward.
                "house": ((sign - lagna_sign) % 12) + 1,
            }
        )
    return out


def _lagna_pos(chart):
    """Return the lagna (sign, degrees) position tuple, or raise."""
    for body, pos in chart:
        if body == "L":
            return pos
    raise EngineOutputError("no Lagna ('L') in chart output")


def _lagna_sign(chart) -> int:
    return int(_lagna_pos(chart)[0])


def _ascendant(chart) -> dict:
    pos = _lagna_pos(chart)
    sign = int(pos[0])
    return {
        "sign_index": sign,
        "sign": names.sign_name(sign),
        "degrees": _round_deg(pos[1]),
    }


def _aspects(chart, node_aspects: str = "standard") -> dict:
    """Graha drishti for a chart: which signs/houses/planets each planet aspects.

    Whole-sign graha drishti. Conjunctions (same sign) are not aspects. Houses are
    relative to the chart's own lagna. Keyed by planet name for stable, citable output
    (atom path ``aspects.<From>.<To>``)."""
    lagna = _lagna_sign(chart)
    planet_signs = {int(body): int(pos[0]) for body, pos in chart if body != "L"}
    result: dict[str, dict] = {}
    for pidx, sign in planet_signs.items():
        aspected = sorted({(sign + off) % 12 for off in names.aspect_offsets(pidx, node_aspects)})
        aspected_set = set(aspected)
        hit_planets = sorted(
            names.planet_name(other)
            for other, osign in planet_signs.items()
            if other != pidx and osign in aspected_set
        )
        result[names.planet_name(pidx)] = {
            "aspected_sign_indices": aspected,
            "aspected_signs": [names.sign_name(s) for s in aspected],
            "aspected_houses": [((s - lagna) % 12) + 1 for s in aspected],
            "aspects_planets": hit_planets,
        }
    return result


# Shadbala applies to the seven classical grahas only (no Rahu/Ketu by definition).
_SHADBALA_PLANETS = tuple(range(7))
# Row order of strength.shad_bala output, verified against strength.py:995 and the
# classical naisargika constants (Sun 60 ... Saturn 8.57 virupas). kaala BEFORE dig.
_SHADBALA_COMPONENTS = ("sthana", "kaala", "dig", "cheshta", "naisargika", "drik")


def _shadbala(jd, place) -> dict:
    """Six-fold planetary strength for the 7 classical grahas.

    Emits per planet exactly: `rupas` (total strength in rupas), `strength_ratio`
    (rupas / classical minimum), and `components` (six named virupa values). Field
    names match the citation atoms one-to-one so a path copied from the JSON always
    validates. Values are engine output rounded to 2dp; `drik` can be negative."""
    import math as _math

    from jhora.horoscope.chart import strength

    sb = strength.shad_bala(jd, place)
    # Expected engine shape: 9 rows (6 components, sum, rupa, ratio) x 7 planets.
    if len(sb) < 9 or any(len(row) < len(_SHADBALA_PLANETS) for row in sb[:9]):
        raise EngineOutputError(f"shad_bala returned unexpected shape {len(sb)} rows")
    out: dict[str, dict] = {}
    for p in _SHADBALA_PLANETS:
        values = [float(sb[i][p]) for i in range(9)]
        if not all(_math.isfinite(v) for v in values):
            raise EngineOutputError(f"shad_bala returned non-finite value for planet {p}")
        components = {
            name: round(values[i], 2) for i, name in enumerate(_SHADBALA_COMPONENTS)
        }
        out[names.planet_name(p)] = {
            "components": components,
            "rupas": round(values[7], 2),
            "strength_ratio": round(values[8], 2),
        }
    return out


# BAV row order of get_ashtaka_varga output: Sun..Saturn then Lagna (row 7), per
# ashtakavarga.planet_list ['sun',...,'saturn','lagnam'].
_ASHTAKAVARGA_ROWS = tuple(names.PLANETS[:7]) + ("Lagna",)


def _ashtakavarga(chart_d1) -> dict:
    """Bhinna (BAV) and Samudaya (SAV) Ashtakavarga from the D1 chart.

    These are the RAW (pre-sodhana) tables — no trikona/ekadhipatya reductions
    applied. Input must be the RAW engine D1 chart (with 'L' and the nodes):
    the engine derives contributor positions from the full house->planet list,
    so the normalized placements (which drop 'L') must NOT be used here. Emits
    `sav` (12 signs; bindus always total 337) and `bav` (8 rows: the 7 classical
    grahas plus "Lagna", each cell 0..8 bindus per sign)."""
    from jhora import utils
    from jhora.horoscope.chart import ashtakavarga

    h_to_p = utils.get_house_planet_list_from_planet_positions(chart_d1)
    bav, sav, _pav = ashtakavarga.get_ashtaka_varga(h_to_p)
    if len(sav) != 12:
        raise EngineOutputError(
            f"get_ashtaka_varga returned unexpected SAV shape {len(sav)} signs"
        )
    if len(bav) != 8 or any(len(row) != 12 for row in bav):
        raise EngineOutputError(
            f"get_ashtaka_varga returned unexpected BAV shape {len(bav)} rows"
        )
    def _bindu(v, what: str) -> int:
        # Strict: these become authoritative cited facts. Reject bools, non-integral
        # floats, and out-of-range values instead of silently coercing.
        if isinstance(v, bool) or not isinstance(v, (int, float)) or int(v) != v:
            raise EngineOutputError(f"non-integral {what} bindu {v!r}")
        return int(v)

    sav_named = {names.sign_name(s): _bindu(sav[s], "SAV") for s in range(12)}
    bav_named: dict[str, dict] = {}
    for p, row_name in enumerate(_ASHTAKAVARGA_ROWS):
        row: dict[str, int] = {}
        for s in range(12):
            b = _bindu(bav[p][s], f"BAV[{row_name}]")
            if not 0 <= b <= 8:
                raise EngineOutputError(f"BAV[{row_name}] bindu {b} outside 0..8")
            row[names.sign_name(s)] = b
        bav_named[row_name] = row
    if sum(sav_named.values()) != 337:
        raise EngineOutputError(
            f"SAV total {sum(sav_named.values())} != 337 (classical invariant)"
        )
    return {"sav": sav_named, "bav": bav_named}


# The engine's yoga scan (yoga.get_yoga_details) eval()s ~284 '<fn>_from_jd_place'
# checks, CATCHES every per-yoga exception and print()s it ("Error executing ..." via
# utils.show_exception) — so a failing yoga silently vanishes from the result. We
# capture stdout/stderr and count marker lines so a shrunken yoga list surfaces as
# engine_errors > 0 / status "partial" instead of passing silently.
_YOGA_ENGINE_ERROR_MARKER = "Error executing"
# Engine fn keys are snake_case already (verified: 'vesi_yoga', 'dharidhra_yoga_149');
# sanitized defensively anyway so a resource-file change can't break atom paths.
_YOGA_KEY_SANITIZE = re.compile(r"[^a-z0-9_]+")


def _yogas_engine(jd, place, resolved: dict[str, int]) -> dict:
    """PyJHora's own yoga scan per configured chart — the UNAUDITED second tier.

    Detection definitions are the engine's and are NOT independently verified; the
    skill mandates hedged phrasing, and our geometric ``facts["yogas"]`` tier stays
    authoritative on any conflict (see ``_yoga_tier_mismatches``). Detected-only:
    presence is implied by inclusion, absence is never asserted as a fact. The
    engine's benefit/prediction prose ("You will ...") is deliberately excluded —
    deterministic-outcome text must not become citable facts.

    Returns ``{"status": "ok"|"partial", "engine_errors": <int>, "charts":
    {<chart lowercase>: [{"key", "name"}]}}`` where ``key`` is the engine's stable
    snake_case function key (e.g. ``vesi_yoga`` — the dict key of get_yoga_details'
    result, not the locale display name) and ``name`` the English display name.
    ``status`` is "partial" when the engine printed per-yoga errors (the list may be
    silently short). Must run under ENGINE_LOCK (reads global ayanamsa state).
    """
    import contextlib
    import io

    # NOTE: redirect_stdout/redirect_stderr swap PROCESS-global streams. This runs
    # under ENGINE_LOCK in a single-process local service, so the ~60ms window can
    # at worst swallow an unrelated log line — accepted for the MVP over a
    # subprocess round-trip. Revisit if this ever serves concurrent multi-worker
    # traffic. The first jhora yoga import also prints path noise, so the import
    # happens INSIDE the capture boundary.
    engine_errors = 0
    charts_out: dict[str, list[dict]] = {}
    _import_buf = io.StringIO()
    with contextlib.redirect_stdout(_import_buf), contextlib.redirect_stderr(_import_buf):
        from jhora.horoscope.chart import yoga as engine_yoga
    for name, factor in resolved.items():
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            # Returns (detected: {fn_key: [chart_id, name, description, benefits]},
            # found_count, total_count); counts are redundant with len(detected).
            detected, _found, _total = engine_yoga.get_yoga_details(
                jd, place, divisional_chart_factor=factor, language="en"
            )
        # Anchored: the engine prints exactly "Error executing <fn> ..." per failed
        # yoga; substring matching would overcount multi-line tracebacks.
        engine_errors += sum(
            1
            for line in buf.getvalue().splitlines()
            if line.startswith(_YOGA_ENGINE_ERROR_MARKER)
        )
        entries: list[dict] = []
        for fn_key, details in detected.items():
            key = _YOGA_KEY_SANITIZE.sub("_", str(fn_key).lower()).strip("_")
            if not key:
                continue
            display = (
                str(details[1])
                if isinstance(details, (list, tuple)) and len(details) > 1
                else key
            )
            entries.append({"key": key, "name": display})
        charts_out[name.lower()] = entries
    return {
        "status": "ok" if engine_errors == 0 else "partial",
        "engine_errors": engine_errors,
        "charts": charts_out,
    }


# Degraded yogas_engine payload when the whole engine scan raises. engine_errors=-1
# distinguishes "could not run" from "ran with N suppressed failures".
_YOGAS_ENGINE_UNAVAILABLE = {"status": "unavailable", "engine_errors": -1, "charts": {}}


def _yoga_tier_mismatches(our_yogas: dict, engine_yogas: dict) -> list[str]:
    """Cross-check the two yoga tiers on the one yoga both cover (Gajakesari).

    Our verified geometric tier is authoritative; a disagreement with the engine's
    unaudited detection is surfaced as a warning string for the agent to relay as
    uncertainty — never as a changed verdict. Engine matching is exact
    normalized-key equality against 'gaja_kesari_yoga'. Skipped unless the engine
    scan completed cleanly (status "ok") — on "partial"/"unavailable" absence
    means nothing."""
    ours = our_yogas.get("Gajakesari")
    # Compare only when the engine scan is fully trustworthy: on "partial" the very
    # function under comparison may be among the failed ones, so its absence means
    # nothing and would produce a false mismatch warning.
    if ours is None or engine_yogas.get("status") != "ok":
        return []
    d1_entries = (engine_yogas.get("charts") or {}).get("d1") or []
    # Exact normalized-key equality: substring matching would accept unrelated keys.
    engine_present = any(
        str(e.get("key", "")).replace("_", "") == "gajakesariyoga" for e in d1_entries
    )
    our_present = bool(ours.get("present"))
    if our_present == engine_present:
        return []
    return [
        "yoga tier mismatch: the verified geometric tier (facts.yogas) says "
        f"Gajakesari present={str(our_present).lower()} but the PyJHora engine "
        f"{'detects' if engine_present else 'does not detect'} a gajakesari-like "
        "yoga in D1. The verified tier is authoritative; treat the engine verdict "
        "as unverified."
    ]


def _planet_sign(chart, planet_index: int) -> int:
    """Sign index of a planet in a raw engine chart, or raise."""
    for body, pos in chart:
        if body != "L" and int(body) == planet_index:
            return int(pos[0])
    raise EngineOutputError(f"planet {planet_index} not in chart output")


def _transits(ref_jd, place, natal_moon_sign: int, natal_lagna_sign: int,
              reference_date: DateTuple, timezone: float) -> dict:
    """Classical gochara: D1 planet positions at the REFERENCE moment, not birth.

    ``ref_jd`` must be ``reference_date`` at local noon (the caller computes it that
    way); the anchor is surfaced so the snapshot convention is a visible fact — the
    Moon moves ~13°/day, so its transit sign is only valid for that moment. Houses
    are whole-sign counts from the NATAL Moon (classical gochara) and the NATAL
    lagna. ``_placements`` is deliberately NOT reused: its ``house`` is relative to
    the transit chart's own lagna (the ascendant at the reference moment over the
    birth place), which is meaningless for gochara — the transit 'L' row is dropped.
    """
    from jhora.horoscope.chart import charts

    chart = charts.divisional_chart(ref_jd, place, divisional_chart_factor=1)
    planets: dict[str, dict] = {}
    for body, pos in chart:
        if body == "L":
            continue  # transit-chart lagna: meaningless for gochara, dropped
        sign = int(pos[0])
        planets[names.planet_name(int(body))] = {
            "sign_index": sign,
            "sign": names.sign_name(sign),
            "degrees": _round_deg(pos[1]),
            # Whole-sign house counted from the natal reference: 1 = same sign.
            "house_from_moon": ((sign - natal_moon_sign) % 12) + 1,
            "house_from_lagna": ((sign - natal_lagna_sign) % 12) + 1,
        }
    return {
        # Offset-aware so the instant is unambiguous; citable as transits.anchor.
        "anchor": "%04d-%02d-%02dT12:00:00%+03d:%02d"
        % (*reference_date, int(timezone), round(abs(timezone) % 1 * 60)),
        "natal_moon_sign": names.sign_name(natal_moon_sign),
        "planets": planets,
    }


def _varshaphal(jd, place, ref_jd, natal_lagna_sign: int,
                birth_date: DateTuple, reference_date: DateTuple) -> dict:
    """Tajaka varshaphal: the Vedic ANNUAL (solar-return) chart active at the
    reference date. This is the classical varshaphal — NOT Western progressions.

    Year selection brackets the reference against actual pravesh (solar-return)
    moments: the emitted ``age_year`` N satisfies ``pravesh_jd(N) <= ref_jd <
    pravesh_jd(N+1)``, where ``tajaka.annual_chart(..., years=N)`` is the (N-1)th
    solar return (``years=1`` is the birth moment itself). Calendar arithmetic
    alone (ref.year - birth.year + 1) is wrong for every reference date that falls
    before that calendar year's return — the ACTIVE annual chart is then still the
    previous year's — so the candidate year is corrected against real pravesh JDs.

    Munthi provenance: sign = (natal lagna sign + completed years) % 12, with
    completed years = age_year - 1. This is the classical rule (munthi in the
    lagna at birth, advancing one sign per year) and is computed via the engine's
    own ``tajaka.muntha_house`` lambda — the same formula. NOTE the engine's
    internal lord-of-year path feeds that lambda the ANNUAL ascendant and an
    uncorrected year count; the classical natal-lagna form is emitted here.

    Year lord (varsheshvara) is deliberately NOT emitted (documented deviation):
    the engine's ``tajaka.lord_of_the_year`` locates the year via the MEAN
    sidereal year (``jd + years*year_value``) — off by one year relative to
    ``annual_chart``'s true-solar-return moment — and its panchavargeeya-bala
    tie-break returns a candidate-list position instead of a planet index, so its
    verdict cannot be verified against the pravesh chart emitted here. The
    five-candidates rule is also school-dependent. Munthi only.

    Must run under ENGINE_LOCK (reads global ayanamsa state).
    """
    from jhora import utils
    from jhora.horoscope.transit import tajaka
    from jhora.panchanga import drik

    # Date-level guard: ref_jd is anchored at local NOON, so comparing raw JDs
    # would reject reference_date == birth date for afternoon births (noon < 12:30).
    # The birth DATE itself is always a valid reference; clamp the bracketing input
    # to the birth moment so pravesh(1) (= the birth jd) still satisfies the
    # half-open [pravesh(n), pravesh(n+1)) invariant.
    if tuple(reference_date) < tuple(birth_date):
        raise ConfigError(
            "reference_date is before birth; varshaphal (the annual solar-return "
            "chart) is undefined before birth. Use a reference_date on or after "
            "the birth date."
        )
    ref_jd = max(ref_jd, jd)

    def pravesh_jd(n: int) -> float:
        # The engine works in local-frame JDs throughout (julian_day_number takes
        # local civil time), so this compares directly against ref_jd.
        return drik.next_solar_date(jd, place, years=n)

    # Calendar candidate, then correct against actual pravesh JDs. Each step is one
    # cheap engine call; the loops move at most one step in practice (they exist for
    # returns that drift across the calendar-year boundary).
    n = max(reference_date[0] - birth_date[0] + 1, 1)
    while n > 1 and ref_jd < pravesh_jd(n):
        n -= 1
    while ref_jd >= pravesh_jd(n + 1):
        n += 1

    p_jd = pravesh_jd(n)
    chart, ((p_y, p_m, p_d), _hms) = tajaka.annual_chart(jd, place, years=n)
    # annual_chart derives its moment from the same next_solar_date call; a date
    # disagreement means the engine changed underneath us.
    y, m, d, hour_float = utils.jd_to_gregorian(p_jd)
    if (int(p_y), int(p_m), int(p_d)) != (int(y), int(m), int(d)):
        raise EngineOutputError(
            f"annual_chart pravesh date ({p_y},{p_m},{p_d}) != next_solar_date "
            f"date ({y},{m},{d}) for years={n}"
        )

    planets: dict[str, dict] = {}
    for body, pos in chart:
        if body == "L":
            continue
        sign = int(pos[0])
        planets[names.planet_name(int(body))] = {
            "sign_index": sign,
            "sign": names.sign_name(sign),
            "degrees": _round_deg(pos[1]),
        }
    munthi_sign = int(tajaka.muntha_house(natal_lagna_sign, n - 1))
    return {
        # ISO local datetime of the solar return via _fmt_dt (rollover-safe),
        # not the engine's to_dms string.
        "pravesh": _fmt_dt((y, m, d, hour_float)),
        # The years= value used; year N of life, valid pravesh(N)..pravesh(N+1).
        # Context for the agent, deliberately not a citation atom.
        "age_year": n,
        "lagna": _ascendant(chart),
        "planets": planets,
        "munthi": {"sign_index": munthi_sign, "sign": names.sign_name(munthi_sign)},
    }


def _houses(chart) -> list[dict]:
    """Whole-sign bhava table for a chart: 12 houses from the lagna with sign + lord."""
    lagna_sign = _lagna_sign(chart)
    table: list[dict] = []
    for house in range(1, 13):
        sign = (lagna_sign + house - 1) % 12
        lord = names.sign_lord_index(sign)
        table.append(
            {
                "house": house,
                "sign_index": sign,
                "sign": names.sign_name(sign),
                "lord_index": lord,
                "lord": names.planet_name(lord) if lord is not None else None,
            }
        )
    return table


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


def _run_engine_session(
    profile: BirthProfile,
    reference_date: DateTuple,
    config: CalculationConfig | None = None,
    domain_callback: Callable[[_EngineSnapshot], _DomainT] | None = None,
) -> _EngineSessionResult[_DomainT]:
    """Own one apply+compute lock and expose only immutable domain primitives.

    The callback runs while the same lock and applied PyJHora configuration are
    active. It receives copied D1/D9 positions, never mutable engine charts. The
    Raw engine structures remain local to this function. Engine reads and the
    callback run under the lock; pure natal normalization/assembly runs afterward.
    """
    config = config or CalculationConfig()
    # Pure config validation happens BEFORE acquiring the lock: an invalid request
    # must not contend on (or burn time inside) the engine critical section.
    resolved = config.resolved_charts()  # {name: factor}, always includes D1
    modules = config.resolved_modules()

    if getattr(_ENGINE_SESSION_LOCAL, "active", False):
        raise _EngineSessionReentryError("engine session re-entry is not allowed")

    _ENGINE_SESSION_LOCAL.active = True
    try:
        with ENGINE_LOCK:
            from jhora import utils
            from jhora.horoscope.chart import charts
            from jhora.panchanga import drik

            applied = apply_config(config)
            place = drik.Place(
                profile.name, profile.latitude, profile.longitude, profile.timezone
            )
            jd = utils.julian_day_number(profile.date, profile.time)
            # Anchor the reference at local noon to avoid date-boundary ambiguity.
            ref_jd = utils.julian_day_number(reference_date, (12, 0, 0))

            # D1/D9 are the shared domain primitives even when a natal caller elects
            # not to publish D9. Additional requested charts retain their resolved
            # order in the natal response below.
            kernel_charts = dict(resolved)
            kernel_charts.setdefault("D9", 9)
            raw_charts = {
                name: charts.divisional_chart(
                    jd, place, divisional_chart_factor=factor
                )
                for name, factor in kernel_charts.items()
            }
            # Jaimini special-lagna primitive, captured under the same configured
            # engine lock as D1/D9.  For a pre-sunrise birth the frozen profile's
            # "minutes since sunrise" anchor is not satisfied; surface unavailable
            # rather than silently switching to the previous civil date.
            try:
                (
                    sun_longitude_at_sunrise,
                    minutes_since_sunrise,
                ) = _special_lagna_primitive(drik, jd, place, profile)
            except Exception:
                # Optional domain primitive: the Jaimini facade converts absence
                # into a typed privacy-safe incomplete result.
                sun_longitude_at_sunrise = None
                minutes_since_sunrise = None
            panchanga = _panchanga(jd, place)
            vimshottari = _vimshottari_current(ref_jd, jd, place)
            module_facts: dict[str, dict] = {}
            if "shadbala" in modules:
                module_facts["shadbala"] = _shadbala(jd, place)
            if "ashtakavarga" in modules:
                module_facts["ashtakavarga"] = _ashtakavarga(raw_charts["D1"])
            if "transits" in modules:
                module_facts["transits"] = _transits(
                    ref_jd,
                    place,
                    natal_moon_sign=_planet_sign(raw_charts["D1"], 1),  # Moon = index 1
                    natal_lagna_sign=_lagna_sign(raw_charts["D1"]),
                    reference_date=reference_date,
                    timezone=profile.timezone,
                )
            if "varshaphal" in modules:
                module_facts["varshaphal"] = _varshaphal(
                    jd,
                    place,
                    ref_jd,
                    natal_lagna_sign=_lagna_sign(raw_charts["D1"]),
                    birth_date=profile.date,
                    reference_date=reference_date,
                )
            if "yogas_engine" in modules:
                # The ONLY module allowed to degrade instead of failing the compute: it
                # dispatches ~284 unaudited engine functions, any of which may raise
                # under a particular ephemeris/date; the rest of the chart must survive.
                try:
                    module_facts["yogas_engine"] = _yogas_engine(jd, place, resolved)
                except ConfigError:
                    raise  # a config defect is a caller error, never "engine unavailable"
                except Exception:
                    module_facts["yogas_engine"] = dict(_YOGAS_ENGINE_UNAVAILABLE)

            snapshot = _EngineSnapshot(
                config=_EngineConfigSnapshot(
                    ayanamsa=applied.ayanamsa,
                    rahu_ketu=applied.rahu_ketu,
                    node_aspects=applied.node_aspects,
                    charts=tuple(resolved),
                    modules=tuple(sorted(modules)),
                ),
                d1=_immutable_positions(raw_charts["D1"]),
                d9=_immutable_positions(raw_charts["D9"]),
                sun_longitude_at_sunrise=sun_longitude_at_sunrise,
                minutes_since_sunrise=minutes_since_sunrise,
                ephemeris_mode=ephemeris_mode(),
            )
            # Last action under the lock: no callback-side config mutation can alter
            # engine-dependent values already captured for the natal response.
            domain_result = (
                domain_callback(snapshot) if domain_callback is not None else None
            )
    finally:
        _ENGINE_SESSION_LOCAL.active = False

    # Cross-module joins and all natal normalization are pure over captured values.
    if "transits" in module_facts and "ashtakavarga" in module_facts:
        sav = module_facts["ashtakavarga"]["sav"]
        for planet in module_facts["transits"]["planets"].values():
            planet["sav_points"] = sav[planet["sign"]]

    divisional_facts = {
        name.lower(): _placements(raw_charts[name]) for name in resolved
    }
    ascendant = _ascendant(raw_charts["D1"])
    yogas = detect_yogas(divisional_facts["d1"])
    if "yogas_engine" in module_facts:
        module_facts["yogas_engine"]["mismatches"] = _yoga_tier_mismatches(
            yogas, module_facts["yogas_engine"]
        )
    houses = _houses(raw_charts["D1"])
    lagnas = {name.lower(): _ascendant(raw_charts[name]) for name in resolved}
    bhava = {name.lower(): _houses(raw_charts[name]) for name in resolved}
    aspects = _aspects(raw_charts["D1"], applied.node_aspects)

    natal = {
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
            "node_aspects": applied.node_aspects,
            "charts": list(resolved),
            "modules": sorted(modules),
            "reference_date": list(reference_date),
        },
        "facts": {
            "ascendant": ascendant,
            "houses": houses,
            "lagnas": lagnas,
            "bhava": bhava,
            "aspects": aspects,
            "yogas": yogas,
            **divisional_facts,
            **module_facts,
            "panchanga": panchanga,
            "vimshottari": vimshottari,
        },
        "provenance": {
            "engine": "PyJHora",
            "engine_version": ENGINE_VERSION,
            "ephemeris_mode": ephemeris_mode(),
        },
    }

    return _EngineSessionResult(natal=natal, snapshot=snapshot, domain=domain_result)


def compute_chart(
    profile: BirthProfile,
    reference_date: DateTuple,
    config: CalculationConfig | None = None,
) -> dict:
    """Compute the deterministic natal fact set through the locked engine session."""
    return _run_engine_session(profile, reference_date, config).natal
