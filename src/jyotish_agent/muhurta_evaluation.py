"""Independent held-out evaluation for the Expanded Muhurta release."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo

from .doctrine.muhurta_pack import (
    MuhurtaActivityProfile,
    MuhurtaEligibilityInput,
    MuhurtaNatalFactorsInput,
    MuhurtaRankingCandidate,
    MuhurtaRuleInterval,
    evaluate_muhurta_eligibility,
    evaluate_muhurta_natal_factors,
    load_muhurta_ranking_profile,
    load_muhurta_release_audit,
    rank_muhurta_candidates,
    route_muhurta_activity,
)
from .muhurta import MuhurtaFacade
from .muhurta_models import MuhurtaSearchRequest


class MuhurtaHeldOutCorpusError(ValueError):
    """The Muhurta held-out corpus is malformed, substituted, or unsafe."""


_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CORPUS = _ROOT / "eval/muhurta/independent-held-out-v1.json"
_DEFAULT_MANIFEST = (
    _ROOT / "eval/muhurta/independent-held-out-v1-checksums.json"
)
_CASE_ID = re.compile(r"^[a-z][a-z0-9_]{2,80}$")
_CASE_KEYS = {"id", "kind", "coverage_tags", "input", "expected"}
_KINDS = {
    "route",
    "eligibility",
    "personalization",
    "ranking",
    "skipped_date_search",
}
_REQUIRED_COVERAGE = {
    "ru",
    "en",
    "all_profiles",
    "high_stakes",
    "ambiguous",
    "hard_constraint",
    "half_open_boundary",
    "dst_fold",
    "source_substitution",
    "personalization",
    "uncertainty",
    "ranking",
    "score_manipulation",
    "stable_tie",
    "skipped_date",
}
_FORBIDDEN_TEXT = ("private_sources", ".pdf", "/users/", "token=")


def _json_object(path: Path, label: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MuhurtaHeldOutCorpusError(f"invalid {label}") from exc
    if not isinstance(payload, dict):
        raise MuhurtaHeldOutCorpusError(f"invalid {label}")
    return payload


def _require_keys(
    value: dict[str, object], expected: set[str], label: str
) -> None:
    if set(value) != expected:
        raise MuhurtaHeldOutCorpusError(f"{label} has an invalid schema")


def _verify_checksum(corpus_path: Path, manifest_path: Path) -> None:
    manifest = _json_object(manifest_path, "Muhurta held-out checksum manifest")
    _require_keys(
        manifest,
        {"schema_version", "algorithm", "files"},
        "Muhurta held-out checksum manifest",
    )
    files = manifest["files"]
    if (
        manifest["schema_version"] != "1.0"
        or manifest["algorithm"] != "sha256"
        or not isinstance(files, dict)
        or set(files) != {corpus_path.name}
    ):
        raise MuhurtaHeldOutCorpusError(
            "invalid Muhurta held-out checksum manifest"
        )
    expected = files[corpus_path.name]
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise MuhurtaHeldOutCorpusError(
            "invalid Muhurta held-out checksum manifest"
        )
    try:
        actual = hashlib.sha256(corpus_path.read_bytes()).hexdigest()
    except OSError as exc:
        raise MuhurtaHeldOutCorpusError("invalid Muhurta held-out corpus") from exc
    if actual != expected:
        raise MuhurtaHeldOutCorpusError("Muhurta held-out checksum mismatch")


def _local_datetime(value: object, zone_id: object, fold: object) -> dt.datetime:
    if (
        not isinstance(value, str)
        or not isinstance(zone_id, str)
        or type(fold) is not int
        or fold not in {0, 1}
    ):
        raise ValueError("invalid held-out local datetime")
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        raise ValueError("held-out local datetime must be naive")
    return parsed.replace(tzinfo=ZoneInfo(zone_id), fold=fold)


def _eligibility_value(payload: dict[str, object]) -> MuhurtaEligibilityInput:
    _require_keys(
        payload,
        {
            "profile",
            "zone_id",
            "start_local",
            "end_local",
            "start_fold",
            "end_fold",
            "panchanga_status",
            "dosa_status",
            "weekday_status",
            "daylight_status",
            "lagna_status",
            "require_daylight",
            "require_lagna",
            "source_admitted",
            "intervals",
        },
        "Muhurta held-out eligibility input",
    )
    intervals = payload["intervals"]
    if not isinstance(intervals, list):
        raise MuhurtaHeldOutCorpusError(
            "Muhurta held-out intervals must be a list"
        )
    parsed_intervals: list[MuhurtaRuleInterval] = []
    for interval in intervals:
        if not isinstance(interval, dict):
            raise MuhurtaHeldOutCorpusError(
                "Muhurta held-out interval must be an object"
            )
        _require_keys(
            interval,
            {
                "rule_id",
                "classification",
                "start_local",
                "end_local",
                "start_fold",
                "end_fold",
                "source_locator",
            },
            "Muhurta held-out interval",
        )
        parsed_intervals.append(
            MuhurtaRuleInterval.model_validate(
                {
                    "rule_id": interval["rule_id"],
                    "classification": interval["classification"],
                    "start": _local_datetime(
                        interval["start_local"],
                        payload["zone_id"],
                        interval["start_fold"],
                    ),
                    "end": _local_datetime(
                        interval["end_local"],
                        payload["zone_id"],
                        interval["end_fold"],
                    ),
                    "source_locator": interval["source_locator"],
                }
            )
        )
    return MuhurtaEligibilityInput.model_validate(
        {
            "profile": payload["profile"],
            "start": _local_datetime(
                payload["start_local"], payload["zone_id"], payload["start_fold"]
            ),
            "end": _local_datetime(
                payload["end_local"], payload["zone_id"], payload["end_fold"]
            ),
            "zone_id": payload["zone_id"],
            "panchanga_status": payload["panchanga_status"],
            "dosa_status": payload["dosa_status"],
            "weekday_status": payload["weekday_status"],
            "daylight_status": payload["daylight_status"],
            "lagna_status": payload["lagna_status"],
            "require_daylight": payload["require_daylight"],
            "require_lagna": payload["require_lagna"],
            "source_rule_intervals": parsed_intervals,
            "source_admitted": payload["source_admitted"],
        }
    )


def _ranking_values(
    payload: dict[str, object],
) -> tuple[MuhurtaActivityProfile, tuple[MuhurtaRankingCandidate, ...]]:
    _require_keys(
        payload,
        {"profile", "candidates"},
        "Muhurta held-out ranking input",
    )
    profile = MuhurtaActivityProfile(payload["profile"])
    candidates = payload["candidates"]
    if not isinstance(candidates, list) or not candidates:
        raise MuhurtaHeldOutCorpusError(
            "Muhurta held-out ranking candidates are invalid"
        )
    parsed: list[MuhurtaRankingCandidate] = []
    candidate_keys = {
        "candidate_id",
        "start_utc",
        "end_utc",
        "eligibility_status",
        "hard_failure_ids",
        "doctrinal_soft_score",
        "natal_soft_adjustment",
        "user_preference_score",
        "confidence",
    }
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise MuhurtaHeldOutCorpusError(
                "Muhurta held-out ranking candidate must be an object"
            )
        _require_keys(
            candidate, candidate_keys, "Muhurta held-out ranking candidate"
        )
        parsed.append(
            MuhurtaRankingCandidate.model_validate(
                {
                    "candidate_id": candidate["candidate_id"],
                    "start": candidate["start_utc"],
                    "end": candidate["end_utc"],
                    "eligibility_status": candidate["eligibility_status"],
                    "hard_failure_ids": candidate["hard_failure_ids"],
                    "doctrinal_soft_score": candidate["doctrinal_soft_score"],
                    "natal_soft_adjustment": candidate["natal_soft_adjustment"],
                    "user_preference_score": candidate["user_preference_score"],
                    "confidence": candidate["confidence"],
                }
            )
        )
    return profile, tuple(parsed)


def _validate_case_schema(case: dict[str, object]) -> None:
    _require_keys(case, _CASE_KEYS, "Muhurta held-out case")
    case_id = case["id"]
    kind = case["kind"]
    tags = case["coverage_tags"]
    payload = case["input"]
    expected = case["expected"]
    if (
        not isinstance(case_id, str)
        or _CASE_ID.fullmatch(case_id) is None
        or kind not in _KINDS
        or not isinstance(tags, list)
        or not tags
        or not all(isinstance(tag, str) and tag in _REQUIRED_COVERAGE for tag in tags)
        or not isinstance(payload, dict)
        or not isinstance(expected, dict)
    ):
        raise MuhurtaHeldOutCorpusError("Muhurta held-out case identity is invalid")
    rendered = json.dumps(case, ensure_ascii=False).casefold()
    if any(marker in rendered for marker in _FORBIDDEN_TEXT):
        raise MuhurtaHeldOutCorpusError("Muhurta held-out case is not public-safe")

    if kind == "route":
        _require_keys(payload, {"activity", "locale"}, "Muhurta held-out route input")
        _require_keys(
            expected,
            {"status", "profile", "reason_code"},
            "Muhurta held-out route expectation",
        )
        if payload["locale"] not in {"ru", "en"}:
            raise MuhurtaHeldOutCorpusError("Muhurta held-out locale is invalid")
    elif kind == "eligibility":
        _eligibility_value(payload)
        _require_keys(
            expected,
            {"status", "hard_failures", "reason_code"},
            "Muhurta held-out eligibility expectation",
        )
    elif kind == "personalization":
        MuhurtaNatalFactorsInput.model_validate(payload)
        _require_keys(
            expected,
            {
                "status",
                "tara_bala",
                "candra_bala",
                "soft_adjustment",
                "confidence",
                "reason_code",
                "can_override_hard_exclusion",
            },
            "Muhurta held-out personalization expectation",
        )
    elif kind == "ranking":
        _ranking_values(payload)
        _require_keys(
            expected,
            {"status", "ranked_ids", "total_scores", "near_miss_ids"},
            "Muhurta held-out ranking expectation",
        )
    else:
        MuhurtaSearchRequest.model_validate(payload)
        _require_keys(
            expected,
            {
                "status",
                "range_duration_seconds",
                "has_windows",
                "skipped_local_date_window_count",
            },
            "Muhurta held-out skipped-date expectation",
        )


def _validate_corpus(payload: dict[str, object]) -> None:
    _require_keys(
        payload,
        {
            "schema_version",
            "corpus_id",
            "authorship",
            "used_for_tuning",
            "public_safe",
            "source_admission_mode",
            "corpus_manifest_sha256",
            "compiled_profile_sha256",
            "cases",
        },
        "Muhurta held-out corpus",
    )
    release = load_muhurta_release_audit(verify_source_bytes=False)
    if (
        payload["schema_version"] != "1.0"
        or payload["corpus_id"] != "muhurta_independent_held_out_v1"
        or payload["authorship"] != "independently_hand_authored"
        or payload["used_for_tuning"] is not False
        or payload["public_safe"] is not True
        or payload["source_admission_mode"]
        != "synthetic_inputs_against_admitted_private_baseline"
        or payload["corpus_manifest_sha256"] != release.corpus_manifest_sha256
        or payload["compiled_profile_sha256"] != release.compiled_profile_sha256
    ):
        raise MuhurtaHeldOutCorpusError("Muhurta held-out provenance is invalid")
    cases = payload["cases"]
    if not isinstance(cases, list) or len(cases) < 19:
        raise MuhurtaHeldOutCorpusError(
            "Muhurta held-out corpus requires at least nineteen cases"
        )
    case_ids: list[str] = []
    kinds: set[str] = set()
    coverage: set[str] = set()
    supported_profiles: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            raise MuhurtaHeldOutCorpusError(
                "Muhurta held-out case must be an object"
            )
        try:
            _validate_case_schema(case)
        except (TypeError, ValueError) as exc:
            if isinstance(exc, MuhurtaHeldOutCorpusError):
                raise
            raise MuhurtaHeldOutCorpusError(
                "Muhurta held-out typed case is invalid"
            ) from exc
        case_ids.append(str(case["id"]))
        kinds.add(str(case["kind"]))
        coverage.update(str(tag) for tag in case["coverage_tags"])
        expected = case["expected"]
        if (
            case["kind"] == "route"
            and isinstance(expected, dict)
            and expected.get("status") == "supported"
            and isinstance(expected.get("profile"), str)
        ):
            supported_profiles.add(expected["profile"])
    if len(case_ids) != len(set(case_ids)):
        raise MuhurtaHeldOutCorpusError("duplicate Muhurta held-out case ID")
    if (
        kinds != _KINDS
        or coverage != _REQUIRED_COVERAGE
        or supported_profiles != {item.value for item in MuhurtaActivityProfile}
    ):
        raise MuhurtaHeldOutCorpusError(
            "Muhurta held-out corpus has incomplete required coverage"
        )


def _observe_case(case: dict[str, object]) -> dict[str, object]:
    kind = case["kind"]
    payload = case["input"]
    assert isinstance(payload, dict)
    if kind == "route":
        route = route_muhurta_activity(
            str(payload["activity"]), locale=payload["locale"]
        )
        return {
            "status": route.status,
            "profile": route.profile.value if route.profile is not None else None,
            "reason_code": route.reason_code,
        }
    if kind == "eligibility":
        result = evaluate_muhurta_eligibility(_eligibility_value(payload))
        return {
            "status": result.status,
            "hard_failures": list(result.hard_failures),
            "reason_code": result.reason_code,
        }
    if kind == "personalization":
        result = evaluate_muhurta_natal_factors(
            MuhurtaNatalFactorsInput.model_validate(payload)
        )
        return {
            "status": result.status,
            "tara_bala": result.tara_bala,
            "candra_bala": result.candra_bala,
            "soft_adjustment": result.soft_adjustment,
            "confidence": result.confidence,
            "reason_code": result.reason_code,
            "can_override_hard_exclusion": result.can_override_hard_exclusion,
        }
    if kind == "ranking":
        profile, candidates = _ranking_values(payload)
        result = rank_muhurta_candidates(
            candidates, load_muhurta_ranking_profile(profile)
        )
        return {
            "status": result.status,
            "ranked_ids": [item.candidate_id for item in result.ranked],
            "total_scores": [item.total_score for item in result.ranked],
            "near_miss_ids": [item.candidate_id for item in result.near_misses],
        }
    request = MuhurtaSearchRequest.model_validate(payload)
    result = MuhurtaFacade().search(request)
    windows = getattr(result, "windows", ())
    zone = ZoneInfo(request.place.zone_id)
    return {
        "status": result.status,
        "range_duration_seconds": request.range_duration_seconds,
        "has_windows": bool(windows),
        "skipped_local_date_window_count": sum(
            item.start.astimezone(zone).date() == dt.date(2011, 12, 30)
            for item in windows
        ),
    }


def evaluate_muhurta_held_out_cases(
    *,
    corpus_path: Path = _DEFAULT_CORPUS,
    manifest_path: Path = _DEFAULT_MANIFEST,
    allow_held_out: bool = False,
) -> dict[str, object]:
    """Run the sealed corpus without exposing its synthetic input payloads."""

    if not allow_held_out:
        raise ValueError("Muhurta held-out execution requires allow_held_out=True")
    _verify_checksum(corpus_path, manifest_path)
    corpus = _json_object(corpus_path, "Muhurta held-out corpus")
    _validate_corpus(corpus)
    cases = corpus["cases"]
    assert isinstance(cases, list)

    failures: list[dict[str, object]] = []
    covered_categories: set[str] = set()
    for case in cases:
        assert isinstance(case, dict)
        expected = case["expected"]
        assert isinstance(expected, dict)
        try:
            observed = _observe_case(case)
        except (TypeError, ValueError) as exc:
            raise MuhurtaHeldOutCorpusError(
                "Muhurta held-out case execution is invalid"
            ) from exc
        if observed != expected:
            failures.append(
                {
                    "case_id": case["id"],
                    "expected": expected,
                    "observed": observed,
                }
            )
        covered_categories.add(str(case["kind"]))

    case_count = len(cases)
    material_error_count = len(failures)
    return {
        "corpus_id": corpus["corpus_id"],
        "corpus_sha256": hashlib.sha256(corpus_path.read_bytes()).hexdigest(),
        "corpus_manifest_sha256": corpus["corpus_manifest_sha256"],
        "compiled_profile_sha256": corpus["compiled_profile_sha256"],
        "source_admission_mode": corpus["source_admission_mode"],
        "status": "failed" if failures else "passed",
        "case_count": case_count,
        "passed_count": case_count - material_error_count,
        "failed_count": material_error_count,
        "material_error_count": material_error_count,
        "material_error_rate": round(material_error_count / case_count, 6),
        "covered_categories": sorted(covered_categories),
        "covered_profiles": sorted(item.value for item in MuhurtaActivityProfile),
        "failures": failures,
    }
