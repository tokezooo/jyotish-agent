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
    AnswerContractV2,
    CorpusReviewRequest,
    CorpusSourceIngest,
    CreateResearchRunRequest,
    FixedOffsetLegacy,
    IanaTimezone,
    IanaWithAssertedOffset,
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
    ResearchReplayResponse,
    ResearchScreenResponse,
    SubmitAnswerRequest,
    TimezoneResolution,
)
from .research_store import ResearchStore, RunNotFound, canonical_json, new_id, sha256_text
from .validation import profile_warnings
from .timezone_resolution import resolve_fixed, resolve_iana
from .timezone_resolution import TimezoneResolutionError, timezone_fingerprint


class UnsupportedTimezoneMode(ValueError):
    pass


class InvalidRunTransition(ValueError):
    pass


class ReplayError(ValueError):
    def __init__(self, error_code: str):
        self.error_code = error_code
        super().__init__(error_code)


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
        civil = dt.datetime.combine(profile.date, profile.time)
        if isinstance(timezone, (int, float, FixedOffsetLegacy)):
            offset_hours = (timezone.offset_hours if isinstance(timezone, FixedOffsetLegacy)
                            else float(timezone))
            resolved = resolve_fixed(civil, offset_hours=offset_hours,
                                     longitude=profile.place.longitude)
        elif isinstance(timezone, (IanaTimezone, IanaWithAssertedOffset)):
            resolved = resolve_iana(
                civil, mode=timezone.kind, zone_id=timezone.zone_id,
                fold=timezone.fold,
                asserted_offset_hours=(timezone.asserted_offset_hours
                    if isinstance(timezone, IanaWithAssertedOffset) else None),
                longitude=profile.place.longitude,
            )
        else:
            raise UnsupportedTimezoneMode("unsupported timezone")
        civil_text = civil.isoformat()
        utc_text = resolved.utc_instant.isoformat().replace("+00:00", "Z")
        reference_date = request.calculation_config.reference_date or now_datetime.date()
        normalized_profile = profile.model_dump(mode="json")
        if isinstance(timezone, (int, float)):
            normalized_profile["place"]["timezone"] = {
                "kind": "fixed_offset_legacy", "offset_hours": offset_hours}
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
            "timezone_resolution_mode": resolved.mode,
            "timezone_zone_id": resolved.zone_id,
            "timezone_fingerprint": resolved.tzdb_fingerprint,
            "timezone_fold": resolved.fold,
            "timezone_warnings": list(resolved.warnings),
            "resolved_offset_minutes": resolved.offset_minutes,
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

    def replay_run(self, run_id: str) -> ResearchReplayResponse:
        """Reconstruct hashes using only immutable/pinned local ledger material."""
        current = self._require_run(run_id)
        rebuilt = self.store.rebuild_run(run_id)
        if canonical_json(current) != canonical_json(rebuilt):
            raise ReplayError("PROJECTION_HASH_MISMATCH")
        if not all(current.get(key) for key in (
            "engine_version", "model_version", "planner_version", "corpus_version",
            "contract_version", "timezone_fingerprint"
        )):
            raise ReplayError("MISSING_PINNED_VERSION")
        plan = self.store.get_question_plan(run_id)
        intent = self.store.get_question_intent(run_id)
        try:
            answers = self.store.list_answers(run_id)
            evidence = self.store.list_evidence(run_id)
            claims = self.store.list_claims(run_id)
        except (ValueError, json.JSONDecodeError):
            raise ReplayError("PINNED_PAYLOAD_HASH_MISMATCH") from None
        if plan is None or intent is None or not answers:
            raise ReplayError("MISSING_PINNED_MATERIAL")
        if current["contract_version"] != "2.0" or plan["plan"].get("schema_version") != 1:
            raise ReplayError("UNSUPPORTED_PINNED_VERSION")
        if plan["planner_version"] != current["planner_version"]:
            raise ReplayError("PINNED_VERSION_MISMATCH")
        events = self.store.list_events(run_id)
        planned_events = [
            json.loads(event["payload_json"])
            for event in events if event["event_type"] == "research_run.planned"
        ]
        if len(planned_events) != 1:
            raise ReplayError("PINNED_PLANNING_MISMATCH")
        planned_result = planned_events[0].get("result", {})
        classifier = planned_result.get("classifier", {})
        if (
            planned_result.get("intent") != intent["intent"]
            or planned_result.get("plan") != plan["plan"]
            or planned_result.get("plan_hash") != plan["plan_hash"]
            or classifier.get("classifier_model") != intent["classifier_model"]
            or classifier.get("classifier_version") != intent["classifier_version"]
            or classifier.get("prompt_hash") != intent["classifier_prompt_hash"]
        ):
            raise ReplayError("PINNED_PLANNING_MISMATCH")
        if sha256_text(canonical_json(planned_result.get("plan"))) != planned_result.get("plan_hash"):
            raise ReplayError("PINNED_PLANNING_MISMATCH")
        if sha256_text(canonical_json(plan["plan"])) != plan["plan_hash"]:
            raise ReplayError("PINNED_PAYLOAD_HASH_MISMATCH")
        if sha256_text(canonical_json(intent["intent"])) != intent["intent_hash"]:
            raise ReplayError("PINNED_PAYLOAD_HASH_MISMATCH")
        self._validate_replay_timezone_material(current)

        supports = self.store.list_claim_supports(run_id)
        attempts = self.store.list_answer_attempts(run_id)
        for row in [*evidence, *answers, *claims]:
            if sha256_text(canonical_json(row["payload"])) != row["payload_hash"]:
                raise ReplayError("PINNED_PAYLOAD_HASH_MISMATCH")
        expected_evidence: set[str] = set()
        expected_answers: set[str] = set()
        expected_attempts: set[str] = set()
        for event in events:
            payload = json.loads(event["payload_json"])
            result = payload.get("result", {})
            if event["event_type"] == "research_run.calculated":
                expected_evidence.update(result.get("evidence_ids", []))
            elif event["event_type"] == "research_run.retrieved":
                expected_evidence.update(
                    item["evidence_id"] for item in result.get("results", [])
                    if item.get("evidence_id")
                )
            elif event["event_type"] == "research_run.answer_submitted" and result.get("answer_id"):
                expected_answers.add(result["answer_id"])
                expected_attempts.add(event["operation_id"])
            elif event["event_type"] == "research_run.answer_submitted":
                expected_attempts.add(event["operation_id"])
        self._require_exact_row_set(expected_evidence,
                                    {row["evidence_id"] for row in evidence})
        self._require_exact_row_set(expected_answers,
                                    {row["answer_id"] for row in answers})
        self._require_exact_row_set(expected_attempts,
                                    {row["attempt_id"] for row in attempts})
        answer_row = answers[-1]
        try:
            answer = AnswerContractV2.model_validate(answer_row["payload"]["contract"])
        except Exception:
            raise ReplayError("UNSUPPORTED_PINNED_VERSION") from None
        valid_attempts = [row for row in attempts if row["valid"]]
        if (len(valid_attempts) != 1
                or valid_attempts[0]["answer_id"] != answer_row["answer_id"]
                or valid_attempts[0]["contract_hash"] != sha256_text(
                    canonical_json(answer.model_dump(mode="json"))
                )):
            raise ReplayError("PINNED_CLAIMS_INVALID")
        violations = validate_answer_contract(
            answer, evidence,
            birth_time_confidence=current["birth_profile"].get("birth_time_confidence", "exact"),
        )
        if violations:
            raise ReplayError("PINNED_CLAIMS_INVALID")
        contract_claims = {
            claim.claim_id: claim.model_dump(mode="json") for claim in answer.claims
        }
        actual_claims = {row["claim_id"]: row["payload"] for row in claims}
        self._require_exact_row_set(set(contract_claims), set(actual_claims))
        if any(actual_claims[key] != value for key, value in contract_claims.items()):
            raise ReplayError("PINNED_CLAIMS_INVALID")
        expected_supports = {
            (claim.claim_id, evidence_id, claim.claim_type)
            for claim in answer.claims if claim.claim_type in {"computed", "source"}
            for evidence_id in claim.supports
        }
        actual_supports = {
            (row["claim_id"], row["evidence_id"], row["support_type"])
            for row in supports
        }
        self._require_exact_row_set(expected_supports, actual_supports)
        rendered = render_answer_markdown(answer, evidence)
        if (rendered.markdown != answer_row["payload"]["markdown"] or
                rendered.sha256 != answer_row["payload"]["markdown_sha256"]):
            raise ReplayError("MEMO_HASH_MISMATCH")
        claims_payload = [claim.model_dump(mode="json") for claim in answer.claims]
        disagreements = [
            {"claim_id": claim.claim_id, "conflicts": list(claim.conflicts)}
            for claim in answer.claims if claim.conflicts
        ]
        return ResearchReplayResponse(
            run_id=run_id, status="replayed",
            projection_hash=sha256_text(canonical_json(rebuilt)),
            claims_hash=sha256_text(canonical_json(claims_payload)),
            memo_hash=rendered.sha256, answer_id=answer_row["answer_id"],
            source_disagreements=disagreements,
        )

    @staticmethod
    def _require_exact_row_set(expected: set, actual: set) -> None:
        if expected - actual:
            raise ReplayError("MISSING_PINNED_MATERIAL")
        if actual - expected:
            raise ReplayError("PINNED_ROW_SET_MISMATCH")

    @staticmethod
    def _validate_replay_timezone_material(run: dict[str, Any]) -> None:
        mode = run["timezone_resolution_mode"]
        if mode == "fixed_offset_legacy":
            if run["timezone_fingerprint"] != "fixed-offset:v1":
                raise ReplayError("PINNED_VERSION_MISMATCH")
            return
        if mode not in {"iana", "iana_with_asserted_offset"}:
            raise ReplayError("UNSUPPORTED_PINNED_VERSION")
        zone_id = run.get("timezone_zone_id")
        if not zone_id:
            raise ReplayError("MISSING_PINNED_MATERIAL")
        try:
            fingerprint = timezone_fingerprint(zone_id)
        except TimezoneResolutionError:
            raise ReplayError("MISSING_PINNED_MATERIAL") from None
        if fingerprint != run["timezone_fingerprint"]:
            raise ReplayError("PINNED_TIMEZONE_MATERIAL_MISMATCH")

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
        persisted_plan = self.store.get_question_plan(run_id)
        if (
            run["status"] != "planned"
            or persisted_plan is None
            or persisted_plan["plan"].get("outcome") != "supported"
        ):
            raise InvalidRunTransition("calculation requires a supported plan")
        if run["revision"] != request.expected_revision:
            raise InvalidRunTransition("expected revision does not match current revision")

        stored_profile = run["birth_profile"]
        profile_input = json.loads(canonical_json(stored_profile))
        profile_input.pop("birth_time_range", None)
        self._apply_resolved_timezone(run, profile_input,
                                      dt.datetime.fromisoformat(run["civil_datetime"]),
                                      validate_pinned=True)
        profile_request = BirthProfileRequest.model_validate(profile_input)
        config_payload = json.loads(canonical_json(run["calculation_config"]))
        plan = persisted_plan["plan"]
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
        sensitivity = []
        confidence = stored_profile.get("birth_time_confidence", "exact")
        if confidence in {"approximate", "unknown"}:
            sensitivity = self._sensitivity_sweep(
                run, profile_input, config_request, plan, calculated["facts"]
            )
            evidence.extend(
                {"evidence_id": new_id("evi_"), "evidence_type": "sensitivity_fact",
                 "payload": item}
                for item in sensitivity
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
            "sensitivity": sensitivity,
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
        violations.extend(validate_answer_contract(
            request.answer, evidence,
            birth_time_confidence=run["birth_profile"].get("birth_time_confidence", "exact"),
        ))
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
    def _sensitivity_sweep(run: dict[str, Any], profile_input: dict[str, Any],
                           config_request: CalculationConfigRequest, plan: dict[str, Any],
                           baseline_facts: dict[str, Any]) -> list[dict[str, Any]]:
        confidence = run["birth_profile"].get("birth_time_confidence")
        if confidence == "approximate":
            offsets = (-15, -10, -5, 0, 5, 10, 15)
        else:
            start, end = run["birth_profile"]["birth_time_range"]
            start_dt = dt.datetime.combine(dt.date.fromisoformat(run["birth_profile"]["date"]), dt.time.fromisoformat(start))
            end_dt = dt.datetime.combine(start_dt.date(), dt.time.fromisoformat(end))
            center = dt.datetime.combine(start_dt.date(), dt.time.fromisoformat(run["birth_profile"]["time"]))
            offsets = tuple(range(int((start_dt-center).total_seconds()/60), int((end_dt-center).total_seconds()/60)+1, 5))
            if offsets[-1] != int((end_dt-center).total_seconds()/60):
                offsets += (int((end_dt-center).total_seconds()/60),)
        reference = (config_request.reference_date.year, config_request.reference_date.month,
                     config_request.reference_date.day)
        base_dt = dt.datetime.fromisoformat(run["civil_datetime"])
        samples: dict[int, dict[str, str]] = {}
        baseline_atoms = iter_fact_atoms(baseline_facts)
        for offset in offsets:
            if offset == 0:
                atoms = baseline_atoms
            else:
                shifted = base_dt + dt.timedelta(minutes=offset)
                payload = json.loads(canonical_json(profile_input))
                payload["date"], payload["time"] = shifted.date().isoformat(), shifted.time().isoformat()
                ResearchService._apply_resolved_timezone(run, payload, shifted)
                request = BirthProfileRequest.model_validate(payload)
                result = compute_chart(request.to_birth_profile(), reference_date=reference,
                                       config=config_request.to_calculation_config())
                atoms = iter_fact_atoms(result["facts"])
            samples[offset] = atoms
        selected = sorted(path for path in set().union(*(set(v) for v in samples.values()))
                          if any(path.startswith(prefix) for prefix in plan["fact_paths"]))
        return [
            {"path": path, "stability": "stable" if len({samples[o].get(path) for o in offsets}) == 1 else "unstable",
             "offsets_minutes": list(offsets),
             "values": [{"offset_minutes": o, "value": samples[o].get(path)} for o in offsets]}
            for path in selected
        ]

    @staticmethod
    def _apply_resolved_timezone(run: dict[str, Any], payload: dict[str, Any],
                                 civil: dt.datetime, *, validate_pinned: bool = False) -> None:
        spec = run["birth_profile"]["place"]["timezone"]
        if isinstance(spec, dict) and spec.get("kind") in {"iana", "iana_with_asserted_offset"}:
            resolved = resolve_iana(
                civil, mode=spec["kind"], zone_id=spec["zone_id"],
                fold=spec.get("fold"),
                asserted_offset_hours=spec.get("asserted_offset_hours"),
                longitude=run["birth_profile"]["place"]["longitude"],
                expected_fingerprint=run.get("timezone_fingerprint"),
            )
            utc_text = resolved.utc_instant.isoformat().replace("+00:00", "Z")
            if validate_pinned and (
                resolved.offset_minutes != run["resolved_offset_minutes"]
                or resolved.fold != run.get("timezone_fold", 0)
                or utc_text != run["utc_instant"]
            ):
                raise TimezoneResolutionError("TIMEZONE_RESOLUTION_MISMATCH")
            payload["place"]["timezone"] = resolved.offset_minutes / 60
        else:
            payload["place"]["timezone"] = run["resolved_offset_minutes"] / 60

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
                zone_id=run.get("timezone_zone_id"),
                tzdb_fingerprint=run.get("timezone_fingerprint", "fixed-offset:v1"),
                resolved_offset_minutes=run["resolved_offset_minutes"],
                utc_instant=run["utc_instant"],
                fold=run.get("timezone_fold", 0),
                warnings=run.get("timezone_warnings", []),
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
