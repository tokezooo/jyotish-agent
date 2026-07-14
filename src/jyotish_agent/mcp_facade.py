"""Codex-facing facade: stateless quick tools and optional deep ResearchRuns."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Callable

from .hardening import reject_symlink_ancestors
from .jaimini import JaiminiFacade
from .jaimini_models import (
    ApproximateJaiminiBirthInput,
    ExactJaiminiBirthInput,
    JaiminiInput,
    JaiminiPlace,
    JaiminiResult,
)
from .prashna import PrashnaFacade
from .prashna_models import PrashnaResult
from .mcp_models import (
    CalculateInput,
    CalculateResult,
    FinalizedResearch,
    FinalizeResearchInput,
    InspectResearchInput,
    JaiminiMcpInput,
    PrashnaMcpInput,
    ProfileInput,
    ProfileResult,
    ResearchBundle,
    ResearchInput,
    ResearchInspection,
    SourceSearchInput,
    SourceSearchResult,
)
from .models import BirthProfileRequest, CalculationConfigRequest
from .pyjhora_facade import compute_chart
from .research_models import (
    AnswerContractV2,
    ClassifierMetadata,
    ComputedClaim,
    CreateResearchRunRequest,
    FixedOffsetLegacy,
    IanaTimezone,
    IanaWithAssertedOffset,
    PlanResearchRunRequest,
    QuestionIntent,
    ResearchBirthProfileRequest,
    ResearchOperationRequest,
    RetrieveResearchRunRequest,
    SourceClaim,
    SubmitAnswerRequest,
    SynthesisClaim,
)
from .research_service import ResearchService
from .research_store import ResearchStore, new_id, sha256_text
from .timezone_resolution import resolve_fixed, resolve_iana
from .validation import profile_warnings


class McpFacadeError(ValueError):
    """Stable public MCP error without private input content."""


_CAREER_HOUSES = {"1", "2", "6", "10", "11"}


def _material_fact_path(path: str) -> bool:
    """Keep a bounded, useful MCP view while the ledger retains every fact."""
    parts = path.split(".")
    if path in {"ascendant.sign", "panchanga.nakshatra"}:
        return True
    if path.startswith(("lagnas.", "vimshottari.")):
        return True
    if parts[0] in {"d1", "d9", "d10"}:
        return len(parts) == 3 and parts[-1] in {"sign", "house"}
    if parts[0] == "houses":
        return len(parts) == 3 and parts[1] in _CAREER_HOUSES
    if parts[0] == "shadbala":
        return parts[-1] == "strength_ratio"
    if parts[0] == "transits":
        return parts[-1] in {"sign", "house_from_lagna", "sav_points"}
    if path.startswith("ashtakavarga.sav."):
        return True
    return False


def compact_research_evidence(
    evidence: list[dict],
) -> dict[str, dict[str, object]]:
    """Project full ledger evidence into a bounded model-facing bundle."""
    facts: dict[str, dict[str, object]] = {}
    for item in evidence:
        payload = item["payload"]
        if item["evidence_type"] == "computed_fact":
            path = payload.get("path")
            if not isinstance(path, str) or not _material_fact_path(path):
                continue
            facts[path] = {
                "value": payload.get("value"),
                "evidence_id": item["evidence_id"],
            }
    return facts


def _compact_sources(results: list) -> list[dict]:
    fields = {
        "evidence_id",
        "fragment_id",
        "source_version_id",
        "work_id",
        "title",
        "source_class",
        "locator",
        "quote",
        "checksum",
        "content_role",
    }
    return [
        {
            key: value
            for key, value in item.model_dump(mode="json").items()
            if key in fields
        }
        for item in results
    ]


class JyotishMcpFacade:
    def __init__(
        self,
        data_root: Path,
        default_profile_path: Path | None,
        *,
        clock: Callable[[], dt.datetime] | None = None,
    ):
        self.data_root = Path(data_root)
        self.default_profile_path = (
            Path(default_profile_path) if default_profile_path is not None else None
        )
        self.store = ResearchStore(self.data_root)
        self.clock = clock or (lambda: dt.datetime.now(dt.UTC))
        service_kwargs = {"clock": clock} if clock is not None else {}
        self.service = ResearchService(self.store, **service_kwargs)

    def _default_profile(self) -> ResearchBirthProfileRequest:
        path = self.default_profile_path
        if path is None or not path.exists():
            raise McpFacadeError("DEFAULT_PROFILE_MISSING")
        try:
            reject_symlink_ancestors(path)
            if path.is_symlink() or not path.is_file():
                raise ValueError("not a private regular file")
            if path.stat().st_mode & 0o077:
                raise McpFacadeError("PRIVATE_PROFILE_PERMISSIONS")
            payload = json.loads(path.read_text(encoding="utf-8"))
            return ResearchBirthProfileRequest.model_validate(payload)
        except McpFacadeError:
            raise
        except Exception as exc:
            raise McpFacadeError("DEFAULT_PROFILE_INVALID") from exc

    def _select_profile(self, value: ProfileInput | CalculateInput | ResearchInput) -> ResearchBirthProfileRequest:
        if value.profile == "inline":
            if value.inline_profile is None:
                raise McpFacadeError("INLINE_PROFILE_REQUIRED")
            return value.inline_profile
        if value.inline_profile is not None:
            raise McpFacadeError("INLINE_PROFILE_REQUIRES_INLINE_MODE")
        return self._default_profile()

    def get_profile(self, value: ProfileInput) -> ProfileResult:
        profile = self._select_profile(value)
        return ProfileResult(
            source=value.profile,
            profile=profile.model_dump(mode="json"),
        )

    @staticmethod
    def _calculation_profile(
        profile: ResearchBirthProfileRequest,
    ) -> BirthProfileRequest:
        civil = dt.datetime.combine(profile.date, profile.time)
        timezone = profile.place.timezone
        if isinstance(timezone, (int, float, FixedOffsetLegacy)):
            offset = timezone.offset_hours if isinstance(timezone, FixedOffsetLegacy) else float(timezone)
            resolved = resolve_fixed(civil, offset_hours=offset, longitude=profile.place.longitude)
        elif isinstance(timezone, (IanaTimezone, IanaWithAssertedOffset)):
            resolved = resolve_iana(
                civil,
                mode=timezone.kind,
                zone_id=timezone.zone_id,
                fold=timezone.fold,
                asserted_offset_hours=(
                    timezone.asserted_offset_hours
                    if isinstance(timezone, IanaWithAssertedOffset)
                    else None
                ),
                longitude=profile.place.longitude,
            )
        else:  # pragma: no cover - discriminated union is exhaustive
            raise McpFacadeError("TIMEZONE_INVALID")
        return BirthProfileRequest.model_validate(
            {
                "name": profile.name,
                "date": profile.date,
                "time": profile.time,
                "birth_time_confidence": profile.birth_time_confidence,
                "place": {
                    "name": profile.place.name,
                    "latitude": profile.place.latitude,
                    "longitude": profile.place.longitude,
                    "timezone": resolved.offset_minutes / 60,
                },
            }
        )

    def calculate(self, value: CalculateInput) -> CalculateResult:
        profile = self._select_profile(value)
        calculation_profile = self._calculation_profile(profile)
        config = CalculationConfigRequest(
            charts=list(dict.fromkeys(value.charts)),
            modules=list(dict.fromkeys(value.modules)),
            reference_date=value.reference_date,
        )
        reference_date = value.reference_date or dt.datetime.now(dt.UTC).date()
        calculated = compute_chart(
            calculation_profile.to_birth_profile(),
            reference_date=(reference_date.year, reference_date.month, reference_date.day),
            config=config.to_calculation_config(),
        )
        return CalculateResult(
            profile_name=profile.name,
            selected_scope={
                "charts": list(dict.fromkeys(value.charts)),
                "modules": list(dict.fromkeys(value.modules)),
                "reference_date": reference_date.isoformat(),
            },
            normalized_input=calculated["normalized_input"],
            facts=calculated["facts"],
            warnings=profile_warnings(calculation_profile),
            provenance=calculated["provenance"],
        )

    def jaimini(self, value: JaiminiMcpInput) -> JaiminiResult:
        """Compute stateless Jaimini facts from a selected private/inline profile."""
        profile = self._select_profile(value)
        timezone = profile.place.timezone
        if not isinstance(timezone, (IanaTimezone, IanaWithAssertedOffset)):
            raise McpFacadeError("JAIMINI_IANA_TIMEZONE_REQUIRED")
        place = JaiminiPlace(
            name=profile.place.name,
            latitude=profile.place.latitude,
            longitude=profile.place.longitude,
            timezone=timezone.zone_id,
            fold=timezone.fold,
            asserted_offset_hours=(
                timezone.asserted_offset_hours
                if isinstance(timezone, IanaWithAssertedOffset)
                else None
            ),
        )
        if value.birth.confidence == "exact":
            if str(profile.birth_time_confidence.value) != "exact":
                raise McpFacadeError("JAIMINI_EXACT_BIRTH_TIME_REQUIRED")
            birth = ExactJaiminiBirthInput(
                confidence="exact",
                date=profile.date,
                time=profile.time,
                place=place,
            )
        else:
            birth = ApproximateJaiminiBirthInput(
                confidence="approximate",
                date=profile.date,
                earliest_time=value.birth.earliest_time,
                latest_time=value.birth.latest_time,
                place=place,
            )
        request = JaiminiInput(
            profile=profile.name,
            birth=birth,
            rule_profile=value.rule_profile,
            analysis_scope=value.analysis_scope,
            gender=value.gender,
            reference_date=value.reference_date,
            include_trace=value.include_trace,
        )
        return JaiminiFacade().calculate(request)

    def prashna(self, value: PrashnaMcpInput) -> PrashnaResult:
        """Compute one stateless, sealed question-time Praśna result."""
        return PrashnaFacade(clock=self.clock).calculate(value)

    def search_sources(self, value: SourceSearchInput) -> SourceSearchResult:
        results = []
        for item in self.service.search_corpus(value.query, limit=value.limit):
            payload = item.model_dump(mode="json")
            payload["content_role"] = "quoted_source_data"
            results.append(payload)
        return SourceSearchResult(query=value.query, results=results)

    def research(self, value: ResearchInput) -> ResearchBundle:
        profile = self._select_profile(value)
        created = self.service.create_run(
            CreateResearchRunRequest(
                operation_id=new_id("op_"),
                expected_revision=0,
                question=value.question,
                birth_profile=profile,
                calculation_config=CalculationConfigRequest(reference_date=value.reference_date),
                model_version=value.model_version,
                planner_version="career-planner-v1",
                corpus_version="governed-corpus-v1",
                contract_version="2.0",
            )
        )
        screened = self.service.screen_run(
            created.run_id,
            ResearchOperationRequest(
                operation_id=new_id("op_"), expected_revision=created.revision
            ),
        )
        if not screened.safe:
            return ResearchBundle(
                run_id=created.run_id,
                revision=screened.revision,
                status=screened.status,
                safe=False,
                redirect=screened.redirect,
                limitations=["The safety screen stopped this request."],
            )
        classifier_prompt = "codex-native:career_factors_and_timing:v1"
        planned = self.service.plan_run(
            created.run_id,
            PlanResearchRunRequest(
                operation_id=new_id("op_"),
                expected_revision=screened.revision,
                intent=QuestionIntent(
                    family="career_factors_and_timing",
                    explicit_annual_scope=value.explicit_annual_scope,
                ),
                classifier=ClassifierMetadata(
                    classifier_model=value.model_version,
                    classifier_version="codex-native-v1",
                    prompt_hash=sha256_text(classifier_prompt),
                ),
            ),
        )
        if planned.plan.outcome != "supported":
            return ResearchBundle(
                run_id=created.run_id,
                revision=planned.revision,
                status=planned.status,
                safe=True,
                plan=planned.plan.model_dump(mode="json"),
                limitations=["The deterministic planner did not support this question."],
            )
        calculated = self.service.calculate_run(
            created.run_id,
            ResearchOperationRequest(
                operation_id=new_id("op_"), expected_revision=planned.revision
            ),
        )
        # The governed seed corpus is primarily English. A fixed supported-family
        # query gives natural-language Russian requests useful provenance without
        # asking the model to translate or invent retrieval terms.
        query = value.retrieval_query or "career"
        retrieved = self.service.retrieve_run(
            created.run_id,
            RetrieveResearchRunRequest(
                operation_id=new_id("op_"),
                expected_revision=calculated.revision,
                query=query,
                limit=value.source_limit,
            ),
        )
        if not retrieved.results and value.retrieval_query is not None:
            retrieved = self.service.retrieve_run(
                created.run_id,
                RetrieveResearchRunRequest(
                    operation_id=new_id("op_"),
                    expected_revision=retrieved.revision,
                    query="career",
                    limit=value.source_limit,
                ),
            )
        complete_evidence = self.store.list_evidence(created.run_id)
        facts = compact_research_evidence(complete_evidence)
        limitations = []
        if not retrieved.results:
            limitations.append("No approved corpus fragments matched this query.")
        return ResearchBundle(
            run_id=created.run_id,
            revision=retrieved.revision,
            status=retrieved.status,
            safe=True,
            plan=planned.plan.model_dump(mode="json"),
            facts=facts,
            sources=_compact_sources(retrieved.results),
            evidence=[],
            warnings=calculated.warnings,
            limitations=limitations,
        )

    def finalize_research(self, value: FinalizeResearchInput) -> FinalizedResearch:
        run = self.store.get_run(value.run_id)
        if run is None:
            raise McpFacadeError("RUN_NOT_FOUND")
        if run["revision"] != value.expected_revision:
            raise McpFacadeError("REVISION_CONFLICT")
        evidence = {item["evidence_id"]: item for item in self.store.list_evidence(value.run_id)}
        requested = list(dict.fromkeys(support for finding in value.findings for support in finding.supports))
        if any(support not in evidence for support in requested):
            raise McpFacadeError("EVIDENCE_MISSING")

        leaf_by_evidence: dict[str, str] = {}
        claims: list[ComputedClaim | SourceClaim | SynthesisClaim] = []
        for evidence_id in requested:
            item = evidence[evidence_id]
            claim_id = new_id("cl_")
            leaf_by_evidence[evidence_id] = claim_id
            if item["evidence_type"] == "computed_fact":
                claims.append(
                    ComputedClaim(
                        claim_type="computed",
                        claim_id=claim_id,
                        materiality="supporting",
                        confidence=1,
                        supports=[evidence_id],
                    )
                )
            elif item["evidence_type"] == "source_fragment":
                source_text = item["payload"].get("quote") or item["payload"].get("text")
                if not isinstance(source_text, str) or not source_text:
                    raise McpFacadeError("SOURCE_EVIDENCE_INVALID")
                claims.append(
                    SourceClaim(
                        claim_type="source",
                        claim_id=claim_id,
                        materiality="supporting",
                        confidence=1,
                        supports=[evidence_id],
                        text=source_text,
                    )
                )
            else:
                raise McpFacadeError("EVIDENCE_TYPE_UNSUPPORTED")
        for finding in value.findings:
            claims.append(
                SynthesisClaim(
                    claim_type="synthesis",
                    claim_id=new_id("cl_"),
                    materiality=finding.materiality,
                    confidence=finding.confidence,
                    supports=[leaf_by_evidence[item] for item in finding.supports],
                    caveats=finding.caveats,
                    text=finding.text,
                )
            )
        response = self.service.submit_answer(
            value.run_id,
            SubmitAnswerRequest(
                operation_id=new_id("op_"),
                expected_revision=value.expected_revision,
                answer=AnswerContractV2(
                    schema_version="2.0",
                    run_status=run["status"],
                    title=value.title,
                    claims=claims,
                    limitations=value.limitations,
                    followups=value.followups,
                ),
            ),
        )
        return FinalizedResearch(
            run_id=response.run_id,
            revision=response.revision,
            status=response.status,
            valid=response.valid,
            violations=response.violations,
            answer_id=response.answer_id,
            markdown=response.markdown,
            markdown_sha256=response.markdown_sha256,
        )

    def inspect_research(self, value: InspectResearchInput) -> ResearchInspection:
        inspected = self.service.inspect_run(value.run_id)
        answer_payload = inspected.answers[-1]["payload"] if inspected.answers else None
        contract = answer_payload.get("contract") if answer_payload else None
        hashes = None
        if value.replay:
            replayed = self.service.replay_run(value.run_id)
            hashes = {
                "projection_hash": replayed.projection_hash,
                "claims_hash": replayed.claims_hash,
                "memo_hash": replayed.memo_hash,
            }
        claims = self.store.list_claims(value.run_id) if value.include_provenance else None
        return ResearchInspection(
            run_id=value.run_id,
            status=inspected.run.status,
            revision=inspected.run.revision,
            title=contract.get("title") if contract else None,
            answer=answer_payload.get("markdown") if answer_payload else None,
            limitations=contract.get("limitations", []) if contract else [],
            evidence=inspected.evidence if value.include_provenance else None,
            events=(
                [event.model_dump(mode="json") for event in inspected.events]
                if value.include_provenance
                else None
            ),
            claims=claims,
            hashes=hashes,
        )


def facade_from_environment() -> JyotishMcpFacade:
    data_root = Path(
        os.environ.get(
            "JYOTISH_AGENT_DATA_ROOT",
            Path.home() / ".local" / "share" / "jyotish-agent",
        )
    )
    raw_profile = os.environ.get("JYOTISH_DEFAULT_PROFILE_PATH")
    profile_path = Path(raw_profile) if raw_profile else data_root / "profiles" / "vlad.json"
    return JyotishMcpFacade(data_root, profile_path)
