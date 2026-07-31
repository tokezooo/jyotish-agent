"""Independent, hand-authored held-out checks for Jaimini Core geometry.

This evaluator is intentionally limited to deterministic scalar/sign geometry.
It neither admits doctrine sources nor replaces human-reviewed worked cases.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Callable, Mapping

from .jaimini import (
    ExactKarakaTieError,
    argala,
    arudha_pada,
    chara_dasha,
    chara_karakas,
    rasi_drishti,
    resolve_co_lord,
    special_lagnas,
)
from .rule_profiles import jaimini_rule_profile_sha256


class HeldOutCorpusError(ValueError):
    """The sealed geometry corpus is malformed, substituted, or unsafe."""


_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CORPUS = _ROOT / "eval" / "jaimini" / "geometry-held-out-v1.json"
_DEFAULT_MANIFEST = _ROOT / "eval" / "jaimini" / "geometry-held-out-v1-checksums.json"
_SCHOOL = "project-canonical-jaimini-v1"
_REQUIRED_FAMILIES = {
    "karakas",
    "rasi_drishti",
    "arudha",
    "co_lord",
    "argala",
    "special_lagnas",
    "chara_dasha",
}
_BODIES = {"Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"}


def _json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HeldOutCorpusError(f"invalid {label}") from exc
    if not isinstance(value, dict):
        raise HeldOutCorpusError(f"invalid {label}")
    return value


def _require_keys(value: Mapping[str, Any], keys: set[str], label: str) -> None:
    if set(value) != keys:
        raise HeldOutCorpusError(f"{label} has an invalid schema")


def _sign(value: Any, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 12:
        raise HeldOutCorpusError(f"{label} must be a zero-based sign")


def _number(value: Any, label: str, *, upper: float | None = None) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise HeldOutCorpusError(f"{label} must be a scalar number")
    if upper is not None and not 0 <= value < upper:
        raise HeldOutCorpusError(f"{label} is outside the synthetic geometry range")


def _assert_public_synthetic(value: Any) -> None:
    """Reject path-like/private payloads before an oracle can inspect them."""
    if isinstance(value, str):
        if any(token in value.lower() for token in ("private_sources", ".pdf", "file://")):
            raise HeldOutCorpusError("synthetic scalar/sign inputs cannot contain private payloads")
        return
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, list):
        for item in value:
            _assert_public_synthetic(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _assert_public_synthetic(key)
            _assert_public_synthetic(item)
        return
    raise HeldOutCorpusError("synthetic scalar/sign inputs must be JSON values")


def _validate_case(case: Any) -> None:
    if not isinstance(case, dict):
        raise HeldOutCorpusError("case must be an object")
    _require_keys(case, {"id", "rule_family", "input", "expected"}, "case")
    if not isinstance(case["id"], str) or not case["id"]:
        raise HeldOutCorpusError("case ID must be a non-empty string")
    family = case["rule_family"]
    if family not in _REQUIRED_FAMILIES:
        raise HeldOutCorpusError("case has an unknown rule family")
    scenario, expected = case["input"], case["expected"]
    if not isinstance(scenario, dict):
        raise HeldOutCorpusError("synthetic scalar/sign inputs must be objects")
    _assert_public_synthetic(scenario)
    _assert_public_synthetic(expected)

    if family == "karakas":
        if set(scenario) != {"scheme", "longitudes"}:
            raise HeldOutCorpusError("synthetic scalar/sign inputs must use only declared fields")
        scheme, longitudes = scenario["scheme"], scenario["longitudes"]
        if scheme not in {7, 8} or not isinstance(longitudes, dict):
            raise HeldOutCorpusError("karaka input is invalid")
        planets = _BODIES - {"Ketu"} if scheme == 8 else _BODIES - {"Rahu", "Ketu"}
        if set(longitudes) != planets:
            raise HeldOutCorpusError("karaka input must contain only the required planets")
        for body, longitude in longitudes.items():
            _number(longitude, f"karaka longitude {body}", upper=30)
        if not isinstance(expected, dict) or not expected:
            raise HeldOutCorpusError("karaka expected value is invalid")
        return

    if family == "rasi_drishti":
        _require_keys(scenario, {"source_sign"}, "rasi drishti input")
        _sign(scenario["source_sign"], "source_sign")
        if not isinstance(expected, list) or len(expected) != 3:
            raise HeldOutCorpusError("rasi drishti expected value is invalid")
        for sign in expected:
            _sign(sign, "rasi drishti target")
        return

    if family == "arudha":
        _require_keys(scenario, {"house", "lord"}, "arudha input")
        _sign(scenario["house"], "house")
        _sign(scenario["lord"], "lord")
        _sign(expected, "arudha expected")
        return

    if family == "co_lord":
        _require_keys(scenario, {"candidates", "durations", "degrees"}, "co-lord input")
        candidates, durations, degrees = (
            scenario["candidates"],
            scenario["durations"],
            scenario["degrees"],
        )
        if (
            not isinstance(candidates, list)
            or set(candidates) not in ({"Mars", "Ketu"}, {"Saturn", "Rahu"})
            or len(candidates) != 2
            or not isinstance(durations, dict)
            or not isinstance(degrees, dict)
            or set(durations) != set(candidates)
            or set(degrees) != set(candidates)
            or expected not in candidates
        ):
            raise HeldOutCorpusError("co-lord input is invalid")
        for candidate in candidates:
            _number(durations[candidate], f"co-lord duration {candidate}")
            _number(degrees[candidate], f"co-lord degree {candidate}", upper=30)
        return

    if family == "argala":
        _require_keys(scenario, {"source_sign", "occupants"}, "argala input")
        _sign(scenario["source_sign"], "source_sign")
        occupants = scenario["occupants"]
        if not isinstance(occupants, dict) or not isinstance(expected, list):
            raise HeldOutCorpusError("argala input is invalid")
        for sign, bodies in occupants.items():
            _sign(int(sign) if isinstance(sign, str) and sign.isdigit() else sign, "occupant sign")
            if not isinstance(bodies, list) or any(body not in _BODIES for body in bodies):
                raise HeldOutCorpusError("argala occupants must contain only bodies")
        if {item.get("house") for item in expected if isinstance(item, dict)} != {2, 4, 11, 5}:
            raise HeldOutCorpusError("argala expected value is invalid")
        return

    if family == "special_lagnas":
        _require_keys(scenario, {"sun_longitude", "minutes_since_sunrise"}, "special-lagna input")
        _number(scenario["sun_longitude"], "sun_longitude", upper=360)
        _number(scenario["minutes_since_sunrise"], "minutes_since_sunrise")
        if not isinstance(expected, dict) or set(expected) != {"bhava_lagna", "hora_lagna", "ghati_lagna"}:
            raise HeldOutCorpusError("special-lagna expected value is invalid")
        return

    _require_keys(scenario, {"lagna_sign", "lord_signs", "gender", "start"}, "chara dasha input")
    _sign(scenario["lagna_sign"], "lagna_sign")
    if not isinstance(scenario["lord_signs"], list) or len(scenario["lord_signs"]) != 12:
        raise HeldOutCorpusError("chara dasha lords are invalid")
    for sign in scenario["lord_signs"]:
        _sign(sign, "chara dasha lord sign")
    if scenario["gender"] not in {"female", "male"} or not isinstance(scenario["start"], str):
        raise HeldOutCorpusError("chara dasha input is invalid")
    if not isinstance(expected, dict) or set(expected) != {
        "signs", "years", "first_end", "first_end_in_first", "first_end_in_second"
    }:
        raise HeldOutCorpusError("chara dasha expected value is invalid")


def _validate_corpus(payload: dict[str, Any]) -> None:
    if "school" not in payload:
        raise HeldOutCorpusError("held-out corpus school identity is missing or wrong")
    _require_keys(
        payload,
        {
            "schema_version", "corpus_id", "authorship", "used_for_tuning", "public_safe",
            "school", "rule_profile_id", "rule_profile_sha256", "cases",
        },
        "held-out corpus",
    )
    if payload["schema_version"] != "1.0" or payload["corpus_id"] != "jaimini_geometry_held_out_v1":
        raise HeldOutCorpusError("unsupported held-out corpus identity")
    if payload["authorship"] != "hand_authored_not_generated":
        raise HeldOutCorpusError("held-out corpus must declare hand-authored provenance")
    if payload["used_for_tuning"] is not False:
        raise HeldOutCorpusError("held-out corpus used_for_tuning must be false")
    if payload["public_safe"] is not True:
        raise HeldOutCorpusError("held-out corpus public_safe must be true")
    if payload["school"] != _SCHOOL:
        raise HeldOutCorpusError("held-out corpus school identity is missing or wrong")
    if payload["rule_profile_id"] != "jaimini_core_v1":
        raise HeldOutCorpusError("held-out corpus profile identity is wrong")
    if payload["rule_profile_sha256"] != jaimini_rule_profile_sha256():
        raise HeldOutCorpusError("held-out corpus profile SHA-256 mismatch")
    cases = payload["cases"]
    if not isinstance(cases, list) or not cases:
        raise HeldOutCorpusError("held-out corpus cases are invalid")
    for case in cases:
        _validate_case(case)
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise HeldOutCorpusError("duplicate case ID")
    if {case["rule_family"] for case in cases} != _REQUIRED_FAMILIES:
        raise HeldOutCorpusError("held-out corpus is missing a required rule family")


def _check_checksum(corpus_path: Path, manifest_path: Path) -> None:
    manifest = _json_object(manifest_path, "held-out checksum manifest")
    _require_keys(manifest, {"schema_version", "algorithm", "files"}, "held-out checksum manifest")
    if manifest["schema_version"] != "1.0" or manifest["algorithm"] != "sha256":
        raise HeldOutCorpusError("invalid held-out checksum manifest")
    files = manifest["files"]
    if not isinstance(files, dict) or set(files) != {corpus_path.name}:
        raise HeldOutCorpusError("invalid held-out checksum manifest")
    expected = files[corpus_path.name]
    if not isinstance(expected, str) or len(expected) != 64:
        raise HeldOutCorpusError("invalid held-out checksum manifest")
    actual = hashlib.sha256(corpus_path.read_bytes()).hexdigest()
    if actual != expected:
        raise HeldOutCorpusError("held-out checksum mismatch")


def _as_utc_text(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _observe_karakas(scenario: Mapping[str, Any]) -> dict[str, str]:
    try:
        return chara_karakas(scenario["longitudes"], scheme=scenario["scheme"]).assignments
    except ExactKarakaTieError:
        return {"error": "EXACT_KARAKA_TIE"}


def _observe_argala(scenario: Mapping[str, Any]) -> list[dict[str, Any]]:
    occupants = {int(sign): bodies for sign, bodies in scenario["occupants"].items()}
    return [
        {"house": pair.house, "status": pair.status}
        for pair in argala(scenario["source_sign"], occupants)
    ]


def _observe_chara_dasha(scenario: Mapping[str, Any]) -> dict[str, Any]:
    start = dt.datetime.fromisoformat(scenario["start"].replace("Z", "+00:00"))
    periods = chara_dasha(
        scenario["lagna_sign"], scenario["lord_signs"], gender=scenario["gender"], start=start
    )
    first_end = periods[0].end
    return {
        "signs": [period.sign for period in periods],
        "years": [period.years for period in periods],
        "first_end": _as_utc_text(first_end),
        "first_end_in_first": periods[0].contains(first_end),
        "first_end_in_second": periods[1].contains(first_end),
    }


_OBSERVERS: dict[str, Callable[[Mapping[str, Any]], Any]] = {
    "karakas": _observe_karakas,
    "rasi_drishti": lambda scenario: list(rasi_drishti(scenario["source_sign"])),
    "arudha": lambda scenario: arudha_pada(scenario["house"], scenario["lord"]),
    "co_lord": lambda scenario: resolve_co_lord(
        scenario["candidates"], scenario["durations"], scenario["degrees"]
    ),
    "argala": _observe_argala,
    "special_lagnas": lambda scenario: special_lagnas(**scenario),
    "chara_dasha": _observe_chara_dasha,
}


def evaluate_held_out_geometry(
    *,
    corpus_path: Path = _DEFAULT_CORPUS,
    manifest_path: Path = _DEFAULT_MANIFEST,
    allow_held_out: bool = False,
) -> dict[str, Any]:
    """Run the sealed corpus only after an explicit final-review opt-in."""
    if not allow_held_out:
        raise ValueError("held-out execution requires allow_held_out=True")
    _check_checksum(corpus_path, manifest_path)
    corpus = _json_object(corpus_path, "held-out corpus")
    _validate_corpus(corpus)
    failures: list[dict[str, Any]] = []
    for case in corpus["cases"]:
        observed = _OBSERVERS[case["rule_family"]](case["input"])
        if observed != case["expected"]:
            failures.append(
                {
                    "rule_family": case["rule_family"],
                    "expected": case["expected"],
                    "observed": observed,
                }
            )
    return {
        "corpus_id": corpus["corpus_id"],
        "case_count": len(corpus["cases"]),
        "passed_count": len(corpus["cases"]) - len(failures),
        "failed_count": len(failures),
        "failures": failures,
    }
