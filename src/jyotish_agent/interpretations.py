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

_DIVISIONAL_KEY = re.compile(r"^d\d+$")


def iter_fact_atoms(facts: dict) -> dict[str, str]:
    """Flatten a chart ``facts`` block into ``{citable_path: canonical_value}``.

    Paths are stable, dotted, and self-describing, e.g.::

        ascendant.sign            -> "Pisces"
        d1.Sun.sign               -> "Sagittarius"
        d1.Sun.degrees            -> "16.886946"
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

    for house in facts.get("houses") or []:
        n = house.get("house")
        if n is None:
            continue
        if house.get("sign") is not None:
            atoms[f"houses.{n}.sign"] = str(house["sign"])
        if house.get("lord") is not None:
            atoms[f"houses.{n}.lord"] = str(house["lord"])

    # Planet-to-planet aspects: aspects.<From>.<To> = "true" if From aspects To.
    aspects = facts.get("aspects")
    if isinstance(aspects, dict):
        for from_planet, info in aspects.items():
            if not isinstance(info, dict):
                continue
            for to_planet in info.get("aspects_planets") or []:
                atoms[f"aspects.{from_planet}.{to_planet}"] = "true"

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


def validate_answer(facts_used: list[dict], facts: dict) -> list[str]:
    """Return a list of citation violations (empty == the answer is fact-grounded).

    Each ``facts_used`` item is ``{"path": str, "value": str|number}``. A violation
    is raised when the path is not a computed fact, or its value disagrees with the
    computed value."""
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
    return violations


class SafetyCategory(str, Enum):
    medical = "medical"
    legal = "legal"
    financial = "financial"
    self_harm = "self_harm"
    deterministic_harm = "deterministic_harm"


# Keyword screens. BEST-EFFORT, English-only, substring-based: a coarse pre-filter,
# NOT a sufficient safety control. It is intentionally broad (false positives just add
# a caveat, the safe direction) and will miss paraphrases/other languages — the model's
# own judgement via the skill remains the primary safeguard.
_SCREENS: dict[SafetyCategory, tuple[str, ...]] = {
    SafetyCategory.self_harm: (
        "suicide", "kill myself", "end my life", "end it all", "self harm", "self-harm",
        "self injury", "self-injury", "harm myself", "hurt myself", "want to die",
        "don't want to be here", "overdose",
    ),
    SafetyCategory.medical: (
        "diagnos", "disease", "cancer", "tumor", "tumour", "terminal", "fatal",
        "medication", "treatment", "cure", "symptom", "pregnan", "mental illness",
        "depression",
    ),
    SafetyCategory.legal: ("lawsuit", "legal advice", "sue ", "court case", "custody"),
    SafetyCategory.financial: (
        "should i invest", "stock", "buy bitcoin", "guaranteed return", "financial advice",
        "put money into",
    ),
    SafetyCategory.deterministic_harm: (
        "when will i die", "when do i die", "when's my death", "date of death",
        "how will i die", "will i die", "predict my death", "day i die",
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


def screen_question(text: str) -> SafetyCategory | None:
    """Return the first matched unsafe category, or None. Self-harm takes priority.
    Best-effort keyword filter only — see the note on ``_SCREENS``."""
    lowered = text.lower()
    for category in (
        SafetyCategory.self_harm,
        SafetyCategory.deterministic_harm,
        SafetyCategory.medical,
        SafetyCategory.legal,
        SafetyCategory.financial,
    ):
        if any(kw in lowered for kw in _SCREENS[category]):
            return category
    return None


def redirect_message(category: SafetyCategory) -> str:
    """Suggested refusal/redirect text for a screened category."""
    return _REDIRECTS[category]
