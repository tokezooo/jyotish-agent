"""ResearchRun domain normalization over the authoritative SQLite store."""

from __future__ import annotations

import datetime as dt
import json
import math
import re
from collections.abc import Callable
from typing import Any

from . import ENGINE, ENGINE_VERSION
from .interpretations import iter_fact_atoms, redirect_message, screen_question
from .models import BirthProfileRequest, CalculationConfigRequest
from .pyjhora_facade import compute_chart
from .research_models import (
    CreateResearchRunRequest,
    FixedOffsetLegacy,
    ResearchCalculationResponse,
    ResearchEventsResponse,
    ResearchOperationRequest,
    ResearchRunResponse,
    ResearchScreenResponse,
    TimezoneResolution,
)
from .research_store import ResearchStore, RunNotFound, canonical_json, new_id, sha256_text
from .validation import profile_warnings


class UnsupportedTimezoneMode(ValueError):
    pass


class InvalidRunTransition(ValueError):
    pass


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class ResearchService:
    def __init__(
        self,
        store: ResearchStore,
        *,
        clock: Callable[[], dt.datetime] = _utc_now,
    ):
        self.store = store
        self.clock = clock

    def create_run(self, request: CreateResearchRunRequest) -> ResearchRunResponse:
        now_datetime = self.clock().astimezone(dt.UTC)
        profile = request.birth_profile
        timezone = profile.place.timezone
        if isinstance(timezone, (int, float)):
            offset_hours = float(timezone)
        elif isinstance(timezone, FixedOffsetLegacy):
            offset_hours = timezone.offset_hours
        else:
            raise UnsupportedTimezoneMode(
                "Task 1 executes fixed_offset_legacy timezone resolution only"
            )
        offset_minutes_float = offset_hours * 60
        offset_minutes = round(offset_minutes_float)
        if abs(offset_minutes_float - offset_minutes) > 1e-9:
            raise UnsupportedTimezoneMode("fixed offset must resolve to whole minutes")

        civil = dt.datetime.combine(profile.date, profile.time)
        utc = (civil - dt.timedelta(minutes=offset_minutes)).replace(tzinfo=dt.UTC)
        civil_text = civil.isoformat()
        utc_text = utc.isoformat().replace("+00:00", "Z")
        reference_date = request.calculation_config.reference_date or now_datetime.date()
        normalized_profile = profile.model_dump(mode="json")
        normalized_profile["place"]["timezone"] = {
            "kind": "fixed_offset_legacy",
            "offset_hours": offset_hours,
        }
        normalized_request = request.model_dump(
            mode="json", exclude={"operation_id", "expected_revision"}
        )
        normalized_request["birth_profile"] = normalized_profile
        normalized_request["calculation_config"]["reference_date"] = reference_date.isoformat()
        request_hash = sha256_text(canonical_json(normalized_request))
        now = now_datetime.isoformat().replace("+00:00", "Z")
        stored = {
            "run_id": new_id("rr_"),
            "revision": 1,
            "status": "created",
            "question": request.question,
            "birth_profile": normalized_profile,
            "calculation_config": normalized_request["calculation_config"],
            "reference_date": reference_date.isoformat(),
            "civil_datetime": civil_text,
            "timezone_resolution_mode": "fixed_offset_legacy",
            "resolved_offset_minutes": offset_minutes,
            "utc_instant": utc_text,
            "engine_name": ENGINE,
            "engine_version": ENGINE_VERSION,
            "model_version": request.model_version,
            "planner_version": request.planner_version,
            "corpus_version": request.corpus_version,
            "contract_version": request.contract_version,
            "request_hash": request_hash,
            "created_at": now,
            "updated_at": now,
        }
        persisted = self.store.create_run(
            stored,
            operation_id=request.operation_id,
            expected_revision=request.expected_revision,
        )
        return self._response(persisted)

    def get_run(self, run_id: str) -> ResearchRunResponse:
        run = self.store.get_run(run_id)
        if run is None:
            raise RunNotFound(run_id)
        return self._response(run)

    def get_events(self, run_id: str) -> ResearchEventsResponse:
        if self.store.get_run(run_id) is None:
            raise RunNotFound(run_id)
        events: list[dict[str, Any]] = []
        for row in self.store.list_events(run_id):
            event = {key: value for key, value in row.items() if key != "payload_json"}
            event["payload"] = json.loads(row["payload_json"])
            events.append(event)
        return ResearchEventsResponse(events=events)

    def screen_run(
        self, run_id: str, request: ResearchOperationRequest
    ) -> ResearchScreenResponse:
        operation = self._prior_operation(
            run_id=run_id,
            request=request,
            event_type="research_run.screened",
        )
        if operation is not None:
            return ResearchScreenResponse(**operation)

        run = self._require_run(run_id)
        if run["status"] != "created":
            raise InvalidRunTransition("only a created run can be screened")

        category = screen_question(run["question"])
        safe = category is None
        status = "screened_safe" if safe else "refused_unsafe"
        result = {
            "run_id": run_id,
            "operation_id": request.operation_id,
            "status": status,
            "safe": safe,
            "category": category.value if category else None,
            "redirect": redirect_message(category) if category else None,
        }
        event, revision = self.store.append_event(
            run_id,
            operation_id=request.operation_id,
            expected_revision=request.expected_revision,
            event_type="research_run.screened",
            payload={"status": status, "result": result},
            request_payload={},
            next_status=status,
            producer="jyotish-agent",
            producer_version=ENGINE_VERSION,
        )
        return ResearchScreenResponse(**self._operation_response(event, revision))

    def calculate_run(
        self, run_id: str, request: ResearchOperationRequest
    ) -> ResearchCalculationResponse:
        prior = self._prior_operation(
            run_id=run_id,
            request=request,
            event_type="research_run.calculated",
        )
        if prior is not None:
            return ResearchCalculationResponse(**prior)

        run = self._require_run(run_id)
        if run["status"] != "screened_safe":
            raise InvalidRunTransition("calculation requires a safely screened run")
        if run["revision"] != request.expected_revision:
            raise InvalidRunTransition("expected revision does not match current revision")

        stored_profile = run["birth_profile"]
        profile_input = json.loads(canonical_json(stored_profile))
        profile_input["place"]["timezone"] = run["resolved_offset_minutes"] / 60
        profile_request = BirthProfileRequest.model_validate(profile_input)
        config_request = CalculationConfigRequest.model_validate(run["calculation_config"])
        reference = (
            config_request.reference_date.year,
            config_request.reference_date.month,
            config_request.reference_date.day,
        )
        calculated = compute_chart(
            profile_request.to_birth_profile(),
            reference_date=reference,
            config=config_request.to_calculation_config(),
        )
        evidence = self._computed_evidence(run, calculated["facts"])
        evidence_ids = [item["evidence_id"] for item in evidence]
        result = {
            "run_id": run_id,
            "operation_id": request.operation_id,
            "status": "calculated",
            "normalized_input": calculated["normalized_input"],
            "calculation_config": calculated["calculation_config"],
            "facts": calculated["facts"],
            "provenance": calculated["provenance"],
            "warnings": profile_warnings(profile_request),
            "evidence_ids": evidence_ids,
        }
        event, revision = self.store.append_event(
            run_id,
            operation_id=request.operation_id,
            expected_revision=request.expected_revision,
            event_type="research_run.calculated",
            payload={"status": "calculated", "result": result},
            request_payload={},
            next_status="calculated",
            evidence_items=evidence,
            producer="jyotish-agent",
            producer_version=ENGINE_VERSION,
        )
        return ResearchCalculationResponse(**self._operation_response(event, revision))

    def _prior_operation(
        self,
        *,
        run_id: str,
        request: ResearchOperationRequest,
        event_type: str,
    ) -> dict[str, Any] | None:
        prior = self.store.get_operation_result(
            operation_id=request.operation_id,
            run_id=run_id,
            expected_revision=request.expected_revision,
            event_type=event_type,
            request_payload={},
            producer="jyotish-agent",
            producer_version=ENGINE_VERSION,
        )
        if prior is None:
            return None
        event, revision = prior
        return self._operation_response(event, revision)

    def _require_run(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        if run is None:
            raise RunNotFound(run_id)
        return run

    @staticmethod
    def _operation_response(event: dict[str, Any], revision: int) -> dict[str, Any]:
        payload = json.loads(event["payload_json"])
        return {
            **payload["result"],
            "revision": revision,
            "backend_seq": event["seq"],
            "event_hash": event["event_hash"],
        }

    @staticmethod
    def _computed_evidence(run: dict[str, Any], facts: dict) -> list[dict[str, Any]]:
        profile_hash = sha256_text(canonical_json(run["birth_profile"]))
        config_hash = sha256_text(canonical_json(run["calculation_config"]))
        engine_hash = sha256_text(
            canonical_json({"name": run["engine_name"], "version": run["engine_version"]})
        )
        result = []
        for path, canonical_value in sorted(iter_fact_atoms(facts).items()):
            value, value_type = _typed_fact_value(canonical_value)
            result.append(
                {
                    "evidence_id": new_id("evi_"),
                    "evidence_type": "computed_fact",
                    "payload": {
                        "path": path,
                        "value": value,
                        "value_type": value_type,
                        "profile_hash": profile_hash,
                        "config_hash": config_hash,
                        "engine_hash": engine_hash,
                    },
                }
            )
        return result

    @staticmethod
    def _response(run: dict[str, Any]) -> ResearchRunResponse:
        return ResearchRunResponse(
            run_id=run["run_id"],
            revision=run["revision"],
            status=run["status"],
            question=run["question"],
            birth_profile=run["birth_profile"],
            calculation_config=run["calculation_config"],
            reference_date=run["reference_date"],
            timezone_resolution=TimezoneResolution(
                original_civil_datetime=run["civil_datetime"],
                mode=run["timezone_resolution_mode"],
                resolved_offset_minutes=run["resolved_offset_minutes"],
                utc_instant=run["utc_instant"],
            ),
            engine_name=run["engine_name"],
            engine_version=run["engine_version"],
            model_version=run["model_version"],
            planner_version=run["planner_version"],
            corpus_version=run["corpus_version"],
            contract_version=run["contract_version"],
            request_hash=run["request_hash"],
            created_at=run["created_at"],
            updated_at=run["updated_at"],
        )


_INTEGER = re.compile(r"^-?(?:0|[1-9]\d*)$")
_NUMBER = re.compile(
    r"^-?(?:(?:0|[1-9]\d*)(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?$"
)


def _typed_fact_value(value: str) -> tuple[str | int | float | bool, str]:
    if value == "true":
        return True, "boolean"
    if value == "false":
        return False, "boolean"
    if _INTEGER.fullmatch(value):
        return int(value), "integer"
    if _NUMBER.fullmatch(value):
        number = float(value)
        if math.isfinite(number):
            return number, "number"
    return value, "string"
