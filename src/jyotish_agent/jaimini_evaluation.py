"""Independent, hand-authored held-out checks for Jaimini Core geometry.

This evaluator is intentionally limited to deterministic scalar/sign geometry.
It neither admits doctrine sources nor replaces human-reviewed worked cases.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
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
from .rule_profiles import jaimini_rule_profile_sha256, jaimini_source_map_sha256


class HeldOutCorpusError(ValueError):
    """The sealed geometry corpus is malformed, substituted, or unsafe."""


class HandWorkedCorpusError(ValueError):
    """The hand-worked corpus is malformed, substituted, or runtime-derived."""


_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CORPUS = _ROOT / "eval" / "jaimini" / "geometry-held-out-v1.json"
_DEFAULT_MANIFEST = _ROOT / "eval" / "jaimini" / "geometry-held-out-v1-checksums.json"
_DEFAULT_HAND_WORKED_CORPUS = _ROOT / "eval" / "jaimini" / "hand-worked-v1.json"
_DEFAULT_HAND_WORKED_MANIFEST = (
    _ROOT / "eval" / "jaimini" / "hand-worked-v1-checksums.json"
)
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
_KARAKA_LABELS = {
    7: ("AK", "AmK", "BK", "MK", "PK", "GK", "DK"),
    8: ("AK", "AmK", "BK", "MK", "PiK", "PK", "GK", "DK"),
}
_CASE_ID = re.compile(r"^[a-z][a-z0-9_]{2,80}$")
_UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


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


def _utc_timestamp(value: Any, label: str) -> dt.datetime:
    if not isinstance(value, str) or not _UTC_TIMESTAMP.fullmatch(value):
        raise HeldOutCorpusError(f"{label} must be a UTC timestamp")
    try:
        return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.UTC)
    except ValueError as exc:
        raise HeldOutCorpusError(f"{label} must be a real UTC timestamp") from exc


def _validate_case(case: Any) -> None:
    if not isinstance(case, dict):
        raise HeldOutCorpusError("case must be an object")
    if case.get("school") != _SCHOOL:
        raise HeldOutCorpusError("case school identity is missing or wrong")
    if case.get("rule_profile_id") != "jaimini_core_v1":
        raise HeldOutCorpusError("case profile identity is missing or wrong")
    if case.get("rule_profile_sha256") != jaimini_rule_profile_sha256():
        raise HeldOutCorpusError("case profile SHA-256 mismatch")
    _require_keys(
        case,
        {
            "id", "school", "rule_profile_id", "rule_profile_sha256", "rule_family",
            "input", "expected",
        },
        "case",
    )
    if not isinstance(case["id"], str) or not _CASE_ID.fullmatch(case["id"]):
        raise HeldOutCorpusError("case ID must be a lowercase identifier")
    family = case["rule_family"]
    if family not in _REQUIRED_FAMILIES:
        raise HeldOutCorpusError("case has an unknown rule family")
    scenario, expected = case["input"], case["expected"]
    if not isinstance(scenario, dict):
        raise HeldOutCorpusError("synthetic scalar/sign inputs must be objects")

    if family == "karakas":
        if set(scenario) != {"scheme", "longitudes"}:
            raise HeldOutCorpusError("karaka input has an invalid schema")
        scheme, longitudes = scenario["scheme"], scenario["longitudes"]
        if isinstance(scheme, bool) or scheme not in _KARAKA_LABELS or not isinstance(longitudes, dict):
            raise HeldOutCorpusError("karaka input is invalid")
        planets = _BODIES - {"Ketu"} if scheme == 8 else _BODIES - {"Rahu", "Ketu"}
        if set(longitudes) != planets:
            raise HeldOutCorpusError("karaka input must contain only the required planets")
        for body, longitude in longitudes.items():
            _number(longitude, f"karaka longitude {body}", upper=30)
        if not isinstance(expected, dict):
            raise HeldOutCorpusError("karaka expected value is invalid")
        if set(expected) == {"error"} and expected["error"] == "EXACT_KARAKA_TIE":
            return
        if (
            set(expected) != set(_KARAKA_LABELS[scheme])
            or not all(isinstance(value, str) and value in planets for value in expected.values())
            or len(set(expected.values())) != len(expected)
        ):
            raise HeldOutCorpusError("karaka expected value is invalid")
        return

    if family == "rasi_drishti":
        _require_keys(scenario, {"source_sign"}, "rasi drishti input")
        _sign(scenario["source_sign"], "source_sign")
        if not isinstance(expected, list) or len(expected) != 3 or len(set(expected)) != 3:
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
            or not all(isinstance(candidate, str) for candidate in candidates)
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
            _number(durations[candidate], f"co-lord duration {candidate}", upper=12)
            _number(degrees[candidate], f"co-lord degree {candidate}", upper=30)
        return

    if family == "argala":
        _require_keys(scenario, {"source_sign", "occupants"}, "argala input")
        _sign(scenario["source_sign"], "source_sign")
        occupants = scenario["occupants"]
        if not isinstance(occupants, dict) or not isinstance(expected, list):
            raise HeldOutCorpusError("argala input is invalid")
        for sign, bodies in occupants.items():
            if not isinstance(sign, str) or not re.fullmatch(r"(?:0|[1-9]|1[01])", sign):
                raise HeldOutCorpusError("argala occupant sign is invalid")
            if (
                not isinstance(bodies, list)
                or not bodies
                or not all(isinstance(body, str) and body in _BODIES for body in bodies)
                or len(bodies) != len(set(bodies))
            ):
                raise HeldOutCorpusError("argala occupants must contain only bodies")
        if (
            len(expected) != 4
            or any(not isinstance(item, dict) or set(item) != {"house", "status"} for item in expected)
            or [item["house"] for item in expected] != [2, 4, 11, 5]
            or any(item["status"] not in {"absent", "unobstructed", "partial", "obstructed"} for item in expected)
        ):
            raise HeldOutCorpusError("argala expected value is invalid")
        return

    if family == "special_lagnas":
        _require_keys(scenario, {"sun_longitude", "minutes_since_sunrise"}, "special-lagna input")
        _number(scenario["sun_longitude"], "sun_longitude", upper=360)
        _number(scenario["minutes_since_sunrise"], "minutes_since_sunrise", upper=1440)
        if not isinstance(expected, dict) or set(expected) != {"bhava_lagna", "hora_lagna", "ghati_lagna"}:
            raise HeldOutCorpusError("special-lagna expected value is invalid")
        for name, value in expected.items():
            _number(value, f"special-lagna expected {name}", upper=360)
        return

    _require_keys(scenario, {"lagna_sign", "lord_signs", "gender", "start"}, "chara dasha input")
    _sign(scenario["lagna_sign"], "lagna_sign")
    if not isinstance(scenario["lord_signs"], list) or len(scenario["lord_signs"]) != 12:
        raise HeldOutCorpusError("chara dasha lords are invalid")
    for sign in scenario["lord_signs"]:
        _sign(sign, "chara dasha lord sign")
    if (
        scenario["gender"] not in {"female", "male"}
    ):
        raise HeldOutCorpusError("chara dasha input is invalid")
    _utc_timestamp(scenario["start"], "chara dasha start")
    if not isinstance(expected, dict) or set(expected) != {
        "signs", "years", "first_end", "first_end_in_first", "first_end_in_second"
    }:
        raise HeldOutCorpusError("chara dasha expected value is invalid")
    if (
        not isinstance(expected["signs"], list)
        or len(expected["signs"]) != 12
        or not isinstance(expected["years"], list)
        or len(expected["years"]) != 12
        or type(expected["first_end_in_first"]) is not bool
        or type(expected["first_end_in_second"]) is not bool
    ):
        raise HeldOutCorpusError("chara dasha expected value is invalid")
    _utc_timestamp(expected["first_end"], "chara dasha expected first_end")
    for sign in expected["signs"]:
        _sign(sign, "chara dasha expected sign")
    for years in expected["years"]:
        if isinstance(years, bool) or not isinstance(years, int) or not 1 <= years <= 12:
            raise HeldOutCorpusError("chara dasha expected years are invalid")


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
    try:
        _validate_corpus(corpus)
    except HeldOutCorpusError:
        raise
    except (TypeError, ValueError, OverflowError) as exc:
        raise HeldOutCorpusError("held-out corpus semantic validation failed") from exc
    failures: list[dict[str, Any]] = []
    for case in corpus["cases"]:
        observed = _OBSERVERS[case["rule_family"]](case["input"])
        if observed != case["expected"]:
            failures.append(
                {
                    "case_id": case["id"],
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


def _check_hand_worked_checksum(corpus_path: Path, manifest_path: Path) -> None:
    try:
        manifest = _json_object(manifest_path, "hand-worked checksum manifest")
    except HeldOutCorpusError as exc:
        raise HandWorkedCorpusError(str(exc)) from exc
    try:
        _require_keys(
            manifest,
            {"schema_version", "algorithm", "files"},
            "hand-worked checksum manifest",
        )
        if manifest["schema_version"] != "1.0" or manifest["algorithm"] != "sha256":
            raise HandWorkedCorpusError("invalid hand-worked checksum manifest")
        files = manifest["files"]
        if not isinstance(files, dict) or set(files) != {corpus_path.name}:
            raise HandWorkedCorpusError("invalid hand-worked checksum manifest")
        expected = files[corpus_path.name]
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise HandWorkedCorpusError("invalid hand-worked checksum manifest")
        if hashlib.sha256(corpus_path.read_bytes()).hexdigest() != expected:
            raise HandWorkedCorpusError("hand-worked checksum mismatch")
    except OSError as exc:
        raise HandWorkedCorpusError("invalid hand-worked corpus") from exc


def _validate_hand_worked_corpus(payload: dict[str, Any]) -> None:
    try:
        _require_keys(
            payload,
            {
                "schema_version",
                "corpus_id",
                "authorship",
                "used_for_tuning",
                "public_safe",
                "school",
                "rule_profile_id",
                "rule_profile_sha256",
                "source_map_sha256",
                "cases",
            },
            "hand-worked corpus",
        )
    except HeldOutCorpusError as exc:
        raise HandWorkedCorpusError(str(exc)) from exc
    if (
        payload["schema_version"] != "1.0"
        or payload["corpus_id"] != "jaimini_hand_worked_v1"
        or payload["authorship"] != "independently_hand_calculated"
        or payload["used_for_tuning"] is not False
        or payload["public_safe"] is not True
        or payload["school"] != _SCHOOL
        or payload["rule_profile_id"] != "jaimini_core_v1"
        or payload["rule_profile_sha256"] != jaimini_rule_profile_sha256()
        or payload["source_map_sha256"] != jaimini_source_map_sha256()
    ):
        raise HandWorkedCorpusError("hand-worked corpus provenance is invalid")
    cases = payload["cases"]
    if not isinstance(cases, list) or len(cases) < 5:
        raise HandWorkedCorpusError("hand-worked corpus requires at least five cases")

    case_ids: list[str] = []
    check_ids: list[str] = []
    covered: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            raise HandWorkedCorpusError("hand-worked case must be an object")
        if set(case) != {
            "id",
            "authorship",
            "runtime_derived_expected",
            "derivation",
            "checks",
        }:
            raise HandWorkedCorpusError("hand-worked case has an invalid schema")
        if (
            not isinstance(case["id"], str)
            or not _CASE_ID.fullmatch(case["id"])
            or case["authorship"] != "independently_hand_calculated"
            or case["runtime_derived_expected"] is not False
        ):
            raise HandWorkedCorpusError("hand-worked case provenance is invalid")
        derivation = case["derivation"]
        if (
            not isinstance(derivation, list)
            or not derivation
            or not all(
                isinstance(step, str)
                and 1 <= len(step) <= 500
                and not any(
                    marker in step.casefold()
                    for marker in ("private_sources", ".pdf", "/users/")
                )
                for step in derivation
            )
        ):
            raise HandWorkedCorpusError("hand-worked derivation is invalid")
        checks = case["checks"]
        if not isinstance(checks, list) or not checks:
            raise HandWorkedCorpusError("hand-worked case requires checks")
        case_ids.append(case["id"])
        for check in checks:
            if not isinstance(check, dict) or set(check) != {
                "check_id",
                "rule_family",
                "input",
                "expected",
            }:
                raise HandWorkedCorpusError("hand-worked check has an invalid schema")
            check_id = check["check_id"]
            if not isinstance(check_id, str) or not _CASE_ID.fullmatch(check_id):
                raise HandWorkedCorpusError("hand-worked check ID is invalid")
            synthetic_case = {
                "id": check_id,
                "school": payload["school"],
                "rule_profile_id": payload["rule_profile_id"],
                "rule_profile_sha256": payload["rule_profile_sha256"],
                "rule_family": check["rule_family"],
                "input": check["input"],
                "expected": check["expected"],
            }
            try:
                _validate_case(synthetic_case)
            except HeldOutCorpusError as exc:
                raise HandWorkedCorpusError(str(exc)) from exc
            check_ids.append(check_id)
            covered.add(check["rule_family"])
    if len(case_ids) != len(set(case_ids)):
        raise HandWorkedCorpusError("duplicate hand-worked case ID")
    if len(check_ids) != len(set(check_ids)):
        raise HandWorkedCorpusError("duplicate hand-worked check ID")
    if covered != _REQUIRED_FAMILIES:
        raise HandWorkedCorpusError("hand-worked corpus is missing a rule family")


def evaluate_hand_worked_cases(
    *,
    corpus_path: Path = _DEFAULT_HAND_WORKED_CORPUS,
    manifest_path: Path = _DEFAULT_HAND_WORKED_MANIFEST,
    allow_hand_worked: bool = False,
) -> dict[str, Any]:
    """Run independently hand-calculated public-safe composite cases."""
    if not allow_hand_worked:
        raise ValueError("hand-worked execution requires allow_hand_worked=True")
    _check_hand_worked_checksum(corpus_path, manifest_path)
    try:
        corpus = _json_object(corpus_path, "hand-worked corpus")
    except HeldOutCorpusError as exc:
        raise HandWorkedCorpusError(str(exc)) from exc
    _validate_hand_worked_corpus(corpus)

    failures: list[dict[str, Any]] = []
    check_count = 0
    covered: set[str] = set()
    for case in corpus["cases"]:
        for check in case["checks"]:
            check_count += 1
            covered.add(check["rule_family"])
            observed = _OBSERVERS[check["rule_family"]](check["input"])
            if observed != check["expected"]:
                failures.append(
                    {
                        "case_id": case["id"],
                        "check_id": check["check_id"],
                        "rule_family": check["rule_family"],
                        "expected": check["expected"],
                        "observed": observed,
                    }
                )
    return {
        "corpus_id": corpus["corpus_id"],
        "corpus_sha256": hashlib.sha256(corpus_path.read_bytes()).hexdigest(),
        "rule_profile_sha256": corpus["rule_profile_sha256"],
        "source_map_sha256": corpus["source_map_sha256"],
        "status": "failed" if failures else "passed",
        "case_count": len(corpus["cases"]),
        "check_count": check_count,
        "passed_count": check_count - len(failures),
        "failed_count": len(failures),
        "covered_rule_families": sorted(covered),
        "failures": failures,
    }
