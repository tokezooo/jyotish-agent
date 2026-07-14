"""Source-bound corpus ledger for the Expanded Muhūrta release.

The ledger verifies locally held source bytes, keeps baseline, commentary, and
modern overlay roles separate, and never turns a worked illustration into an
observed outcome claim.
"""

from __future__ import annotations

import json
import datetime as dt
from enum import StrEnum
from importlib import resources
from typing import Literal

from pydantic import Field, model_validator

from .models import FrozenModel
from .sources import SourceId, SourceManifest, SourceVerificationReport


class MuhurtaCorpusRequirement(StrEnum):
    MUHURTA_CINTAMANI = "muhurta_cintamani"
    KALAPRAKASIKA = "kalaprakasika"
    PANCHANGA_DOSA_REFERENCE = "panchanga_dosa_reference"
    MODERN_OVERLAY = "modern_overlay"
    PUBLISHED_WORKED_ELECTIONS = "published_worked_elections"


class MuhurtaCorpusRequirementRecord(FrozenModel):
    requirement: MuhurtaCorpusRequirement
    school_role: Literal["baseline", "commentary", "overlay", "worked_examples"]
    source_ids: tuple[SourceId, ...] = ()
    rule_topics: tuple[str, ...] = ()
    applicable_safe_profiles: tuple[str, ...] = ()
    acquisition_blocker: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _coherent(self) -> "MuhurtaCorpusRequirementRecord":
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("source_ids must be unique")
        if not self.source_ids and not self.acquisition_blocker:
            raise ValueError("a source-free requirement needs an acquisition blocker")
        if len(set(self.rule_topics)) != len(self.rule_topics):
            raise ValueError("rule_topics must be unique")
        if len(set(self.applicable_safe_profiles)) != len(self.applicable_safe_profiles):
            raise ValueError("applicable_safe_profiles must be unique")
        return self


class MuhurtaCorpusCatalog(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    safe_profiles: tuple[str, ...] = Field(min_length=6)
    unsupported_high_stakes_profiles: tuple[str, ...] = Field(min_length=1)
    requirements: tuple[MuhurtaCorpusRequirementRecord, ...] = Field(min_length=5)

    @model_validator(mode="after")
    def _complete_separated_catalog(self) -> "MuhurtaCorpusCatalog":
        requirements = [item.requirement for item in self.requirements]
        if len(requirements) != len(set(requirements)):
            raise ValueError("duplicate corpus requirement")
        if set(requirements) != set(MuhurtaCorpusRequirement):
            raise ValueError("catalog must declare every Muhurta corpus requirement")
        safe = set(self.safe_profiles)
        if safe & set(self.unsupported_high_stakes_profiles):
            raise ValueError("safe and high-stakes profiles must be disjoint")
        baseline = self.requirement(MuhurtaCorpusRequirement.MUHURTA_CINTAMANI)
        commentary = self.requirement(MuhurtaCorpusRequirement.KALAPRAKASIKA)
        overlay = self.requirement(MuhurtaCorpusRequirement.MODERN_OVERLAY)
        if {baseline.school_role, commentary.school_role, overlay.school_role} != {
            "baseline",
            "commentary",
            "overlay",
        }:
            raise ValueError("baseline, commentary, and overlay roles must stay explicit")
        for item in self.requirements:
            if not set(item.applicable_safe_profiles) <= safe:
                raise ValueError("requirement references an undeclared safe profile")
        covered = {
            profile
            for item in self.requirements
            if item.requirement != MuhurtaCorpusRequirement.MODERN_OVERLAY
            for profile in item.applicable_safe_profiles
        }
        if covered != safe:
            raise ValueError("classical requirements must map every safe profile")
        return self

    def requirement(
        self, requirement: MuhurtaCorpusRequirement
    ) -> MuhurtaCorpusRequirementRecord:
        return next(item for item in self.requirements if item.requirement == requirement)


class MuhurtaWorkedExample(FrozenModel):
    example_id: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    source_id: SourceId
    profile: str = Field(min_length=1)
    example_kind: Literal["worked_rule_illustration"]
    source_pdf_pages: tuple[int, ...] = Field(min_length=1)
    source_printed_pages: tuple[int, ...] = Field(min_length=1)
    rule_topics: tuple[str, ...] = Field(min_length=1)
    observed_outcome_claimed: Literal[False]

    @model_validator(mode="after")
    def _paired_pages(self) -> "MuhurtaWorkedExample":
        if len(self.source_pdf_pages) != len(self.source_printed_pages):
            raise ValueError("PDF and printed page anchors must pair one-to-one")
        if len(set(self.source_pdf_pages)) != len(self.source_pdf_pages):
            raise ValueError("source_pdf_pages must be unique")
        return self


class MuhurtaWorkedExampleCatalog(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    examples: tuple[MuhurtaWorkedExample, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def _unique_examples(self) -> "MuhurtaWorkedExampleCatalog":
        ids = [item.example_id for item in self.examples]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate worked example")
        return self


class MuhurtaCorpusCoverage(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    manifest_sha256: str
    verified_source_ids: tuple[SourceId, ...]
    unverified_source_ids: tuple[SourceId, ...]
    covered_requirements: tuple[MuhurtaCorpusRequirement, ...]
    missing_requirements: tuple[MuhurtaCorpusRequirement, ...]
    verified_worked_example_count: int = Field(ge=0)
    covered_safe_profiles: tuple[str, ...]
    unsupported_high_stakes_profiles: tuple[str, ...]
    acquisition_blockers: tuple[str, ...]
    ready: bool


def build_muhurta_corpus_coverage(
    manifest: SourceManifest,
    verification: SourceVerificationReport,
    catalog: MuhurtaCorpusCatalog,
    examples: MuhurtaWorkedExampleCatalog,
) -> MuhurtaCorpusCoverage:
    manifest_ids = {source.source_id for source in manifest.sources}
    referenced_ids = {
        source_id for item in catalog.requirements for source_id in item.source_ids
    } | {item.source_id for item in examples.examples}
    if referenced_ids - manifest_ids:
        raise ValueError("Muhurta catalog references a source absent from the manifest")

    verified = set(verification.verified_source_ids)
    verified_examples = sum(item.source_id in verified for item in examples.examples)
    covered: list[MuhurtaCorpusRequirement] = []
    missing: list[MuhurtaCorpusRequirement] = []
    blockers: list[str] = []
    profiles: set[str] = set()
    for item in sorted(catalog.requirements, key=lambda value: value.requirement.value):
        fulfilled = bool(item.source_ids) and set(item.source_ids) <= verified
        if item.requirement == MuhurtaCorpusRequirement.PUBLISHED_WORKED_ELECTIONS:
            fulfilled = fulfilled and verified_examples >= 2
        if fulfilled:
            covered.append(item.requirement)
            profiles.update(item.applicable_safe_profiles)
        else:
            missing.append(item.requirement)
            blockers.append(
                f"{item.requirement.value}: "
                f"{item.acquisition_blocker or 'declared source bytes did not verify'}"
            )

    return MuhurtaCorpusCoverage(
        manifest_sha256=manifest.manifest_sha256,
        verified_source_ids=tuple(sorted(verified)),
        unverified_source_ids=tuple(sorted(manifest_ids - verified)),
        covered_requirements=tuple(sorted(covered, key=lambda item: item.value)),
        missing_requirements=tuple(sorted(missing, key=lambda item: item.value)),
        verified_worked_example_count=verified_examples,
        covered_safe_profiles=tuple(sorted(profiles)),
        unsupported_high_stakes_profiles=tuple(
            sorted(catalog.unsupported_high_stakes_profiles)
        ),
        acquisition_blockers=tuple(sorted(blockers)),
        ready=not missing,
    )


def render_muhurta_corpus_coverage(
    report: MuhurtaCorpusCoverage,
) -> dict[str, object]:
    """Return a deterministic projection without source paths or source text."""

    return report.model_dump(mode="json")


class MuhurtaActivityProfile(StrEnum):
    FOCUSED_WORK = "focused_work"
    STUDY_LEARNING = "study_learning"
    CREATIVE_PRODUCTION = "creative_production"
    PRODUCT_LAUNCH_COMMUNICATION = "product_launch_communication"
    LOW_RISK_TRAVEL_PLANNING = "low_risk_travel_planning"
    GENERAL_PRIVATE_TASK = "general_private_task"


class MuhurtaProfileDefinition(FrozenModel):
    profile: MuhurtaActivityProfile
    aliases_en: tuple[str, ...] = Field(min_length=1)
    aliases_ru: tuple[str, ...] = Field(min_length=1)
    required_rule_families: tuple[str, ...] = Field(min_length=1)
    doctrine_status: Literal["available", "unavailable_pending_source_admission"]
    admitted_rule_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _availability_is_honest(self) -> "MuhurtaProfileDefinition":
        if self.doctrine_status == "available" and not self.admitted_rule_ids:
            raise ValueError("available profile requires admitted rules")
        if (
            self.doctrine_status == "unavailable_pending_source_admission"
            and self.admitted_rule_ids
        ):
            raise ValueError("unavailable profile cannot carry admitted rules")
        for aliases in (self.aliases_en, self.aliases_ru):
            if len(set(aliases)) != len(aliases):
                raise ValueError("profile aliases must be unique")
        return self


class MuhurtaProfileCatalog(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    profiles: tuple[MuhurtaProfileDefinition, ...] = Field(min_length=6)
    high_stakes_aliases_en: tuple[str, ...] = Field(min_length=1)
    high_stakes_aliases_ru: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _complete(self) -> "MuhurtaProfileCatalog":
        declared = [item.profile for item in self.profiles]
        if len(declared) != len(set(declared)) or set(declared) != set(
            MuhurtaActivityProfile
        ):
            raise ValueError("profile catalog must declare every activity exactly once")
        for locale in ("en", "ru"):
            aliases = [
                alias
                for item in self.profiles
                for alias in getattr(item, f"aliases_{locale}")
            ]
            if len(aliases) != len(set(aliases)):
                raise ValueError(f"{locale} aliases must not overlap between profiles")
        return self


class MuhurtaActivityRoute(FrozenModel):
    status: Literal["supported", "needs_input", "unsupported_high_stakes"]
    profile: MuhurtaActivityProfile | None = None
    reason_code: str | None = None
    legacy_profile_id: Literal["muhurta_focused_work_v1"] | None = None

    @model_validator(mode="after")
    def _coherent_route(self) -> "MuhurtaActivityRoute":
        if self.status == "supported" and self.profile is None:
            raise ValueError("supported route requires a profile")
        if self.status != "supported" and self.profile is not None:
            raise ValueError("non-supported route cannot select a profile")
        return self


def load_muhurta_profile_catalog() -> MuhurtaProfileCatalog:
    payload = resources.files("jyotish_agent").joinpath(
        "data/doctrine/muhurta-profiles.json"
    ).read_text(encoding="utf-8")
    return MuhurtaProfileCatalog.model_validate(json.loads(payload))


def _normalize_activity(value: str) -> str:
    return " ".join(
        "".join(character if character.isalnum() else " " for character in value.casefold()).split()
    )


def _alias_present(normalized: str, alias: str) -> bool:
    normalized_alias = _normalize_activity(alias)
    return normalized == normalized_alias or f" {normalized_alias} " in f" {normalized} "


def route_muhurta_activity(
    activity: str, *, locale: Literal["ru", "en"]
) -> MuhurtaActivityRoute:
    """Route only explicit, bounded aliases; broad intent never widens scope."""

    catalog = load_muhurta_profile_catalog()
    normalized = _normalize_activity(activity)
    high_stakes = getattr(catalog, f"high_stakes_aliases_{locale}")
    if any(_alias_present(normalized, alias) for alias in high_stakes):
        return MuhurtaActivityRoute(
            status="unsupported_high_stakes",
            reason_code="HIGH_STAKES_ACTIVITY",
        )

    matches = [
        item.profile
        for item in catalog.profiles
        if any(
            _alias_present(normalized, alias)
            for alias in getattr(item, f"aliases_{locale}")
        )
    ]
    if len(matches) > 1:
        return MuhurtaActivityRoute(
            status="needs_input",
            reason_code="COMPOSITE_ACTIVITY_UNSUPPORTED",
        )
    if not matches:
        return MuhurtaActivityRoute(
            status="needs_input",
            reason_code="ACTIVITY_PROFILE_REQUIRED",
        )
    profile = matches[0]
    return MuhurtaActivityRoute(
        status="supported",
        profile=profile,
        legacy_profile_id=(
            "muhurta_focused_work_v1"
            if profile == MuhurtaActivityProfile.FOCUSED_WORK
            else None
        ),
    )


class MuhurtaRuleInterval(FrozenModel):
    rule_id: str = Field(pattern=r"^muhurta\.[A-Za-z0-9_.-]+$")
    classification: Literal["hard", "soft"]
    start: dt.datetime
    end: dt.datetime
    source_locator: str = Field(min_length=1)

    @model_validator(mode="after")
    def _valid_half_open_interval(self) -> "MuhurtaRuleInterval":
        if any(
            value.tzinfo is None or value.utcoffset() is None
            for value in (self.start, self.end)
        ):
            raise ValueError("rule interval endpoints must be timezone-aware")
        if self.end.astimezone(dt.UTC) <= self.start.astimezone(dt.UTC):
            raise ValueError("rule interval end must be after start")
        return self


class MuhurtaEligibilityInput(FrozenModel):
    profile: MuhurtaActivityProfile
    start: dt.datetime
    end: dt.datetime
    zone_id: str = Field(min_length=1)
    panchanga_status: Literal["allowed", "prohibited", "unavailable"]
    dosa_status: Literal["clear", "active", "unavailable"]
    weekday_status: Literal["allowed", "prohibited", "unavailable"]
    daylight_status: Literal["inside", "outside", "unavailable"]
    lagna_status: Literal["available", "prohibited", "unavailable"]
    require_daylight: bool
    require_lagna: bool
    source_rule_intervals: tuple[MuhurtaRuleInterval, ...] = ()
    source_admitted: bool

    @model_validator(mode="after")
    def _valid_candidate(self) -> "MuhurtaEligibilityInput":
        if any(
            value.tzinfo is None or value.utcoffset() is None
            for value in (self.start, self.end)
        ):
            raise ValueError("candidate endpoints must be timezone-aware")
        if self.end.astimezone(dt.UTC) <= self.start.astimezone(dt.UTC):
            raise ValueError("candidate end must be after start")
        return self


class MuhurtaEligibilityTrace(FrozenModel):
    rule_id: str = Field(pattern=r"^muhurta\.[A-Za-z0-9_.-]+$")
    classification: Literal["hard", "soft"]
    applicability: Literal["applicable", "not_applicable"]
    result: Literal["pass", "fail", "preferred", "neutral"]
    source_locator: str = Field(min_length=1)


class MuhurtaEligibilityResult(FrozenModel):
    status: Literal["eligible", "ineligible", "unavailable"]
    hard_failures: tuple[str, ...] = ()
    soft_signals: tuple[str, ...] = ()
    rule_traces: tuple[MuhurtaEligibilityTrace, ...] = ()
    reason_code: str | None = None


_ELIGIBILITY_LOCATORS = {
    "muhurta.eligibility.panchanga": "Kalaprakasika, Introduction, printed p. xvii",
    "muhurta.eligibility.dosa": "Kalaprakasika, adverse periods, printed pp. 167-177",
    "muhurta.eligibility.weekday": "Kalaprakasika, weekday periods, printed p. 176",
    "muhurta.eligibility.daylight": "request hard constraint; source not required",
    "muhurta.eligibility.lagna": "Kalaprakasika, rising-sign conditions, printed pp. 178-185",
    "muhurta.preference.daylight": "request soft preference; source not required",
}


def _overlaps_half_open(
    left_start: dt.datetime,
    left_end: dt.datetime,
    right_start: dt.datetime,
    right_end: dt.datetime,
) -> bool:
    left_start_utc, left_end_utc = left_start.astimezone(dt.UTC), left_end.astimezone(dt.UTC)
    right_start_utc, right_end_utc = (
        right_start.astimezone(dt.UTC),
        right_end.astimezone(dt.UTC),
    )
    return left_start_utc < right_end_utc and right_start_utc < left_end_utc


def evaluate_muhurta_eligibility(
    value: MuhurtaEligibilityInput,
) -> MuhurtaEligibilityResult:
    """Apply admitted hard gates before soft signals, with a full rule trace."""

    if not value.source_admitted:
        return MuhurtaEligibilityResult(
            status="unavailable",
            reason_code="SOURCE_RULES_NOT_ADMITTED",
        )

    hard_checks = (
        ("muhurta.eligibility.panchanga", value.panchanga_status == "allowed", True),
        ("muhurta.eligibility.dosa", value.dosa_status == "clear", True),
        ("muhurta.eligibility.weekday", value.weekday_status == "allowed", True),
        (
            "muhurta.eligibility.daylight",
            value.daylight_status == "inside",
            value.require_daylight,
        ),
        (
            "muhurta.eligibility.lagna",
            value.lagna_status == "available",
            value.require_lagna,
        ),
    )
    traces: list[MuhurtaEligibilityTrace] = []
    hard_failures: list[str] = []
    for rule_id, passed, applicable in hard_checks:
        if applicable and not passed:
            hard_failures.append(rule_id)
        traces.append(
            MuhurtaEligibilityTrace(
                rule_id=rule_id,
                classification="hard",
                applicability="applicable" if applicable else "not_applicable",
                result=("pass" if passed else "fail") if applicable else "neutral",
                source_locator=_ELIGIBILITY_LOCATORS[rule_id],
            )
        )

    soft_signals: list[str] = []
    daylight_preferred = value.daylight_status == "inside"
    if daylight_preferred:
        soft_signals.append("daylight_preferred")
    traces.append(
        MuhurtaEligibilityTrace(
            rule_id="muhurta.preference.daylight",
            classification="soft",
            applicability="applicable",
            result="preferred" if daylight_preferred else "neutral",
            source_locator=_ELIGIBILITY_LOCATORS["muhurta.preference.daylight"],
        )
    )

    for interval in value.source_rule_intervals:
        applies = _overlaps_half_open(value.start, value.end, interval.start, interval.end)
        if applies and interval.classification == "hard":
            hard_failures.append(interval.rule_id)
        elif applies:
            soft_signals.append(interval.rule_id)
        traces.append(
            MuhurtaEligibilityTrace(
                rule_id=interval.rule_id,
                classification=interval.classification,
                applicability="applicable" if applies else "not_applicable",
                result=(
                    "fail"
                    if applies and interval.classification == "hard"
                    else "preferred"
                    if applies
                    else "neutral"
                ),
                source_locator=interval.source_locator,
            )
        )

    failures = tuple(sorted(set(hard_failures)))
    return MuhurtaEligibilityResult(
        status="ineligible" if failures else "eligible",
        hard_failures=failures,
        soft_signals=tuple(sorted(set(soft_signals))),
        rule_traces=tuple(traces),
    )


class MuhurtaNatalFactorsInput(FrozenModel):
    personalization_requested: bool
    consent_confirmed: bool
    source_admitted: bool
    birth_time_accuracy: Literal["exact", "approximate"]
    birth_nakshatra_stable: bool
    birth_moon_sign_stable: bool
    birth_nakshatra_index: int = Field(ge=0, le=26)
    candidate_nakshatra_index: int = Field(ge=0, le=26)
    birth_moon_sign_index: int = Field(ge=0, le=11)
    candidate_moon_sign_index: int = Field(ge=0, le=11)


class MuhurtaNatalFactorsResult(FrozenModel):
    status: Literal["available", "omitted", "unavailable"]
    tara_bala: Literal["favorable", "unfavorable"] | None = None
    candra_bala: Literal["favorable", "unfavorable"] | None = None
    soft_adjustment: int = Field(ge=-2, le=2)
    confidence: Literal["exact", "stable_approximate", "unstable", "not_applicable"]
    source_locators: tuple[str, ...] = ()
    reason_code: str | None = None
    can_override_hard_exclusion: Literal[False] = False


def evaluate_muhurta_natal_factors(
    value: MuhurtaNatalFactorsInput,
) -> MuhurtaNatalFactorsResult:
    """Calculate opt-in Tara/Candra bala without returning natal coordinates."""

    if not value.personalization_requested:
        return MuhurtaNatalFactorsResult(
            status="omitted",
            soft_adjustment=0,
            confidence="not_applicable",
        )
    if not value.consent_confirmed:
        return MuhurtaNatalFactorsResult(
            status="unavailable",
            soft_adjustment=0,
            confidence="not_applicable",
            reason_code="NATAL_CONSENT_REQUIRED",
        )
    if not value.source_admitted:
        return MuhurtaNatalFactorsResult(
            status="unavailable",
            soft_adjustment=0,
            confidence="not_applicable",
            reason_code="NATAL_RULES_NOT_ADMITTED",
        )
    if value.birth_time_accuracy == "approximate" and not (
        value.birth_nakshatra_stable and value.birth_moon_sign_stable
    ):
        return MuhurtaNatalFactorsResult(
            status="unavailable",
            soft_adjustment=0,
            confidence="unstable",
            reason_code="NATAL_FACTORS_UNSTABLE",
        )

    tara_position = (
        (value.candidate_nakshatra_index - value.birth_nakshatra_index) % 9
    ) + 1
    candra_position = (
        (value.candidate_moon_sign_index - value.birth_moon_sign_index) % 12
    ) + 1
    tara = "favorable" if tara_position in {2, 4, 6, 8, 9} else "unfavorable"
    candra = "favorable" if candra_position in {1, 3, 6, 7, 10, 11} else "unfavorable"
    adjustment = (1 if tara == "favorable" else -1) + (
        1 if candra == "favorable" else -1
    )
    return MuhurtaNatalFactorsResult(
        status="available",
        tara_bala=tara,
        candra_bala=candra,
        soft_adjustment=adjustment,
        confidence=(
            "exact" if value.birth_time_accuracy == "exact" else "stable_approximate"
        ),
        source_locators=(
            "Kalaprakasika, printed pp. 166-168",
            "Kalaprakasika, printed pp. 207-208",
        ),
    )


class MuhurtaRankingProfile(FrozenModel):
    profile: MuhurtaActivityProfile
    version: Literal["1.0.0"]
    doctrine_weight: int = Field(ge=1, le=10)
    natal_weight: int = Field(ge=0, le=5)
    user_preference_weight: int = Field(ge=0, le=5)
    tie_break: Literal["start_utc_then_candidate_id"]


class MuhurtaRankingCatalog(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    profiles: tuple[MuhurtaRankingProfile, ...] = Field(min_length=6)

    @model_validator(mode="after")
    def _complete(self) -> "MuhurtaRankingCatalog":
        profiles = [item.profile for item in self.profiles]
        if len(profiles) != len(set(profiles)) or set(profiles) != set(
            MuhurtaActivityProfile
        ):
            raise ValueError("ranking catalog must cover every Muhurta profile")
        return self


class MuhurtaRankingCandidate(FrozenModel):
    candidate_id: str = Field(min_length=1)
    start: dt.datetime
    end: dt.datetime
    eligibility_status: Literal["eligible", "ineligible", "unavailable"]
    hard_failure_ids: tuple[str, ...] = ()
    doctrinal_soft_score: int = Field(ge=-10, le=10)
    natal_soft_adjustment: int = Field(ge=-2, le=2)
    user_preference_score: int = Field(ge=-2, le=2)
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _coherent_candidate(self) -> "MuhurtaRankingCandidate":
        if any(
            value.tzinfo is None or value.utcoffset() is None
            for value in (self.start, self.end)
        ):
            raise ValueError("candidate endpoints must be timezone-aware")
        if self.end.astimezone(dt.UTC) <= self.start.astimezone(dt.UTC):
            raise ValueError("candidate end must be after start")
        if self.eligibility_status == "eligible" and self.hard_failure_ids:
            raise ValueError("eligible candidate cannot have hard failures")
        if self.eligibility_status == "ineligible" and not self.hard_failure_ids:
            raise ValueError("ineligible candidate requires a hard failure")
        if len(set(self.hard_failure_ids)) != len(self.hard_failure_ids):
            raise ValueError("hard failures must be unique")
        return self


class MuhurtaRankedWindow(FrozenModel):
    candidate_id: str
    start: dt.datetime
    end: dt.datetime
    rank: int = Field(ge=1)
    total_score: int
    score_components: dict[str, int]
    confidence: float = Field(ge=0.0, le=1.0)
    pareto_dominated_by: tuple[str, ...] = ()


class MuhurtaRankingNearMiss(FrozenModel):
    candidate_id: str
    start: dt.datetime
    end: dt.datetime
    hard_failure_ids: tuple[str, ...] = Field(min_length=1)


class MuhurtaRankingResult(FrozenModel):
    status: Literal["completed", "no_window", "unavailable"]
    profile: MuhurtaActivityProfile
    ranking_version: Literal["1.0.0"]
    ranked: tuple[MuhurtaRankedWindow, ...] = ()
    near_misses: tuple[MuhurtaRankingNearMiss, ...] = ()


def load_muhurta_ranking_profile(
    profile: MuhurtaActivityProfile,
) -> MuhurtaRankingProfile:
    payload = resources.files("jyotish_agent").joinpath(
        "data/doctrine/muhurta-ranking-v1.json"
    ).read_text(encoding="utf-8")
    catalog = MuhurtaRankingCatalog.model_validate(json.loads(payload))
    return next(item for item in catalog.profiles if item.profile == profile)


def _dominates(left: MuhurtaRankingCandidate, right: MuhurtaRankingCandidate) -> bool:
    left_values = (
        left.doctrinal_soft_score,
        left.natal_soft_adjustment,
        left.user_preference_score,
        left.confidence,
    )
    right_values = (
        right.doctrinal_soft_score,
        right.natal_soft_adjustment,
        right.user_preference_score,
        right.confidence,
    )
    return all(a >= b for a, b in zip(left_values, right_values, strict=True)) and any(
        a > b for a, b in zip(left_values, right_values, strict=True)
    )


def rank_muhurta_candidates(
    candidates: tuple[MuhurtaRankingCandidate, ...],
    profile: MuhurtaRankingProfile,
) -> MuhurtaRankingResult:
    """Rank eligible candidates only and retain rejected candidates as near misses."""

    eligible = [item for item in candidates if item.eligibility_status == "eligible"]
    unavailable = [
        item for item in candidates if item.eligibility_status == "unavailable"
    ]
    ineligible = [
        item for item in candidates if item.eligibility_status == "ineligible"
    ]

    scored: list[tuple[MuhurtaRankingCandidate, dict[str, int], int]] = []
    for item in eligible:
        components = {
            "doctrine": item.doctrinal_soft_score * profile.doctrine_weight,
            "natal": item.natal_soft_adjustment * profile.natal_weight,
            "user_preference": item.user_preference_score
            * profile.user_preference_weight,
        }
        scored.append((item, components, sum(components.values())))
    scored.sort(
        key=lambda row: (
            -row[2],
            row[0].start.astimezone(dt.UTC),
            row[0].candidate_id,
        )
    )
    ordering = {item.candidate_id: index for index, (item, _, _) in enumerate(scored)}
    ranked = tuple(
        MuhurtaRankedWindow(
            candidate_id=item.candidate_id,
            start=item.start,
            end=item.end,
            rank=index,
            total_score=total,
            score_components=components,
            confidence=item.confidence,
            pareto_dominated_by=tuple(
                candidate.candidate_id
                for candidate in sorted(
                    (other for other in eligible if _dominates(other, item)),
                    key=lambda other: ordering[other.candidate_id],
                )
            ),
        )
        for index, (item, components, total) in enumerate(scored, start=1)
    )
    ineligible.sort(
        key=lambda item: (
            len(item.hard_failure_ids),
            item.start.astimezone(dt.UTC),
            item.candidate_id,
        )
    )
    near_misses = tuple(
        MuhurtaRankingNearMiss(
            candidate_id=item.candidate_id,
            start=item.start,
            end=item.end,
            hard_failure_ids=tuple(sorted(item.hard_failure_ids)),
        )
        for item in ineligible
    )
    status: Literal["completed", "no_window", "unavailable"]
    if ranked:
        status = "completed"
    elif unavailable:
        status = "unavailable"
    else:
        status = "no_window"
    return MuhurtaRankingResult(
        status=status,
        profile=profile.profile,
        ranking_version=profile.version,
        ranked=ranked,
        near_misses=near_misses,
    )
