"""ResearchRun domain normalization over the authoritative SQLite store."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from typing import Any

from . import ENGINE, ENGINE_VERSION
from .research_models import (
    CreateResearchRunRequest,
    FixedOffsetLegacy,
    ResearchEventsResponse,
    ResearchRunResponse,
    TimezoneResolution,
)
from .research_store import ResearchStore, RunNotFound, canonical_json, new_id, sha256_text


class UnsupportedTimezoneMode(ValueError):
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
