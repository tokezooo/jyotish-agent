"""Deterministic Praśna work/project facts over one sealed question moment."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import threading
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Literal
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from . import ENGINE_VERSION, names
from .config import CalculationConfig, ConfigError
from .error_registry import error_record
from .event_models import EventAnchor, EventPlace
from .prashna_models import (
    PrashnaCompletedResult,
    PrashnaFact,
    PrashnaIncompleteResult,
    PrashnaNeedsInputResult,
    PrashnaProvenance,
    PrashnaRequest,
    PrashnaResult,
    PrashnaRuleResult,
    PrashnaTruncation,
    PrashnaUnavailableResult,
)
from .prashna_profiles import (
    PrashnaGovernanceError,
    PrashnaRuleProfile,
    load_prashna_rule_profile,
    load_prashna_source_map,
    prashna_rule_profile_sha256,
    prashna_source_admission_evidence,
    prashna_source_map_sha256,
)
from .pyjhora_facade import BirthProfile, EngineOutputError, _run_engine_session
from .signing import cache_domain_artifact, get_cached_domain_artifact, sign_facts, verify_domain_artifact

_WORD = re.compile(r"[^\w]+", re.UNICODE)
_WORK = ("work", "project", "job", "career", "business", "founder", "startup", "работ", "проект", "карьер", "бизнес", "стартап", "делов")
_RELATIONSHIP = ("relationship", "partner", "love", "marriage", "отнош", "любов", "брак")
_HIGH_STAKES = (
    "medical", "health", "surgery", "cancer", "pregnan", "death", "die", "harm",
    "lawsuit", "court", "legal", "invest", "stock", "crypto", "loan",
    "здоров", "операц", "рак", "беремен", "смерт", "умр", "вред", "суд", "юрид", "инвест", "крипт", "кредит",
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _normalized_question(question: str) -> str:
    value = unicodedata.normalize("NFKC", question).casefold().replace("ё", "е")
    return " ".join(part for part in _WORD.sub(" ", value).split() if part)


def question_fingerprint(question: str) -> str:
    return hashlib.sha256(_normalized_question(question).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TopicRoute:
    status: Literal["supported", "unsupported", "composite", "high_stakes"]
    family: str | None = None
    primary_house: int | None = None
    secondary_houses: tuple[int, ...] = ()


def _contains_any(text: str, fragments: tuple[str, ...]) -> bool:
    return any(fragment in text for fragment in fragments)


def route_prashna_topic(question: str, profile: PrashnaRuleProfile | None = None) -> TopicRoute:
    profile = profile or load_prashna_rule_profile()
    normalized = _normalized_question(question)
    if _contains_any(normalized, _HIGH_STAKES):
        return TopicRoute("high_stakes")
    work = _contains_any(normalized, _WORK)
    relationship = _contains_any(normalized, _RELATIONSHIP)
    if work and relationship:
        return TopicRoute("composite")
    if work:
        return TopicRoute(
            "supported",
            profile.question_family,
            profile.primary_house,
            profile.secondary_houses,
        )
    return TopicRoute("unsupported")


def _rasi_drishti(source: int) -> tuple[int, ...]:
    movable, fixed, dual = {0, 3, 6, 9}, {1, 4, 7, 10}, {2, 5, 8, 11}
    if source in movable:
        targets = fixed - {(source + 1) % 12}
    elif source in fixed:
        targets = movable - {(source - 1) % 12}
    else:
        targets = dual - {source}
    return tuple(sorted(targets))


def _utc_text(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _anchor_payload(anchor: EventAnchor) -> dict:
    resolved = anchor.resolved()
    return {
        "asked_at": anchor.asked_at.isoformat(),
        "normalized_utc": _utc_text(resolved.utc_instant),
        "zone_id": anchor.place.zone_id,
        "fold": resolved.fold,
        "offset_minutes": resolved.offset_minutes,
        "tzdb_fingerprint": resolved.tzdb_fingerprint,
        "time_confidence": anchor.time_confidence,
        # Private server-held replay inputs. They are HMAC-bound and never returned.
        "place": {
            "name": anchor.place.name,
            "latitude": anchor.place.latitude,
            "longitude": anchor.place.longitude,
            "zone_id": anchor.place.zone_id,
            "fold": anchor.place.fold,
        },
    }


def _request_id(fingerprint: str, anchor_hash: str) -> str:
    return "prq_" + hashlib.sha256(f"{fingerprint}:{anchor_hash}".encode()).hexdigest()[:24]


def _prashna_config_sha256() -> str:
    config = CalculationConfig(charts=("D1",))
    return _sha({
        "ayanamsa": config.ayanamsa,
        "rahu_ketu": config.rahu_ketu,
        "node_aspects": config.node_aspects,
        "charts": tuple(config.resolved_charts()),
        "modules": tuple(sorted(config.resolved_modules())),
    })


@dataclass(frozen=True)
class _CaptureRecord:
    material_sha256: str
    anchor_data: dict
    anchor_token: str


_CAPTURE_CACHE: "OrderedDict[str, _CaptureRecord]" = OrderedDict()
_CAPTURE_CACHE_MAX = 256
_CAPTURE_LOCK = threading.Lock()


class _IdempotencyConflict(ValueError):
    pass


class _PrashnaEngineFailure(RuntimeError):
    pass


def _error_fields(code: str, *, request_id: str, stage: str) -> dict:
    record = error_record(
        code,
        run_id=None,
        request_id=request_id,
        mode="prashna",
        stage=stage,
    )
    return {
        key: record[key]
        for key in (
            "error_code", "request_id", "mode", "stage", "retryable",
            "problem", "cause", "fix", "next_action",
        )
    }


def _provable_clarification(original: str, current: str) -> bool:
    """Allow only the exact original normalized question plus a short suffix."""
    if not current.startswith(original + " "):
        return False
    suffix = current[len(original):].strip().split()
    allowed = {
        "which", "obstacle", "is", "most", "visible", "strongest", "primary",
        "now", "please", "clarify", "detail", "what", "does", "this", "mean",
        "какое", "препятствие", "сейчас", "самое", "заметное", "главное",
        "уточни", "поясни", "пожалуйста", "что", "это", "значит",
    }
    return 2 <= len(suffix) <= 20 and set(suffix) <= allowed


class PrashnaFacade:
    def __init__(self, *, clock: Callable[[], dt.datetime] | None = None):
        self._clock = clock or (lambda: dt.datetime.now(dt.UTC))

    def _capture(self, place: EventPlace) -> EventAnchor:
        captured = self._clock()  # Exactly once by contract.
        if captured.tzinfo is None or captured.utcoffset() is None:
            raise ValueError("EVENT_TIME_REQUIRED")
        local = captured.astimezone(ZoneInfo(place.zone_id))
        effective_place = place
        if place.fold is None and local.fold:
            effective_place = place.model_copy(update={"fold": local.fold})
        return EventAnchor(
            asked_at=local.isoformat(timespec="microseconds"),
            place=effective_place,
            time_confidence="captured_now",
        )

    def _capture_idempotently(
        self,
        request: PrashnaRequest,
        *,
        fingerprint: str,
        route: TopicRoute,
    ) -> tuple[EventAnchor, str]:
        assert request.place is not None and request.idempotency_key is not None
        identity = sign_facts({
            "mode": "prashna_capture_identity",
            "idempotency_key": request.idempotency_key,
        })
        material_sha256 = _sha({
            "question_fingerprint": fingerprint,
            "place": request.place.model_dump(mode="json"),
            "rule_profile": request.rule_profile,
        })
        with _CAPTURE_LOCK:
            cached = _CAPTURE_CACHE.get(identity)
            if cached is not None:
                if cached.material_sha256 != material_sha256:
                    raise _IdempotencyConflict
                _CAPTURE_CACHE.move_to_end(identity)
                resealed = self._seal_anchor(
                    cached.anchor_data,
                    fingerprint=fingerprint,
                    normalized_question=_normalized_question(request.question),
                    route=route,
                    rule_profile=request.rule_profile,
                )
                return (
                    EventAnchor(
                        asked_at=cached.anchor_data["asked_at"],
                        place=cached.anchor_data["place"],
                        time_confidence=cached.anchor_data["time_confidence"],
                    ),
                    resealed["artifact_token"],
                )
            anchor = self._capture(request.place)
            anchor_data = _anchor_payload(anchor)
            sealed = self._seal_anchor(
                anchor_data,
                fingerprint=fingerprint,
                normalized_question=_normalized_question(request.question),
                route=route,
                rule_profile=request.rule_profile,
            )
            record = _CaptureRecord(material_sha256, anchor_data, sealed["artifact_token"])
            _CAPTURE_CACHE[identity] = record
            _CAPTURE_CACHE.move_to_end(identity)
            while len(_CAPTURE_CACHE) > _CAPTURE_CACHE_MAX:
                _CAPTURE_CACHE.popitem(last=False)
            return anchor, record.anchor_token

    @staticmethod
    def _seal_anchor(
        anchor_data: dict,
        *,
        fingerprint: str,
        normalized_question: str,
        route: TopicRoute,
        rule_profile: str,
    ) -> dict:
        return cache_domain_artifact(
            {
                "mode": "prashna_anchor",
                "normalized_anchor": anchor_data,
                "normalized_anchor_sha256": _sha(anchor_data),
                "question_fingerprint": fingerprint,
                "normalized_question": normalized_question,
                "topic_family": route.family,
                "rule_profile": rule_profile,
                "rule_profile_sha256": prashna_rule_profile_sha256(),
                "config_sha256": _prashna_config_sha256(),
            }
        )

    @staticmethod
    def _rescue(route: TopicRoute, request_id: str) -> PrashnaResult:
        if route.status == "high_stakes":
            return PrashnaUnavailableResult(
                status="unavailable",
                **_error_fields("HIGH_STAKES_TOPIC", request_id=request_id, stage="topic_routing"),
            )
        code = "TOPIC_COMPOSITE" if route.status == "composite" else "TOPIC_UNSUPPORTED"
        return PrashnaNeedsInputResult(
            status="needs_input",
            **_error_fields(code, request_id=request_id, stage="topic_routing"),
        )

    @staticmethod
    def _mismatch(fingerprint: str) -> PrashnaNeedsInputResult:
        return PrashnaNeedsInputResult(
            status="needs_input",
            **_error_fields(
                "ANCHOR_MISMATCH",
                request_id="prq_" + fingerprint[:24],
                stage="anchor_reuse",
            ),
        )

    @staticmethod
    def _stale(fingerprint: str) -> PrashnaNeedsInputResult:
        return PrashnaNeedsInputResult(
            status="needs_input",
            **_error_fields(
                "ANCHOR_STALE",
                request_id="prq_" + fingerprint[:24],
                stage="anchor_replay",
            ),
        )

    def calculate(self, request: PrashnaRequest) -> PrashnaResult:
        current_fingerprint = question_fingerprint(request.question)
        try:
            profile = load_prashna_rule_profile()
            route = route_prashna_topic(request.question, profile)
        except PrashnaGovernanceError:
            return PrashnaUnavailableResult(
                status="unavailable",
                **_error_fields(
                    "GOVERNANCE_INTEGRITY_ERROR",
                    request_id="prq_" + current_fingerprint[:24],
                    stage="governance",
                ),
            )

        if request.anchor_token is None and route.status != "supported":
            return self._rescue(route, "prq_" + current_fingerprint[:24])

        if request.anchor_token is not None:
            sealed = get_cached_domain_artifact(request.anchor_token)
            original_fingerprint = None if sealed is None else str(sealed.get("question_fingerprint", ""))
            exact = current_fingerprint == original_fingerprint
            clarified = bool(
                sealed is not None
                and request.clarification_of_fingerprint == original_fingerprint
                and _provable_clarification(
                    str(sealed.get("normalized_question", "")),
                    _normalized_question(request.question),
                )
            )
            if (
                sealed is None
                or not verify_domain_artifact(sealed)
                or sealed.get("mode") != "prashna_anchor"
                or sealed.get("rule_profile") != request.rule_profile
                or route.status != "supported"
                or route.family != sealed.get("topic_family")
                or not (exact or clarified)
            ):
                return self._mismatch(current_fingerprint)
            anchor_data = sealed["normalized_anchor"]
            try:
                anchor = EventAnchor(
                    asked_at=anchor_data["asked_at"],
                    place=anchor_data["place"],
                    time_confidence=anchor_data["time_confidence"],
                )
                replayed_anchor = _anchor_payload(anchor)
            except ValidationError:
                return self._stale(current_fingerprint)
            if (
                sealed.get("rule_profile_sha256") != prashna_rule_profile_sha256()
                or sealed.get("config_sha256") != _prashna_config_sha256()
                or sealed.get("normalized_anchor_sha256") != _sha(replayed_anchor)
                or anchor_data != replayed_anchor
            ):
                return self._stale(current_fingerprint)
            anchor_data = replayed_anchor
            anchor_token = request.anchor_token
            fingerprint = str(sealed["question_fingerprint"])
            relation = "exact_duplicate" if exact else "bounded_clarification"
        else:
            try:
                if request.anchor is not None:
                    anchor = request.anchor
                    anchor_data = _anchor_payload(anchor)
                    sealed = self._seal_anchor(
                        anchor_data,
                        fingerprint=current_fingerprint,
                        normalized_question=_normalized_question(request.question),
                        route=route,
                        rule_profile=request.rule_profile,
                    )
                    anchor_token = sealed["artifact_token"]
                else:
                    anchor, anchor_token = self._capture_idempotently(
                        request, fingerprint=current_fingerprint, route=route
                    )
            except _IdempotencyConflict:
                return PrashnaNeedsInputResult(
                    status="needs_input",
                    **_error_fields(
                        "IDEMPOTENCY_CONFLICT",
                        request_id="prq_" + current_fingerprint[:24],
                        stage="anchor_capture",
                    ),
                )
            anchor_data = _anchor_payload(anchor)
            fingerprint = current_fingerprint
            relation = "new_anchor"

        anchor_data = _anchor_payload(anchor)
        anchor_hash = _sha(anchor_data)
        request_id = _request_id(fingerprint, anchor_hash)
        if route.status != "supported":
            return self._rescue(route, request_id)
        try:
            return self._calculate_supported(
                request=request,
                anchor=anchor,
                anchor_data=anchor_data,
                anchor_hash=anchor_hash,
                anchor_token=anchor_token,
                fingerprint=fingerprint,
                request_id=request_id,
                route=route,
                rule_profile=profile,
                current_fingerprint=current_fingerprint,
                question_relation=relation,
            )
        except _PrashnaEngineFailure:
            return PrashnaIncompleteResult(
                status="incomplete",
                **_error_fields(
                    "ENGINE_CROSSCHECK_FAILED",
                    request_id=request_id,
                    stage="calculation",
                ),
            )
        except PrashnaGovernanceError:
            return PrashnaUnavailableResult(
                status="unavailable",
                **_error_fields(
                    "GOVERNANCE_INTEGRITY_ERROR",
                    request_id=request_id,
                    stage="governance",
                ),
            )

    def _calculate_supported(
        self,
        *,
        request: PrashnaRequest,
        anchor: EventAnchor,
        anchor_data: dict,
        anchor_hash: str,
        anchor_token: str,
        fingerprint: str,
        request_id: str,
        route: TopicRoute,
        rule_profile: PrashnaRuleProfile,
        current_fingerprint: str,
        question_relation: str,
    ) -> PrashnaCompletedResult:
        resolved = anchor.resolved()
        local = resolved.utc_instant.astimezone(ZoneInfo(anchor.place.zone_id))
        engine_profile = BirthProfile(
            name="event-anchor",
            date=(local.year, local.month, local.day),
            time=(local.hour, local.minute, local.second),
            latitude=anchor.place.latitude,
            longitude=anchor.place.longitude,
            timezone=resolved.offset_minutes / 60,
        )
        try:
            session = _run_engine_session(
                engine_profile,
                (local.year, local.month, local.day),
                CalculationConfig(charts=("D1",)),
                domain_callback=lambda snapshot: snapshot,
            )
        except (ConfigError, EngineOutputError, ArithmeticError) as exc:
            raise _PrashnaEngineFailure from exc
        chart = session.natal["facts"]
        ascendant = chart["ascendant"]
        placements = chart["d1"]
        moon = next(item for item in placements if item["planet"] == "Moon")
        primary = chart["houses"][route.primary_house - 1]  # type: ignore[operator]
        primary_lord = next(item for item in placements if item["planet"] == primary["lord"])
        lagna_lord = chart["houses"][0]["lord"]
        lagna_lord_placement = next(item for item in placements if item["planet"] == lagna_lord)
        panchanga = chart["panchanga"]
        tithi_index = int(panchanga["tithi"]["index"])
        moon_phase = "waxing" if tithi_index <= 15 else "waning"

        facts: list[PrashnaFact] = [
            PrashnaFact(fact_id="prashna.geometry.applying_separating", value="unsupported_by_verified_primitive"),
            PrashnaFact(fact_id="prashna.lagna.degrees", value=ascendant["degrees"]),
            PrashnaFact(fact_id="prashna.lagna.lord", value=lagna_lord),
            PrashnaFact(fact_id="prashna.lagna.lord_house", value=lagna_lord_placement["house"]),
            PrashnaFact(fact_id="prashna.lagna.lord_sign", value=lagna_lord_placement["sign"]),
            PrashnaFact(fact_id="prashna.lagna.method", value="time_chart"),
            PrashnaFact(fact_id="prashna.lagna.sign", value=ascendant["sign"]),
            PrashnaFact(fact_id="prashna.moon.house", value=moon["house"]),
            PrashnaFact(fact_id="prashna.moon.phase", value=moon_phase),
            PrashnaFact(fact_id="prashna.moon.sign", value=moon["sign"]),
            PrashnaFact(fact_id="prashna.topic.family", value=route.family),
            PrashnaFact(fact_id="prashna.topic.primary_house", value=route.primary_house),
            PrashnaFact(fact_id="prashna.topic.primary_lord", value=primary["lord"]),
            PrashnaFact(fact_id="prashna.topic.primary_lord_house", value=primary_lord["house"]),
            PrashnaFact(fact_id="prashna.topic.primary_lord_sign", value=primary_lord["sign"]),
            PrashnaFact(fact_id="prashna.topic.secondary_houses", value=",".join(map(str, route.secondary_houses))),
        ]
        for key in ("weekday", "tithi", "nakshatra", "yoga", "karana"):
            entry = panchanga[key]
            facts.append(PrashnaFact(fact_id=f"prashna.panchanga.{key}", value=entry["name"]))
        occupants: dict[int, list[str]] = {}
        for body in placements:
            occupants.setdefault(body["sign_index"], []).append(body["planet"])
        for house in chart["houses"]:
            facts.extend(
                (
                    PrashnaFact(fact_id=f"prashna.bhava.{house['house']}.sign", value=house["sign"]),
                    PrashnaFact(fact_id=f"prashna.bhava.{house['house']}.lord", value=house["lord"]),
                )
            )
        for sign_index, sign_name in enumerate(names.SIGNS):
            targets = _rasi_drishti(sign_index)
            facts.extend(
                (
                    PrashnaFact(
                        fact_id=f"prashna.rasi_drishti.sign.{sign_name}.signs",
                        value=",".join(names.SIGNS[index] for index in targets),
                    ),
                    PrashnaFact(
                        fact_id=f"prashna.rasi_drishti.sign.{sign_name}.planets",
                        value=",".join(sorted(body for index in targets for body in occupants.get(index, ()))) or "none",
                    ),
                )
            )
        for body in placements:
            planet = body["planet"]
            facts.extend(
                (
                    PrashnaFact(fact_id=f"prashna.planets.{planet}.degrees", value=body["degrees"]),
                    PrashnaFact(fact_id=f"prashna.planets.{planet}.house", value=body["house"]),
                    PrashnaFact(fact_id=f"prashna.planets.{planet}.sign", value=body["sign"]),
                    PrashnaFact(
                        fact_id=f"prashna.rasi_drishti.{planet}.signs",
                        value=",".join(names.SIGNS[index] for index in _rasi_drishti(body["sign_index"])),
                    ),
                )
            )
        for planet, aspect in sorted(chart["aspects"].items()):
            facts.append(
                PrashnaFact(
                    fact_id=f"prashna.graha_drishti.{planet}.houses",
                    value=",".join(map(str, aspect["aspected_houses"])),
                )
            )
        facts.sort(key=lambda item: item.fact_id)

        definitions = {rule.rule_id: rule for rule in rule_profile.rules}

        def evaluated_rule(
            rule_id: str,
            *,
            status: str,
            severity: str,
            inputs: tuple[str, ...],
            outputs: tuple[str, ...],
        ) -> PrashnaRuleResult:
            definition = definitions[rule_id]
            return PrashnaRuleResult(
                rule_id=definition.rule_id,
                version=definition.version,
                status=status,
                severity=severity,
                inputs=inputs,
                outputs=outputs,
                source_status=definition.source_status,
            )

        all_rules = tuple(sorted((
            evaluated_rule(
                "prashna.readability.anchor_complete", status="pass", severity="info",
                inputs=("normalized_utc", "zone_id", "place"), outputs=("sealed",),
            ),
            evaluated_rule(
                "prashna.readability.single_topic", status="pass", severity="info",
                inputs=(route.family or "",), outputs=(f"house_{rule_profile.primary_house}",),
            ),
            evaluated_rule(
                "prashna.geometry.applying_separating", status="not_applicable", severity="warning",
                inputs=(), outputs=("unsupported_by_verified_primitive",),
            ),
            evaluated_rule(
                "prashna.radicality.source_gate", status="not_applicable", severity="warning",
                inputs=(), outputs=("no_admitted_doctrinal_rule",),
            ),
        ), key=lambda item: item.rule_id))
        rules = all_rules[:rule_profile.rule_result_limit]
        source_map = load_prashna_source_map()
        provenance = PrashnaProvenance(
            normalized_utc=anchor_data["normalized_utc"],
            zone_id=anchor_data["zone_id"],
            resolved_offset_minutes=anchor_data["offset_minutes"],
            fold=anchor_data["fold"],
            tzdb_fingerprint=anchor_data["tzdb_fingerprint"],
            engine_version=ENGINE_VERSION,
            ephemeris_mode=session.snapshot.ephemeris_mode,
            rule_profile_sha256=prashna_rule_profile_sha256(),
            source_map_sha256=prashna_source_map_sha256(),
            source_review_status=source_map.review.status,
        )
        source_evidence = prashna_source_admission_evidence()
        fact_payload = [item.model_dump(mode="json") for item in facts]
        rule_payload = [item.model_dump(mode="json") for item in rules]
        artifact = cache_domain_artifact(
            {
                "mode": "prashna",
                "anchor_token": anchor_token,
                "normalized_anchor_sha256": anchor_hash,
                "question_fingerprint": fingerprint,
                "current_question_fingerprint": current_fingerprint,
                "question_relation": question_relation,
                "rule_profile": request.rule_profile,
                "rule_profile_sha256": prashna_rule_profile_sha256(),
                "source_map_sha256": prashna_source_map_sha256(),
                "source_admission_sha256": source_evidence["sha256"],
                "config_sha256": _sha(session.snapshot.config.__dict__),
                "facts": fact_payload,
                "rule_traces": rule_payload,
                "provenance": provenance.model_dump(mode="json"),
            }
        )
        trace = tuple(
            PrashnaFact(fact_id=f"prashna.trace.rule.{index}.status", value=rule.status)
            for index, rule in enumerate(rules)
        ) if request.include_trace else None
        return PrashnaCompletedResult(
            status="completed",
            request_id=request_id,
            anchor_token=anchor_token,
            anchor_summary=f"sealed question moment: {anchor_data['normalized_utc']}; {anchor_data['zone_id']}",
            normalized_anchor_sha256=anchor_hash,
            question_fingerprint=fingerprint,
            current_question_fingerprint=current_fingerprint,
            question_relation=question_relation,
            facts=tuple(facts),
            rules=rules,
            truncation=PrashnaTruncation(
                truncated=len(rules) < len(all_rules),
                total_count=len(all_rules),
                returned_count=len(rules),
            ),
            limitations=(
                "Computed chart and geometry facts only; governed Praśna interpretation is unavailable.",
                "Applying/separating geometry is unavailable because no independently verified primitive is admitted.",
                "Unsupported lagna methods: " + ", ".join(rule_profile.unsupported_lagna_methods) + ".",
                "Captured-now retry idempotency is process-local and bounded to the 256 most recent identities.",
            ),
            provenance=provenance,
            artifact_id=artifact["artifact_id"],
            artifact_sha256=artifact["artifact_sha256"],
            artifact_token=artifact["artifact_token"],
            trace=trace,
        )
