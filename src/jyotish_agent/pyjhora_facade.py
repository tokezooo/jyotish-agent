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
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import ENGINE_VERSION, names
from .config import ENGINE_LOCK, CalculationConfig, apply_config, ephemeris_mode
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


def _round_deg(value: float) -> float:
    return round(float(value), _DEG_PRECISION)


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

    from jhora.horoscope.chart import yoga as engine_yoga

    engine_errors = 0
    charts_out: dict[str, list[dict]] = {}
    for name, factor in resolved.items():
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            # Returns (detected: {fn_key: [chart_id, name, description, benefits]},
            # found_count, total_count); counts are redundant with len(detected).
            detected, _found, _total = engine_yoga.get_yoga_details(
                jd, place, divisional_chart_factor=factor, language="en"
            )
        engine_errors += sum(
            1 for line in buf.getvalue().splitlines() if _YOGA_ENGINE_ERROR_MARKER in line
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
    uncertainty — never as a changed verdict. Engine matching is by 'gajakesari'
    substring on the underscore-stripped D1 keys (the engine names it
    'gaja_kesari_yoga'). Skipped when the engine tier is unavailable (no detection
    happened, so absence means nothing)."""
    ours = our_yogas.get("Gajakesari")
    if ours is None or engine_yogas.get("status") == "unavailable":
        return []
    d1_entries = (engine_yogas.get("charts") or {}).get("d1") or []
    engine_present = any(
        "gajakesari" in str(e.get("key", "")).replace("_", "") for e in d1_entries
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
    # Pure config validation happens BEFORE acquiring the lock: an invalid request
    # must not contend on (or burn time inside) the engine critical section.
    resolved = config.resolved_charts()  # {name: factor}, always includes D1
    modules = config.resolved_modules()

    with ENGINE_LOCK:
        from jhora import utils
        from jhora.horoscope.chart import charts
        from jhora.panchanga import drik

        applied = apply_config(config)
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
        if "yogas_engine" in modules:
            # The ONLY module allowed to degrade instead of failing the compute: it
            # dispatches ~284 unaudited engine functions, any of which may raise
            # under a particular ephemeris/date; the rest of the chart must survive.
            try:
                module_facts["yogas_engine"] = _yogas_engine(jd, place, resolved)
            except Exception:
                module_facts["yogas_engine"] = dict(_YOGAS_ENGINE_UNAVAILABLE)

        # Cross-module joins run AFTER all modules are computed so they never depend
        # on module execution order. Gochara×SAV: each transit planet gets the SAV
        # bindus of its transited sign (classical transit strength).
        if "transits" in module_facts and "ashtakavarga" in module_facts:
            sav = module_facts["ashtakavarga"]["sav"]
            for planet in module_facts["transits"]["planets"].values():
                planet["sav_points"] = sav[planet["sign"]]

    # Each divisional chart becomes a lowercase fact key (d1, d9, d10, ...). The
    # ascendant is taken from D1, which resolved_charts guarantees is present.
    divisional_facts = {name.lower(): _placements(chart) for name, chart in raw_charts.items()}
    ascendant = _ascendant(raw_charts["D1"])
    yogas = detect_yogas(divisional_facts["d1"])  # narrow geometric set, D1 only
    if "yogas_engine" in module_facts:
        # Two-tier cross-check, run after BOTH tiers exist so it never depends on
        # module execution order. Always present (possibly empty) so the agent can
        # rely on the field; strings are context to surface, deliberately NOT atoms.
        module_facts["yogas_engine"]["mismatches"] = _yoga_tier_mismatches(
            yogas, module_facts["yogas_engine"]
        )
    # D1 ascendant/houses are retained as top-level aliases for back-compat; the
    # general per-chart forms are `lagnas` and `bhava` (which include D1). Keys are
    # lowercased (d1, d9, ...) to match the divisional placement key convention.
    houses = _houses(raw_charts["D1"])
    lagnas = {name.lower(): _ascendant(chart) for name, chart in raw_charts.items()}
    bhava = {name.lower(): _houses(chart) for name, chart in raw_charts.items()}
    aspects = _aspects(raw_charts["D1"], applied.node_aspects)

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
            "node_aspects": applied.node_aspects,
            "charts": list(resolved),
            "modules": sorted(modules),
            # reference_date drives the running Vimshottari period; surfaced here so a
            # quoted/cached result is fully reproducible from calculation_config alone.
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
