from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from jyotish_agent.doctrine.dsl import (
    CompilationFailure,
    DoctrineCompiler,
    FactPremise,
    ProfileDefinition,
    RuleDefinition,
)
from jyotish_agent.doctrine.evidence import EvidenceStore, FragmentDraft, FragmentRef
from jyotish_agent.doctrine.sources import SourceManifest


FACTS = frozenset(
    {
        "jaimini.karakas.AK.planet",
        "jaimini.karakas.AmK.planet",
        "jaimini.arudha.AL.sign",
        "jaimini.dasha.active.sign",
    }
)


def _manifest() -> SourceManifest:
    return SourceManifest.model_validate(
        {
            "schema_version": "1.0",
            "sources": [
                {
                    "source_id": "jaimini_source_v1",
                    "title": "Jaimini fixture source",
                    "author_or_commentator": "Fixture author",
                    "translator_editor": "Fixture editor",
                    "edition": "Fixture edition",
                    "publisher": "Fixture publisher",
                    "year": 2026,
                    "isbn": None,
                    "languages": ["en"],
                    "domain": "jaimini",
                    "school_role": "baseline",
                    "license_class": "public_domain",
                    "local_file": "jaimini/fixture/source.pdf",
                    "sha256": hashlib.sha256(b"source").hexdigest(),
                    "page_offset": 0,
                    "scan_quality": "born_digital",
                    "ocr_required": False,
                    "ocr_status": "not_required",
                }
            ],
        }
    )


def _store(*, status: str = "admitted") -> tuple[EvidenceStore, FragmentRef]:
    manifest = _manifest()
    store = EvidenceStore(manifest)
    text = "A permitted source fragment for symbolic career analysis."
    fragment = store.append(
        FragmentDraft(
            source_id="jaimini_source_v1",
            source_manifest_sha256=manifest.manifest_sha256,
            page_number=12,
            printed_page=12,
            anchor_kind="sutra",
            anchor_label="1.2.3",
            language="en",
            content_role="root_text",
            school="baseline_school",
            scope="career",
            full_text_sha256=hashlib.sha256(text.encode()).hexdigest(),
            normalized_content_sha256=hashlib.sha256(text.encode()).hexdigest(),
            excerpt_permission="public_domain",
            permitted_excerpt=text,
            admission_status=status,
        )
    )
    return store, FragmentRef.from_fragment(fragment)


def _profile(**updates: object) -> ProfileDefinition:
    payload: dict[str, object] = {
        "profile_id": "jaimini_baseline_v1",
        "version": "1.0.0",
        "school": "baseline_school",
        "profile_kind": "baseline",
        "base_profile_sha256": None,
    }
    payload.update(updates)
    return ProfileDefinition.model_validate(payload)


def _rule(reference: FragmentRef, **updates: object) -> RuleDefinition:
    payload: dict[str, object] = {
        "rule_id": "jaimini.career.amatyakaraka",
        "version": "1.0.0",
        "profile_id": "jaimini_baseline_v1",
        "school": "baseline_school",
        "topic": "career",
        "premises": [
            {
                "path": "jaimini.karakas.AmK.planet",
                "operator": "equals",
                "value": "Mercury",
            }
        ],
        "exclusions": [],
        "depends_on": [],
        "conflicts_with": [],
        "supersedes": [],
        "conclusion_template": "Amatyakaraka supports a symbolic career theme.",
        "modality": "symbolic",
        "confidence_ceiling": 0.70,
        "time_scope": "natal",
        "safety_class": "safe_symbolic",
        "source_refs": [reference.model_dump(mode="json")],
    }
    payload.update(updates)
    return RuleDefinition.model_validate(payload)


def test_compiler_requires_current_admitted_sources_and_supported_fact_paths() -> None:
    store, reference = _store()
    compiler = DoctrineCompiler(store)

    with pytest.raises(CompilationFailure) as no_source:
        compiler.compile(
            _profile(),
            [_rule(reference, source_refs=[])],
            fact_catalog=FACTS,
        )
    assert no_source.value.code == "RULE_SOURCE_REQUIRED"

    quarantined_store, quarantined_ref = _store(status="quarantined")
    with pytest.raises(CompilationFailure) as not_admitted:
        DoctrineCompiler(quarantined_store).compile(
            _profile(), [_rule(quarantined_ref)], fact_catalog=FACTS
        )
    assert not_admitted.value.code == "RULE_SOURCE_NOT_ADMITTED"

    with pytest.raises(CompilationFailure) as unsupported:
        compiler.compile(
            _profile(),
            [
                _rule(
                    reference,
                    premises=[
                        {
                            "path": "invented.fact.path",
                            "operator": "exists",
                            "value": None,
                        }
                    ],
                )
            ],
            fact_catalog=FACTS,
        )
    assert unsupported.value.code == "FACT_PATH_UNSUPPORTED"


def test_compiler_output_is_deterministic_hashable_and_matches_typed_premises() -> None:
    store, reference = _store()
    first_rule = _rule(reference)
    second_rule = _rule(
        reference,
        rule_id="jaimini.identity.atmakaraka",
        topic="identity",
        premises=[
            {
                "path": "jaimini.karakas.AK.planet",
                "operator": "in",
                "value": ["Sun", "Moon"],
            }
        ],
        conclusion_template="Atmakaraka supports a bounded identity theme.",
    )
    compiler = DoctrineCompiler(store)
    forward = compiler.compile(
        _profile(), [first_rule, second_rule], fact_catalog=FACTS
    )
    reverse = compiler.compile(
        _profile(), [second_rule, first_rule], fact_catalog=FACTS
    )

    assert forward == reverse
    assert forward.compiled_profile_sha256 == reverse.compiled_profile_sha256
    assert [rule.rule_id for rule in forward.rules] == sorted(
        [first_rule.rule_id, second_rule.rule_id]
    )
    compiled_first = next(
        rule for rule in forward.executable_rules if rule.rule_id == first_rule.rule_id
    )
    assert compiled_first.matches({"jaimini.karakas.AmK.planet": "Mercury"})
    assert not compiled_first.matches({"jaimini.karakas.AmK.planet": "Venus"})


def test_compiler_rejects_missing_dependencies_cycles_and_confidence_escalation() -> (
    None
):
    store, reference = _store()
    compiler = DoctrineCompiler(store)

    with pytest.raises(CompilationFailure) as missing:
        compiler.compile(
            _profile(),
            [_rule(reference, depends_on=["missing.rule"])],
            fact_catalog=FACTS,
        )
    assert missing.value.code == "RULE_DEPENDENCY_MISSING"

    first = _rule(
        reference,
        rule_id="rule.first",
        depends_on=["rule.second"],
    )
    second = _rule(
        reference,
        rule_id="rule.second",
        depends_on=["rule.first"],
    )
    with pytest.raises(CompilationFailure) as cycle:
        compiler.compile(_profile(), [first, second], fact_catalog=FACTS)
    assert cycle.value.code == "RULE_DEPENDENCY_CYCLE"

    foundation = _rule(
        reference,
        rule_id="rule.foundation",
        confidence_ceiling=0.55,
    )
    inflated = _rule(
        reference,
        rule_id="rule.inflated",
        depends_on=["rule.foundation"],
        confidence_ceiling=0.80,
    )
    with pytest.raises(CompilationFailure) as escalation:
        compiler.compile(_profile(), [foundation, inflated], fact_catalog=FACTS)
    assert escalation.value.code == "RULE_CONFIDENCE_ESCALATION"


def test_supersession_and_conflict_remain_auditable_but_not_both_executable() -> None:
    store, reference = _store()
    original = _rule(reference, rule_id="rule.original")
    replacement = _rule(
        reference,
        rule_id="rule.replacement",
        supersedes=["rule.original"],
        conflicts_with=["rule.alternative"],
    )
    alternative = _rule(
        reference,
        rule_id="rule.alternative",
        conflicts_with=["rule.replacement"],
    )
    compiled = DoctrineCompiler(store).compile(
        _profile(), [alternative, original, replacement], fact_catalog=FACTS
    )

    assert {rule.rule_id for rule in compiled.rules} == {
        "rule.original",
        "rule.replacement",
        "rule.alternative",
    }
    assert {rule.rule_id for rule in compiled.executable_rules} == {
        "rule.replacement",
        "rule.alternative",
    }
    assert compiled.superseded_rule_ids == ("rule.original",)


def test_overlay_requires_explicit_matching_baseline_and_never_mutates_it() -> None:
    store, reference = _store()
    compiler = DoctrineCompiler(store)
    baseline = compiler.compile(_profile(), [_rule(reference)], fact_catalog=FACTS)
    overlay_profile = _profile(
        profile_id="jaimini_sanjay_rath_v1",
        school="sanjay_rath",
        profile_kind="overlay",
        base_profile_sha256=baseline.compiled_profile_sha256,
    )
    overlay_rule = _rule(
        reference,
        rule_id="jaimini.overlay.career",
        profile_id="jaimini_sanjay_rath_v1",
        school="sanjay_rath",
        conclusion_template="Named overlay adds a distinct symbolic theme.",
    )

    with pytest.raises(CompilationFailure) as implicit:
        compiler.compile(overlay_profile, [overlay_rule], fact_catalog=FACTS)
    assert implicit.value.code == "OVERLAY_BASE_REQUIRED"

    overlay = compiler.compile(
        overlay_profile,
        [overlay_rule],
        fact_catalog=FACTS,
        baseline=baseline,
    )
    assert overlay.layers == (
        (baseline.profile.profile_id, baseline.compiled_profile_sha256),
        (overlay_profile.profile_id, overlay.own_layer_sha256),
    )
    assert (
        baseline.rules
        == compiler.compile(_profile(), [_rule(reference)], fact_catalog=FACTS).rules
    )
    wrong_hash = overlay_profile.model_copy(update={"base_profile_sha256": "f" * 64})
    with pytest.raises(CompilationFailure) as substituted:
        compiler.compile(
            wrong_hash,
            [overlay_rule],
            fact_catalog=FACTS,
            baseline=baseline,
        )
    assert substituted.value.code == "OVERLAY_BASE_SUBSTITUTED"


def test_strict_models_reject_invalid_safety_and_unknown_fields() -> None:
    store, reference = _store()
    with pytest.raises(ValidationError):
        _rule(reference, safety_class="medical_prediction")
    with pytest.raises(ValidationError):
        FactPremise.model_validate(
            {"path": "x", "operator": "exists", "value": None, "extra": True}
        )
