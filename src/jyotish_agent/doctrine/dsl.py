"""Versioned source-bound Doctrine DSL and deterministic compiler."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import Field, model_validator

from ..research_store import canonical_json
from .evidence import EvidenceFailure, EvidenceStore, FragmentRef
from .models import FrozenModel
from .sources import Sha256


Scalar = str | int | float | bool | None
PremiseValue = Scalar | tuple[str | int | float | bool, ...]


class CompilationFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class FactPremise(FrozenModel):
    path: str = Field(pattern=r"^[a-z][A-Za-z0-9_.-]*$")
    operator: Literal[
        "equals", "not_equals", "in", "not_in", "exists", "gt", "gte", "lt", "lte"
    ]
    value: PremiseValue = None

    @model_validator(mode="after")
    def _operator_value_contract(self) -> "FactPremise":
        if self.operator == "exists" and self.value is not None:
            raise ValueError("exists premise value must be null")
        if self.operator in {"in", "not_in"} and not isinstance(self.value, tuple):
            raise ValueError("membership premise value must be an array")
        if self.operator in {"gt", "gte", "lt", "lte"} and (
            isinstance(self.value, bool) or not isinstance(self.value, (int, float))
        ):
            raise ValueError("ordered premise value must be numeric")
        return self

    def matches(self, facts: dict[str, object]) -> bool:
        present = self.path in facts
        actual = facts.get(self.path)
        if self.operator == "exists":
            return present
        if not present:
            return False
        if self.operator == "equals":
            return actual == self.value
        if self.operator == "not_equals":
            return actual != self.value
        if self.operator == "in":
            return actual in (self.value or ())
        if self.operator == "not_in":
            return actual not in (self.value or ())
        if isinstance(actual, bool) or not isinstance(actual, (int, float)):
            return False
        expected = self.value
        if isinstance(expected, bool) or not isinstance(expected, (int, float)):
            return False
        return {
            "gt": actual > expected,
            "gte": actual >= expected,
            "lt": actual < expected,
            "lte": actual <= expected,
        }[self.operator]


class ProfileDefinition(FrozenModel):
    profile_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,95}$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    school: str = Field(min_length=1, max_length=120)
    profile_kind: Literal["baseline", "overlay"]
    base_profile_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def _layer_contract(self) -> "ProfileDefinition":
        if self.profile_kind == "baseline" and self.base_profile_sha256 is not None:
            raise ValueError("baseline profile cannot name a base profile hash")
        if self.profile_kind == "overlay" and self.base_profile_sha256 is None:
            raise ValueError("overlay profile requires a base profile hash")
        return self


class RuleDefinition(FrozenModel):
    rule_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,127}$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    profile_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,95}$")
    school: str = Field(min_length=1, max_length=120)
    topic: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    premises: tuple[FactPremise, ...] = Field(min_length=1)
    exclusions: tuple[FactPremise, ...] = ()
    depends_on: tuple[str, ...] = ()
    conflicts_with: tuple[str, ...] = ()
    supersedes: tuple[str, ...] = ()
    conclusion_template: str = Field(min_length=1, max_length=1_000)
    modality: Literal["symbolic", "tendency", "timing_window", "eligibility", "unavailable"]
    confidence_ceiling: float = Field(ge=0.0, le=0.95)
    time_scope: Literal["natal", "period", "question_anchor", "election_window", "timeless"]
    safety_class: Literal["informational", "safe_symbolic", "sensitive_symbolic", "prohibited"]
    source_refs: tuple[FragmentRef, ...]

    @model_validator(mode="after")
    def _unique_edges(self) -> "RuleDefinition":
        for name in ("depends_on", "conflicts_with", "supersedes"):
            values = getattr(self, name)
            if len(values) != len(set(values)):
                raise ValueError(f"{name} values must be unique")
            if self.rule_id in values:
                raise ValueError(f"rule cannot reference itself in {name}")
        if len(self.source_refs) != len(set(self.source_refs)):
            raise ValueError("source_refs must be unique")
        return self


class CompiledRule(FrozenModel):
    rule_id: str
    version: str
    profile_id: str
    layer_kind: Literal["baseline", "overlay"]
    school: str
    topic: str
    premises: tuple[FactPremise, ...]
    exclusions: tuple[FactPremise, ...]
    depends_on: tuple[str, ...]
    conflicts_with: tuple[str, ...]
    supersedes: tuple[str, ...]
    conclusion_template: str
    modality: str
    confidence_ceiling: float
    time_scope: str
    safety_class: str
    source_refs: tuple[FragmentRef, ...]
    rule_sha256: Sha256

    def matches(self, facts: dict[str, object]) -> bool:
        return all(item.matches(facts) for item in self.premises) and not any(
            item.matches(facts) for item in self.exclusions
        )


class CompiledProfile(FrozenModel):
    profile: ProfileDefinition
    source_manifest_sha256: Sha256
    evidence_store_sha256: Sha256
    rules: tuple[CompiledRule, ...]
    superseded_rule_ids: tuple[str, ...]
    own_layer_sha256: Sha256
    layers: tuple[tuple[str, Sha256], ...]
    compiled_profile_sha256: Sha256

    @property
    def executable_rules(self) -> tuple[CompiledRule, ...]:
        superseded = set(self.superseded_rule_ids)
        return tuple(rule for rule in self.rules if rule.rule_id not in superseded)


class DoctrineCompiler:
    def __init__(self, evidence: EvidenceStore) -> None:
        self.evidence = evidence

    def compile(
        self,
        profile: ProfileDefinition,
        rules: list[RuleDefinition] | tuple[RuleDefinition, ...],
        *,
        fact_catalog: frozenset[str],
        baseline: CompiledProfile | None = None,
    ) -> CompiledProfile:
        if profile.profile_kind == "baseline" and baseline is not None:
            raise CompilationFailure(
                "BASELINE_CANNOT_LAYER", "A baseline profile cannot consume another profile."
            )
        if profile.profile_kind == "overlay":
            if baseline is None:
                raise CompilationFailure(
                    "OVERLAY_BASE_REQUIRED", "Overlay compilation requires an explicit baseline."
                )
            if profile.base_profile_sha256 != baseline.compiled_profile_sha256:
                raise CompilationFailure(
                    "OVERLAY_BASE_SUBSTITUTED",
                    "Overlay base hash does not match the supplied baseline artifact.",
                )

        own_definitions = sorted(rules, key=lambda item: item.rule_id)
        if len({rule.rule_id for rule in own_definitions}) != len(own_definitions):
            raise CompilationFailure("RULE_ID_DUPLICATE", "Rule IDs must be unique per layer.")
        for rule in own_definitions:
            if rule.profile_id != profile.profile_id or rule.school != profile.school:
                raise CompilationFailure(
                    "RULE_PROFILE_MISMATCH",
                    "Rule profile and school must match the compiled layer explicitly.",
                )
            self._validate_rule_boundary(rule, fact_catalog)

        own_compiled = tuple(
            self._compile_rule(rule, profile.profile_kind) for rule in own_definitions
        )
        inherited = tuple(baseline.rules) if baseline is not None else ()
        combined_by_id = {rule.rule_id: rule for rule in inherited}
        for rule in own_compiled:
            if rule.rule_id in combined_by_id:
                raise CompilationFailure(
                    "RULE_ID_LAYER_COLLISION",
                    "Overlay rules require a new ID and explicit supersedes edge.",
                )
            combined_by_id[rule.rule_id] = rule
        combined = tuple(combined_by_id[key] for key in sorted(combined_by_id))
        self._validate_edges(combined)

        superseded = tuple(
            sorted(
                set(baseline.superseded_rule_ids if baseline is not None else ())
                | {target for rule in combined for target in rule.supersedes}
            )
        )
        for rule in combined:
            if any(dep in superseded for dep in rule.depends_on):
                raise CompilationFailure(
                    "RULE_UNREACHABLE", "Executable rule depends on a superseded rule."
                )
        own_layer_payload = {
            "profile": profile.model_dump(mode="json"),
            "source_manifest_sha256": self.evidence.manifest.manifest_sha256,
            "evidence_store_sha256": self.evidence.store_sha256,
            "rules": [rule.model_dump(mode="json") for rule in own_compiled],
        }
        own_layer_sha256 = _hash_payload(own_layer_payload)
        layers = (
            ((profile.profile_id, own_layer_sha256),)
            if baseline is None
            else (
                (baseline.profile.profile_id, baseline.compiled_profile_sha256),
                (profile.profile_id, own_layer_sha256),
            )
        )
        compiled_payload = {
            "profile": profile.model_dump(mode="json"),
            "source_manifest_sha256": self.evidence.manifest.manifest_sha256,
            "evidence_store_sha256": self.evidence.store_sha256,
            "rules": [rule.model_dump(mode="json") for rule in combined],
            "superseded_rule_ids": superseded,
            "own_layer_sha256": own_layer_sha256,
            "layers": layers,
        }
        return CompiledProfile(
            **compiled_payload,
            compiled_profile_sha256=_hash_payload(compiled_payload),
        )

    def _validate_rule_boundary(
        self, rule: RuleDefinition, fact_catalog: frozenset[str]
    ) -> None:
        if not rule.source_refs:
            raise CompilationFailure(
                "RULE_SOURCE_REQUIRED", "Executable rules require admitted source evidence."
            )
        for reference in rule.source_refs:
            try:
                fragment = self.evidence.resolve(reference, require_current=True)
            except EvidenceFailure as exc:
                raise CompilationFailure(exc.code, str(exc)) from exc
            if fragment.admission_status != "admitted":
                raise CompilationFailure(
                    "RULE_SOURCE_NOT_ADMITTED",
                    "Rule source evidence is not admitted for compilation.",
                )
        for premise in (*rule.premises, *rule.exclusions):
            if premise.path not in fact_catalog:
                raise CompilationFailure(
                    "FACT_PATH_UNSUPPORTED", "Rule references an unsupported fact path."
                )
        if rule.safety_class == "prohibited":
            raise CompilationFailure(
                "RULE_SAFETY_PROHIBITED", "Prohibited safety classes are not executable."
            )

    @staticmethod
    def _compile_rule(
        definition: RuleDefinition, layer_kind: Literal["baseline", "overlay"]
    ) -> CompiledRule:
        payload = {**definition.model_dump(mode="json"), "layer_kind": layer_kind}
        return CompiledRule(**payload, rule_sha256=_hash_payload(payload))

    @staticmethod
    def _validate_edges(rules: tuple[CompiledRule, ...]) -> None:
        by_id = {rule.rule_id: rule for rule in rules}
        for rule in rules:
            for target in (*rule.depends_on, *rule.conflicts_with, *rule.supersedes):
                if target not in by_id:
                    code = (
                        "RULE_DEPENDENCY_MISSING"
                        if target in rule.depends_on
                        else "RULE_EDGE_TARGET_MISSING"
                    )
                    raise CompilationFailure(code, "Rule edge target does not exist.")
            for dependency in rule.depends_on:
                if rule.confidence_ceiling > by_id[dependency].confidence_ceiling:
                    raise CompilationFailure(
                        "RULE_CONFIDENCE_ESCALATION",
                        "Dependent rule confidence exceeds its supporting rule ceiling.",
                    )
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(rule_id: str) -> None:
            if rule_id in visiting:
                raise CompilationFailure(
                    "RULE_DEPENDENCY_CYCLE", "Rule dependency graph contains a cycle."
                )
            if rule_id in visited:
                return
            visiting.add(rule_id)
            for dependency in by_id[rule_id].depends_on:
                visit(dependency)
            visiting.remove(rule_id)
            visited.add(rule_id)

        for rule_id in sorted(by_id):
            visit(rule_id)


def _hash_payload(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
