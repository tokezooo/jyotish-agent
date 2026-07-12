"""ResearchRun domain normalization over the authoritative SQLite store."""

from __future__ import annotations

import datetime as dt
import json
import math
import re
from collections.abc import Callable
from typing import Any

from . import ENGINE, ENGINE_VERSION
from .answer_contract import render_answer_markdown, validate_answer_contract
from .interpretations import iter_fact_atoms, redirect_message, screen_question
from .models import BirthProfileRequest, CalculationConfigRequest
from .pyjhora_facade import compute_chart
from .research_models import (
    CorpusFragmentsIngestRequest,
    CorpusReviewRequest,
    CorpusSourceIngest,
    CreateResearchRunRequest,
    FixedOffsetLegacy,
    PlanResearchRunRequest,
    ResearchPlanResponse,
    ResearchRetrievalResponse,
    RetrievedCorpusFragment,
    RetrieveResearchRunRequest,
    ResearchCalculationResponse,
    ResearchAnswerResponse,
    ResearchEventsResponse,
    ResearchOperationRequest,
    ResearchRunResponse,
    ResearchScreenResponse,
    SubmitAnswerRequest,
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
            mode="json",
            exclude={"operation_id", "expected_revision"},
            exclude_none=True,
        )
        normalized_request["birth_profile"] = normalized_profile
        normalized_request["calculation_config"]["reference_date"] = reference_date.isoformat()
        request_hash = sha256_text(canonical_json(normalized_request))
        now = now_datetime.isoformat().replace("+00:00", "Z")
        stored = {
            "run_id": request.run_id or new_id("rr_"),
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
        if run["status"] not in {"screened_safe", "planned"}:
            raise InvalidRunTransition("calculation requires a safely screened run")
        if run["revision"] != request.expected_revision:
            raise InvalidRunTransition("expected revision does not match current revision")

        stored_profile = run["birth_profile"]
        profile_input = json.loads(canonical_json(stored_profile))
        profile_input["place"]["timezone"] = run["resolved_offset_minutes"] / 60
        profile_request = BirthProfileRequest.model_validate(profile_input)
        config_payload = json.loads(canonical_json(run["calculation_config"]))
        if run["status"] == "planned":
            persisted_plan = self.store.get_question_plan(run_id)
            if persisted_plan is None:
                raise InvalidRunTransition("planned run is missing its persisted plan")
            plan = persisted_plan["plan"]
            if plan.get("outcome") != "supported":
                raise InvalidRunTransition("only a supported plan can be calculated")
            config_payload["charts"] = plan["charts"]
            config_payload["modules"] = plan["modules"]
        config_request = CalculationConfigRequest.model_validate(config_payload)
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
        evidence = self._computed_evidence(
            run, calculated["facts"], calculated["calculation_config"]
        )
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

    def plan_run(
        self, run_id: str, request: PlanResearchRunRequest
    ) -> ResearchPlanResponse:
        from .planner import build_question_plan, question_plan_bytes

        request_payload = {
            "intent": request.intent.model_dump(mode="json"),
            "classifier": request.classifier.model_dump(mode="json"),
        }
        prior = self.store.get_operation_result(
            operation_id=request.operation_id,
            run_id=run_id,
            expected_revision=request.expected_revision,
            event_type="research_run.planned",
            request_payload=request_payload,
            producer="jyotish-agent",
            producer_version=ENGINE_VERSION,
        )
        if prior is not None:
            event, revision = prior
            return ResearchPlanResponse(**self._operation_response(event, revision))

        run = self._require_run(run_id)
        if run["status"] != "screened_safe":
            raise InvalidRunTransition("planning requires a safely screened run")
        if run["revision"] != request.expected_revision:
            raise InvalidRunTransition("expected revision does not match current revision")

        plan = build_question_plan(request.intent)
        plan_hash = sha256_text(question_plan_bytes(plan).decode("utf-8"))
        status = {
            "supported": "planned",
            "needs_clarification": "plan_needs_clarification",
            "unsupported": "plan_unsupported",
        }[plan.outcome]
        result = {
            "run_id": run_id,
            "operation_id": request.operation_id,
            "status": status,
            "intent": request.intent.model_dump(mode="json"),
            "classifier": request.classifier.model_dump(mode="json"),
            "plan": plan.model_dump(mode="json"),
            "plan_hash": plan_hash,
        }
        event, revision = self.store.append_event(
            run_id,
            operation_id=request.operation_id,
            expected_revision=request.expected_revision,
            event_type="research_run.planned",
            payload={"status": status, "result": result},
            request_payload=request_payload,
            next_status=status,
            planning_record={
                "intent": request.intent.model_dump(mode="json"),
                "classifier_model": request.classifier.classifier_model,
                "classifier_version": request.classifier.classifier_version,
                "classifier_prompt_hash": request.classifier.prompt_hash,
                "plan": plan.model_dump(mode="json"),
                "plan_hash": plan_hash,
                "planner_version": run["planner_version"],
            },
            producer="jyotish-agent",
            producer_version=ENGINE_VERSION,
        )
        return ResearchPlanResponse(**self._operation_response(event, revision))

    def retrieve_run(
        self, run_id: str, request: RetrieveResearchRunRequest
    ) -> ResearchRetrievalResponse:
        request_payload = {"query": request.query, "limit": request.limit}
        prior = self.store.get_operation_result(
            operation_id=request.operation_id,
            run_id=run_id,
            expected_revision=request.expected_revision,
            event_type="research_run.retrieved",
            request_payload=request_payload,
            producer="jyotish-agent",
            producer_version=ENGINE_VERSION,
        )
        if prior is not None:
            event, revision = prior
            return ResearchRetrievalResponse(**self._operation_response(event, revision))
        run = self._require_run(run_id)
        plan = self.store.get_question_plan(run_id)
        if (
            run["status"] not in {"planned", "calculated"}
            or plan is None
            or plan["plan"].get("outcome") != "supported"
        ):
            raise InvalidRunTransition("retrieval requires a supported plan")
        if run["revision"] != request.expected_revision:
            raise InvalidRunTransition("expected revision does not match current revision")
        found = self.search_corpus(request.query, limit=request.limit)
        results = []
        evidence = []
        for item in found:
            evidence_id = "evi_" + sha256_text(
                canonical_json(
                    {
                        "run_id": run_id,
                        "operation_id": request.operation_id,
                        "fragment_id": item.fragment_id,
                    }
                )
            )[:32]
            item = item.model_copy(update={"evidence_id": evidence_id})
            results.append(item)
            payload = item.model_dump(mode="json")
            evidence.append(
                {
                    "evidence_id": evidence_id,
                    "evidence_type": "source_fragment",
                    "payload": payload,
                }
            )
        result = {
            "run_id": run_id,
            "operation_id": request.operation_id,
            "status": run["status"],
            "query": request.query,
            "results": [item.model_dump(mode="json") for item in results],
        }
        event, revision = self.store.append_event(
            run_id,
            operation_id=request.operation_id,
            expected_revision=request.expected_revision,
            event_type="research_run.retrieved",
            payload={"status": run["status"], "result": result},
            request_payload=request_payload,
            next_status=run["status"],
            evidence_items=evidence,
            producer="jyotish-agent",
            producer_version=ENGINE_VERSION,
        )
        return ResearchRetrievalResponse(**self._operation_response(event, revision))

    def ingest_source(self, source: CorpusSourceIngest) -> dict[str, Any]:
        return self.store.ingest_source_version(
            source.model_dump(
                mode="json", exclude={"operation_id", "expected_revision"}
            ),
            operation_id=source.operation_id,
            expected_revision=source.expected_revision,
        )

    def ingest_fragments(
        self, source_version_id: str, request: CorpusFragmentsIngestRequest
    ) -> dict[str, Any]:
        return self.store.ingest_source_fragments(
            source_version_id,
            [fragment.model_dump(mode="json") for fragment in request.fragments],
            operation_id=request.operation_id,
            expected_revision=request.expected_revision,
        )

    def review_source(
        self, source_version_id: str, review: CorpusReviewRequest
    ) -> dict[str, Any]:
        return self.store.review_source_version(
            source_version_id,
            review.model_dump(
                mode="json", exclude={"operation_id", "expected_revision"}
            ),
            operation_id=review.operation_id,
            expected_revision=review.expected_revision,
        )

    def review_fragment(
        self, fragment_id: str, review: CorpusReviewRequest
    ) -> dict[str, Any]:
        return self.store.review_source_fragment(
            fragment_id,
            review.model_dump(
                mode="json", exclude={"operation_id", "expected_revision"}
            ),
            operation_id=review.operation_id,
            expected_revision=review.expected_revision,
        )

    def search_corpus(self, query: str, *, limit: int) -> list[RetrievedCorpusFragment]:
        return [
            RetrievedCorpusFragment.model_validate(row)
            for row in self.store.search_approved_fragments(query, limit=limit)
        ]

    def submit_answer(
        self, run_id: str, request: SubmitAnswerRequest
    ) -> ResearchAnswerResponse:
        request_payload = {"answer": request.answer.model_dump(mode="json")}
        prior = self.store.get_operation_result(
            operation_id=request.operation_id,
            run_id=run_id,
            expected_revision=request.expected_revision,
            event_type="research_run.answer_submitted",
            request_payload=request_payload,
            producer="jyotish-agent",
            producer_version=ENGINE_VERSION,
        )
        if prior is not None:
            event, revision = prior
            return ResearchAnswerResponse(**self._operation_response(event, revision))

        run = self._require_run(run_id)
        if run["status"] not in {"calculated", "answer_needs_repair"}:
            raise InvalidRunTransition(
                "answers require a calculated run with repair budget remaining"
            )
        if run["revision"] != request.expected_revision:
            raise InvalidRunTransition("expected revision does not match current revision")
        prior_attempts = self.store.list_answer_attempts(run_id)
        if len(prior_attempts) >= 2:
            raise InvalidRunTransition("answer repair budget is exhausted")

        evidence = self.store.list_evidence(run_id)
        violations = []
        if request.answer.run_status != run["status"]:
            violations.append("answer run_status does not match authoritative run status")
        violations.extend(validate_answer_contract(request.answer, evidence))
        violations = list(dict.fromkeys(violations))
        valid = not violations
        attempt_no = len(prior_attempts) + 1
        repair_remaining = max(0, 2 - attempt_no)
        answer_id = new_id("ans_") if valid else None
        rendered = render_answer_markdown(request.answer, evidence) if valid else None
        status = (
            "validated"
            if valid
            else "answer_needs_repair"
            if repair_remaining
            else "answer_repair_exhausted"
        )
        result = {
            "run_id": run_id,
            "operation_id": request.operation_id,
            "status": status,
            "valid": valid,
            "violations": violations,
            "repair_remaining": repair_remaining,
            "answer_id": answer_id,
            "markdown": rendered.markdown if rendered else None,
            "markdown_sha256": rendered.sha256 if rendered else None,
        }
        contract_payload = request.answer.model_dump(mode="json")
        answer_record = None
        claim_records = []
        claim_supports = []
        if valid and answer_id and rendered:
            answer_record = {
                "answer_id": answer_id,
                "schema_version": request.answer.schema_version,
                "payload": {
                    "contract": contract_payload,
                    "markdown": rendered.markdown,
                    "markdown_sha256": rendered.sha256,
                },
            }
            for claim in request.answer.claims:
                claim_records.append(
                    {
                        "claim_id": claim.claim_id,
                        "claim_type": claim.claim_type,
                        "payload": claim.model_dump(mode="json"),
                    }
                )
                if claim.claim_type in {"computed", "source"}:
                    claim_supports.extend(
                        {
                            "claim_id": claim.claim_id,
                            "evidence_id": support,
                            "support_type": claim.claim_type,
                        }
                        for support in claim.supports
                    )
        event, revision = self.store.append_event(
            run_id,
            operation_id=request.operation_id,
            expected_revision=request.expected_revision,
            event_type="research_run.answer_submitted",
            payload={"status": status, "result": result},
            request_payload=request_payload,
            next_status=status,
            answer_attempt={
                "attempt_id": request.operation_id,
                "attempt_no": attempt_no,
                "contract_hash": sha256_text(canonical_json(contract_payload)),
                "valid": valid,
                "violations": violations,
                "answer_id": answer_id,
            },
            answer_record=answer_record,
            claim_records=claim_records,
            claim_supports=claim_supports,
            producer="jyotish-agent",
            producer_version=ENGINE_VERSION,
        )
        return ResearchAnswerResponse(**self._operation_response(event, revision))

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
    def _computed_evidence(
        run: dict[str, Any], facts: dict, calculation_config: dict[str, Any]
    ) -> list[dict[str, Any]]:
        profile_hash = sha256_text(canonical_json(run["birth_profile"]))
        config_hash = sha256_text(canonical_json(calculation_config))
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
