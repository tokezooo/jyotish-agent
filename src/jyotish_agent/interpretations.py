"""Fact-citation contract + safety screening — the enforceable trust boundary.

The product's promise: an interpretive answer may synthesize and prioritize, but it
must cite only facts the calculation tools actually returned. This module turns a
chart's ``facts`` block into a flat set of citable atoms and checks an answer's
``facts_used`` against them. A citation of a placement/dasha/panchanga value that
isn't in the computed facts is a violation — that is how "never invent placements"
becomes a test, not a hope.

It also screens questions for domains the agent must refuse or redirect (medical,
legal, financial, self-harm, deterministic death/harm claims).
"""

from __future__ import annotations

import math
import re
from enum import Enum

from .names import PLANETS, SIGNS
from .rule_profiles import jaimini_source_admission_evidence
from .signing import get_cached_domain_artifact, verify_domain_artifact

_DIVISIONAL_KEY = re.compile(r"^d\d+$")

# Matches "<Planet> [is|sits|placed] in <Sign>" claims in answer prose, so a stated
# placement can be checked against the computed charts even if the author forgot to
# add it to facts_used. Best-effort English-phrasing detector, not a parser.
_PLACEMENT_CLAIM = re.compile(
    r"\b(" + "|".join(PLANETS) + r")\b"
    r"(?:\s+is|\s+sits|\s+is\s+placed|\s+placed)?\s+in\s+"
    r"\b(" + "|".join(SIGNS) + r")\b",
    re.IGNORECASE,
)


def iter_fact_atoms(facts: dict) -> dict[str, str]:
    """Flatten a chart ``facts`` block into ``{citable_path: canonical_value}``.

    Paths are stable, dotted, and self-describing, e.g.::

        ascendant.sign            -> "Pisces"
        d1.Sun.sign               -> "Sagittarius"
        d1.Sun.degrees            -> "16.886946"
        d1.Sun.house              -> "10"
        houses.10.lord            -> "Jupiter"
        bhava.d9.10.lord          -> "..."   (per-varga bhava table)
        lagnas.d9.sign            -> "..."   (per-varga lagna)
        aspects.Saturn.Moon       -> "true"
        panchanga.nakshatra       -> "Shatabhisha"
        panchanga.nakshatra.pada  -> "1"
        vimshottari.mahadasha.lord-> "Saturn"

    Only meaningful, citable leaves are included (names, signs, degrees, lords,
    period bounds) — raw integer indices are intentionally omitted as citation
    targets to keep the contract about the human-meaningful facts.
    """
    atoms: dict[str, str] = {}

    asc = facts.get("ascendant") or {}
    if asc.get("sign") is not None:
        atoms["ascendant.sign"] = str(asc["sign"])
    if asc.get("degrees") is not None:
        atoms["ascendant.degrees"] = str(asc["degrees"])

    # Any divisional chart key (d1, d9, d10, ...) present in the facts is citable.
    for chart_key, value in facts.items():
        if not _DIVISIONAL_KEY.match(chart_key) or not isinstance(value, list):
            continue
        for placement in value:
            planet = placement.get("planet")
            if not planet:
                continue
            if placement.get("sign") is not None:
                atoms[f"{chart_key}.{planet}.sign"] = str(placement["sign"])
            if placement.get("degrees") is not None:
                atoms[f"{chart_key}.{planet}.degrees"] = str(placement["degrees"])
            if placement.get("house") is not None:
                atoms[f"{chart_key}.{planet}.house"] = str(placement["house"])

    def _emit_house_table(prefix: str, table) -> None:
        for house in table or []:
            n = house.get("house")
            if n is None:
                continue
            if house.get("sign") is not None:
                atoms[f"{prefix}.{n}.sign"] = str(house["sign"])
            if house.get("lord") is not None:
                atoms[f"{prefix}.{n}.lord"] = str(house["lord"])

    _emit_house_table("houses", facts.get("houses"))  # D1 alias

    # Per-varga bhava tables: bhava.<Chart>.<N>.sign / .lord
    bhava = facts.get("bhava")
    if isinstance(bhava, dict):
        for chart_name, table in bhava.items():
            _emit_house_table(f"bhava.{chart_name}", table)

    # Varga lagnas: lagnas.<Chart>.sign
    lagnas = facts.get("lagnas")
    if isinstance(lagnas, dict):
        for chart_name, lag in lagnas.items():
            if isinstance(lag, dict) and lag.get("sign") is not None:
                atoms[f"lagnas.{chart_name}.sign"] = str(lag["sign"])

    # Planet-to-planet aspects: aspects.<From>.<To> = "true" if From aspects To.
    aspects = facts.get("aspects")
    if isinstance(aspects, dict):
        for from_planet, info in aspects.items():
            if not isinstance(info, dict):
                continue
            for to_planet in info.get("aspects_planets") or []:
                atoms[f"aspects.{from_planet}.{to_planet}"] = "true"

    # Shadbala (module): shadbala.<Planet>.rupas / .strength_ratio / .components.<name>
    shadbala = facts.get("shadbala")
    if isinstance(shadbala, dict):
        for planet, info in shadbala.items():
            if not isinstance(info, dict):
                continue
            if info.get("rupas") is not None:
                atoms[f"shadbala.{planet}.rupas"] = str(info["rupas"])
            if info.get("strength_ratio") is not None:
                atoms[f"shadbala.{planet}.strength_ratio"] = str(info["strength_ratio"])
            for comp, val in (info.get("components") or {}).items():
                atoms[f"shadbala.{planet}.components.{comp}"] = str(val)

    # Ashtakavarga (module): ashtakavarga.sav.<Sign>, ashtakavarga.bav.<Planet|Lagna>.<Sign>
    ashtakavarga = facts.get("ashtakavarga")
    if isinstance(ashtakavarga, dict):
        for sign, points in (ashtakavarga.get("sav") or {}).items():
            atoms[f"ashtakavarga.sav.{sign}"] = str(points)
        for row, cells in (ashtakavarga.get("bav") or {}).items():
            if not isinstance(cells, dict):
                continue
            for sign, points in cells.items():
                atoms[f"ashtakavarga.bav.{row}.{sign}"] = str(points)

    # Transits (module): transits.<Planet>.sign / .house_from_moon / .house_from_lagna
    # (+ .sav_points when the ashtakavarga module is also on) and
    # transits.natal_moon_sign and transits.anchor (offset-aware snapshot moment),
    # not a citable claim — deliberately no atom.
    transits = facts.get("transits")
    if isinstance(transits, dict):
        if transits.get("natal_moon_sign") is not None:
            atoms["transits.natal_moon_sign"] = str(transits["natal_moon_sign"])
        if transits.get("anchor") is not None:
            atoms["transits.anchor"] = str(transits["anchor"])
        for planet, info in (transits.get("planets") or {}).items():
            if not isinstance(info, dict):
                continue
            for field in ("sign", "degrees", "house_from_moon", "house_from_lagna", "sav_points"):
                if info.get(field) is not None:
                    atoms[f"transits.{planet}.{field}"] = str(info[field])

    # Varshaphal (module): varshaphal.pravesh (ISO local solar-return moment),
    # varshaphal.lagna.sign, varshaphal.<Planet>.sign, varshaphal.munthi.sign.
    # age_year is context for year bracketing, deliberately NOT an atom.
    varshaphal = facts.get("varshaphal")
    if isinstance(varshaphal, dict):
        if varshaphal.get("pravesh") is not None:
            atoms["varshaphal.pravesh"] = str(varshaphal["pravesh"])
        lagna = varshaphal.get("lagna")
        if isinstance(lagna, dict):
            if lagna.get("sign") is not None:
                atoms["varshaphal.lagna.sign"] = str(lagna["sign"])
            if lagna.get("degrees") is not None:
                atoms["varshaphal.lagna.degrees"] = str(lagna["degrees"])
        munthi = varshaphal.get("munthi")
        if isinstance(munthi, dict) and munthi.get("sign") is not None:
            atoms["varshaphal.munthi.sign"] = str(munthi["sign"])
        for planet, info in (varshaphal.get("planets") or {}).items():
            if not isinstance(info, dict):
                continue
            if info.get("sign") is not None:
                atoms[f"varshaphal.{planet}.sign"] = str(info["sign"])
            # degrees citable, matching the project-wide convention (ascendant,
            # d<N> placements, transits all atomize degrees).
            if info.get("degrees") is not None:
                atoms[f"varshaphal.{planet}.degrees"] = str(info["degrees"])

    # Yogas: yogas.<Name>.present = "true"/"false"
    yogas = facts.get("yogas")
    if isinstance(yogas, dict):
        for name, info in yogas.items():
            if isinstance(info, dict) and "present" in info:
                atoms[f"yogas.{name}.present"] = "true" if info["present"] else "false"

    # Engine yogas (module): yogas_engine.<chart>.<key>.present = "true" — detected
    # only, an absence is NOT a citable fact — plus yogas_engine.status. The
    # engine_errors count and mismatches strings are context for the agent,
    # deliberately NOT atoms (they are about the scan, not the chart).
    engine_yogas = facts.get("yogas_engine")
    if isinstance(engine_yogas, dict):
        if engine_yogas.get("status") is not None:
            atoms["yogas_engine.status"] = str(engine_yogas["status"])
        charts_map = engine_yogas.get("charts")
        if isinstance(charts_map, dict):
            for chart_key, entries in charts_map.items():
                for entry in entries or []:
                    if isinstance(entry, dict) and entry.get("key"):
                        atoms[f"yogas_engine.{chart_key}.{entry['key']}.present"] = "true"

    panchanga = facts.get("panchanga") or {}
    for key, entry in panchanga.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("name") is not None:
            atoms[f"panchanga.{key}"] = str(entry["name"])
        if entry.get("pada") is not None:
            atoms[f"panchanga.{key}.pada"] = str(entry["pada"])

    vim = facts.get("vimshottari") or {}
    for level in ("mahadasha", "bhukti", "antara"):
        period = vim.get(level)
        if not isinstance(period, dict):
            continue
        for field in ("lord", "start", "end"):
            if period.get(field) is not None:
                atoms[f"vimshottari.{level}.{field}"] = str(period[field])

    return atoms


def iter_jaimini_fact_atoms(facts: list[dict]) -> dict[str, str]:
    """Project a bounded Jaimini artifact fact list into citable atoms."""
    atoms: dict[str, str] = {}
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        path = fact.get("fact_id")
        value = fact.get("value")
        if (
            isinstance(path, str)
            and path.startswith("jaimini.")
            and isinstance(value, (str, int, float, bool))
        ):
            if path in atoms:
                raise ValueError(f"DUPLICATE_JAIMINI_FACT_ID:{path}")
            atoms[path] = "true" if value is True else "false" if value is False else str(value)
    return atoms


def validate_jaimini_answer(
    facts_used: list[dict],
    artifact_token: str,
    *,
    interpretation_requested: bool = False,
    summary: str | None = None,
) -> list[str]:
    """Check citations against a server-held artifact and enforce its source gate."""
    artifact = get_cached_domain_artifact(artifact_token)
    if artifact is None:
        return ["ARTIFACT_NOT_FOUND"]
    if not verify_domain_artifact(artifact):
        return ["ARTIFACT_INVALID"]
    if interpretation_requested or summary is not None:
        admission = jaimini_source_admission_evidence()
        if not admission["verified"]:
            return ["INTERPRETATION_SOURCE_UNAVAILABLE"]
        if artifact.get("source_admission_sha256") != admission["sha256"]:
            return ["SOURCE_ADMISSION_MISMATCH"]
        # No governed analysis graph / canonical renderer is admitted yet.  Even a
        # fully verified future source pack cannot turn caller-authored prose into
        # validated interpretation merely by citing computed facts.
        return ["INTERPRETATION_RENDERER_UNAVAILABLE"]
    atoms = iter_jaimini_fact_atoms(artifact.get("facts", []))
    violations: list[str] = []
    for ref in facts_used:
        path = str(ref.get("path", "")).strip()
        value = str(ref.get("value", "")).strip()
        if path not in atoms:
            violations.append(f"FACT_NOT_IN_ARTIFACT:{path}")
        elif not _values_match(value, atoms[path]):
            violations.append(f"FACT_VALUE_MISMATCH:{path}")
    return violations


def _values_match(cited: str, computed: str) -> bool:
    """Match a cited value to a computed one.

    Float comparison uses a tolerance so a citation copied (or rounded by one place)
    from the JSON doesn't false-positive. Non-finite values (nan/inf) never match,
    even via raw string equality, so a forged 'nan'/'inf' can't sneak through."""
    c, k = cited.strip(), computed.strip()
    try:
        cf, kf = float(c), float(k)
        if not (math.isfinite(cf) and math.isfinite(kf)):
            return False
        return abs(cf - kf) < 1e-4
    except ValueError:
        return c == k


def _planet_signs(facts: dict) -> dict[str, set[str]]:
    """Map planet name -> set of signs it occupies across all computed charts."""
    out: dict[str, set[str]] = {}
    for key, value in facts.items():
        if not _DIVISIONAL_KEY.match(key) or not isinstance(value, list):
            continue
        for placement in value:
            planet, sign = placement.get("planet"), placement.get("sign")
            if planet and sign:
                out.setdefault(planet, set()).add(sign)
    return out


_NEGATION = re.compile(r"\b(not|never|no|isn't|aren't|unlike|n't|без|не)\b", re.IGNORECASE)


def find_prose_contradictions(summary: str, facts: dict) -> list[str]:
    """Detect '<Planet> in <Sign>' claims in the prose that CONTRADICT the computed
    charts. Catches the MOST COMMON LITERAL English phrasing only — it is a
    floor-raiser for accidental contradictions, NOT a security control. It is trivially
    bypassed by paraphrase ("occupies", "exalted in", a comma), reversed word order, or
    another language, so the model's own discipline (cite everything) remains primary.

    Limitations (deliberate, documented):
    - Negated/counterfactual mentions ("unlike a Sun in Leo native") are skipped to
      avoid flagging correct answers.
    - A placement is considered true if it holds in ANY computed chart (planet-level
      union), so a claim about a specific varga that is only true in another varga is
      NOT flagged. Per-chart prose validation is out of scope.
    """
    signs_by_planet = _planet_signs(facts)
    canon_planet = {p.lower(): p for p in PLANETS}
    canon_sign = {s.lower(): s for s in SIGNS}
    violations: list[str] = []
    seen: set[tuple[str, str]] = set()
    for m in _PLACEMENT_CLAIM.finditer(summary or ""):
        # Skip negated/counterfactual phrasings: a negation in the ~30 chars before the
        # claim means the answer is contrasting, not asserting, the placement.
        if _NEGATION.search(summary[max(0, m.start() - 30) : m.start()]):
            continue
        planet = canon_planet[m.group(1).lower()]
        sign = canon_sign[m.group(2).lower()]
        if (planet, sign) in seen:
            continue
        seen.add((planet, sign))
        actual = signs_by_planet.get(planet, set())
        if actual and sign not in actual:
            violations.append(
                f"summary claims '{planet} in {sign}' but the computed charts place "
                f"{planet} in {sorted(actual)}"
            )
    return violations


def validate_answer(
    facts_used: list[dict], facts: dict, summary: str | None = None
) -> list[str]:
    """Return a list of citation violations (empty == the answer is fact-grounded).

    Each ``facts_used`` item is ``{"path": str, "value": str|number}``. A violation is
    raised when the path is not a computed fact, or its value disagrees with the
    computed value. If ``summary`` is given, prose placement claims that contradict the
    computed charts are also flagged (see find_prose_contradictions)."""
    atoms = iter_fact_atoms(facts)
    violations: list[str] = []
    for ref in facts_used:
        path = str(ref.get("path", "")).strip()
        value = str(ref.get("value", "")).strip()
        if path not in atoms:
            violations.append(
                f"cited fact '{path}' is not in the computed facts (invented or mistyped path)"
            )
        elif not _values_match(value, atoms[path]):
            violations.append(
                f"fact '{path}' cited as '{value}' but the computed value is '{atoms[path]}'"
            )
    if summary:
        violations.extend(find_prose_contradictions(summary, facts))
    return violations


class SafetyCategory(str, Enum):
    medical = "medical"
    legal = "legal"
    financial = "financial"
    self_harm = "self_harm"
    deterministic_harm = "deterministic_harm"


# Keyword screens. BEST-EFFORT, substring-based: a coarse pre-filter, NOT a sufficient
# safety control. English + Russian (the studio is Russian-primary) for the highest-risk
# categories; intentionally broad (false positives just add a caveat, the safe
# direction). It will still miss paraphrases and other languages — the model's own
# judgement via the skill remains the primary safeguard.
_SCREENS: dict[SafetyCategory, tuple[str, ...]] = {
    # Russian terms are chosen to avoid substring collisions with common astrology
    # vocabulary (судьба=fate, характер=character, увлечение=hobby, реакция=reaction),
    # so they are unambiguous phrases rather than short stems.
    SafetyCategory.self_harm: (
        # English
        "suicide", "kill myself", "end my life", "end it all", "self harm", "self-harm",
        "self injury", "self-injury", "harm myself", "hurt myself", "want to die",
        "don't want to be here", "overdose",
        # Russian
        "суицид", "убить себя", "покончить с собой", "не хочу жить",
        "причинить себе вред", "наложить на себя руки", "свести счёты с жизнью",
    ),
    SafetyCategory.medical: (
        # English. "cancer" is NOT a bare term here: it collides with the zodiac sign
        # Cancer (Moon in Cancer). The cancer-as-disease sense is matched contextually
        # in _REGEX_SCREENS instead.
        "diagnos", "disease", "tumor", "tumour", "terminal", "fatal",
        "medication", "medicine", "treatment", "cure", "symptom", "pregnan", "mental illness",
        "depression",
        # Russian (рак=cancer is likewise contextual in _REGEX_SCREENS; bare рак
        # collides with Раке=the sign Cancer).
        "диагноз", "болезн", "онколог", "опухол", "симптом", "беремен", "депресси",
        "вылечить", "лекарств", "заболевани",
    ),
    SafetyCategory.legal: (
        "lawsuit", "legal advice", "sue ", "court case", "custody",
        "судебн", "подать иск", "юридическ", "адвокат",
    ),
    SafetyCategory.financial: (
        # "stock" is contextual in _REGEX_SCREENS (collides with stockpile, etc.).
        "should i invest", "buy bitcoin", "guaranteed return", "investment return", "financial advice",
        "put money into",
        "инвестир", "купить биткоин", "вложить деньги", "купить акци", "фондовый рынок",
    ),
    SafetyCategory.deterministic_harm: (
        "when will i die", "when do i die", "when's my death", "date of death",
        "how will i die", "will i die", "predict my death", "day i die",
        "exact day i will be fired", "exact day i'll be fired",
        "когда я умру", "когда умру", "дата смерти", "как я умру", "как умру",
    ),
}

_REDIRECTS: dict[SafetyCategory, str] = {
    SafetyCategory.self_harm: (
        "I can't help with this. If you're thinking about harming yourself, please "
        "reach out to a crisis line or emergency services now. Jyotish is not a "
        "substitute for immediate human support."
    ),
    SafetyCategory.medical: (
        "I can't give medical guidance. Please consult a qualified medical "
        "professional. I can discuss chart symbolism only in general, reflective terms."
    ),
    SafetyCategory.legal: (
        "I can't give legal advice. Please consult a qualified lawyer. I can speak to "
        "chart symbolism only in general, reflective terms."
    ),
    SafetyCategory.financial: (
        "I can't give financial advice or predict markets. Please consult a licensed "
        "financial advisor. I can discuss chart symbolism only in general terms."
    ),
    SafetyCategory.deterministic_harm: (
        "I won't make deterministic claims about death, illness, or harm. Jyotish here "
        "is reflective and symbolic, not predictive of such outcomes."
    ),
}


# Context-required regexes for terms whose bare substring collides with common
# (often astrology) vocabulary: "cancer"/"рак" the disease vs Cancer/Раке the sign,
# "stock" vs stockpile. These require a disease/finance context to fire, so legitimate
# zodiac-Cancer and "stockpile" questions are not screened.
_REGEX_SCREENS: dict[SafetyCategory, tuple[re.Pattern[str], ...]] = {
    SafetyCategory.medical: (
        re.compile(r"\b(have|has|had|get|getting|got|risk of|diagnosed with)\s+cancer\b", re.I),
        re.compile(r"\bcancer\s+(treatment|diagnos\w*|patient|screening|risk)\b", re.I),
        re.compile(r"рак груди|больн\w*\s+раком|диагноз[:\s]+рак|рак\s+(желудка|лёгких|легких|кожи|крови)", re.I),
    ),
    SafetyCategory.financial: (re.compile(r"\bstocks?\b", re.I),),
}


def screen_question(text: str) -> SafetyCategory | None:
    """Return the first matched unsafe category, or None. Self-harm takes priority.
    Best-effort keyword filter only — see the note on ``_SCREENS``."""
    lowered = str(text).lower()
    for category in (
        SafetyCategory.self_harm,
        SafetyCategory.deterministic_harm,
        SafetyCategory.medical,
        SafetyCategory.legal,
        SafetyCategory.financial,
    ):
        if any(kw in lowered for kw in _SCREENS[category]):
            return category
        if any(rx.search(lowered) for rx in _REGEX_SCREENS.get(category, ())):
            return category
    return None


def redirect_message(category: SafetyCategory) -> str:
    """Suggested refusal/redirect text for a screened category."""
    return _REDIRECTS[category]
