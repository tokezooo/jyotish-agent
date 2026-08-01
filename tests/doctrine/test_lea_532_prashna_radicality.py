from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from jyotish_agent.doctrine.prashna_pack import (
    PrashnaRadicalityInput,
    PrashnaRadicalityProfile,
    evaluate_prashna_radicality,
)
from jyotish_agent.doctrine.ingestion import (
    DocumentIngestor,
    IngestionConfig,
    PyPdfExtractor,
)
from jyotish_agent.doctrine.sources import load_source_manifest


ROOT = Path(__file__).parents[2]
RULES = ROOT / "src/jyotish_agent/data/doctrine/prashna-rules.json"
MANIFEST = ROOT / "src/jyotish_agent/data/doctrine/prashna-sources.json"
AUDIT = ROOT / "docs/evidence/doctrine/prashna-radicality-fragment-review.json"


def _profile() -> PrashnaRadicalityProfile:
    return PrashnaRadicalityProfile.model_validate_json(RULES.read_text())


def _input(**updates: object) -> PrashnaRadicalityInput:
    payload = {
        "anchor_state": "sealed",
        "question_relation": "new_anchor",
        "topic_state": "single_safe",
        "question_form": "proper",
        "intent_state": "sincere",
        "sources_admitted": True,
    }
    payload.update(updates)
    return PrashnaRadicalityInput.model_validate(payload)


def test_every_criterion_has_an_exact_source_page_hash_and_baseline_identity() -> None:
    profile = _profile()
    assert profile.school == "prasna_marga_baseline"
    assert profile.profile_kind == "baseline"
    assert profile.overlay_profile_id is None
    assert {criterion.criterion_id for criterion in profile.criteria} == {
        "anchor_exact",
        "question_not_test",
        "question_once",
        "question_proper_form",
    }
    for criterion in profile.criteria:
        assert criterion.source_id
        assert criterion.pdf_page >= 1
        assert criterion.printed_page >= 1
        assert len(criterion.page_sha256) == 64
        assert 0 <= criterion.fragment_start_offset < criterion.fragment_end_offset
        assert len(criterion.fragment_text_sha256) == 64
        assert criterion.fragment_word_count >= 1
        assert criterion.fragment_normalization == "whitespace_collapse_v1"
        assert criterion.admission_status == "private_experimental"
        assert criterion.specialist_review_status == "missing"


def test_exact_page_hashes_replay_against_private_sources_when_available() -> None:
    manifest = load_source_manifest(MANIFEST)
    private_root = ROOT / "private_sources"
    by_id = {source.source_id: source for source in manifest.sources}
    if not all(
        (private_root / by_id[item.source_id].local_file).exists()
        for item in _profile().criteria
    ):
        return
    ingestor = DocumentIngestor(extractor=PyPdfExtractor(), renderer=None, ocr=None)
    artifacts = {}
    for source_id in {item.source_id for item in _profile().criteria}:
        source = by_id[source_id]
        artifacts[source_id] = ingestor.ingest(
            source,
            root=private_root,
            config=IngestionConfig(languages=source.languages),
        )
    for criterion in _profile().criteria:
        pages = {
            page.page_number: page for page in artifacts[criterion.source_id].pages
        }
        assert pages[criterion.pdf_page].normalized_sha256 == criterion.page_sha256
        page_text = pages[criterion.pdf_page].text
        fragment = " ".join(
            page_text[
                criterion.fragment_start_offset : criterion.fragment_end_offset
            ].split()
        )
        assert hashlib.sha256(fragment.encode("utf-8")).hexdigest() == (
            criterion.fragment_text_sha256
        )
        assert len(fragment.split()) == criterion.fragment_word_count


def test_fragment_review_audit_matches_profile_without_tracking_source_text() -> None:
    profile = _profile()
    manifest = load_source_manifest(MANIFEST)
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))

    assert audit["source_manifest_sha256"] == manifest.manifest_sha256
    assert audit["profile_sha256"] == hashlib.sha256(RULES.read_bytes()).hexdigest()
    assert audit["criterion_ids"] == sorted(
        criterion.criterion_id for criterion in profile.criteria
    )
    assert audit["tracked_source_text"] is False
    assert audit["admission_state"] == "private_experimental"
    assert audit["product_rule_use_allowed"] == "safe_low_risk_only"
    assert audit["external_specialist_review_missing"] is True


def test_radicality_profile_rejects_non_admitted_or_unbounded_fragments() -> None:
    payload = json.loads(RULES.read_text(encoding="utf-8"))
    payload["criteria"][0]["admission_status"] = "quarantined"
    with pytest.raises(ValidationError, match="admission_status"):
        PrashnaRadicalityProfile.model_validate(payload)

    payload = json.loads(RULES.read_text(encoding="utf-8"))
    payload["criteria"][0]["fragment_end_offset"] = payload["criteria"][0][
        "fragment_start_offset"
    ]
    with pytest.raises(ValidationError, match="fragment offsets"):
        PrashnaRadicalityProfile.model_validate(payload)


def test_readable_bounded_clarification_preserves_sealed_anchor() -> None:
    result = evaluate_prashna_radicality(
        _input(question_relation="bounded_clarification"), _profile()
    )
    assert result.status == "readable"
    assert result.outcome_allowed is True
    assert result.anchor_action == "reuse_sealed_anchor"
    assert result.confidence_ceiling == 0.65
    assert result.source_refs
    assert all(":fragment:sha256:" in ref for ref in result.source_refs)


def test_repeated_question_is_conflicting_and_cannot_produce_outcome() -> None:
    result = evaluate_prashna_radicality(
        _input(question_relation="exact_duplicate"), _profile()
    )
    assert result.status == "conflicting"
    assert result.outcome_allowed is False
    assert result.anchor_action == "reuse_sealed_anchor"
    assert result.reason_codes == ("QUESTION_REPEATED",)


def test_composite_stale_and_materially_changed_questions_are_unavailable() -> None:
    composite = evaluate_prashna_radicality(_input(topic_state="composite"), _profile())
    stale = evaluate_prashna_radicality(_input(anchor_state="stale"), _profile())
    changed = evaluate_prashna_radicality(
        _input(question_relation="material_mismatch"), _profile()
    )
    assert composite.status == stale.status == changed.status == "unavailable"
    assert composite.anchor_action == "require_single_question"
    assert stale.anchor_action == "create_new_anchor"
    assert changed.anchor_action == "create_new_anchor"
    assert not composite.outcome_allowed


def test_missing_source_admission_fails_closed_without_private_input_reflection() -> (
    None
):
    secret = "secret-place-and-question"
    result = evaluate_prashna_radicality(_input(sources_admitted=False), _profile())
    rendered = json.dumps(result.model_dump(mode="json"), sort_keys=True)
    assert result.status == "unavailable"
    assert result.reason_codes == ("SOURCE_ADMISSION_MISSING",)
    assert secret not in rendered
    assert "question" not in rendered.casefold()


def test_named_overlay_cannot_be_smuggled_into_baseline_profile() -> None:
    payload = _profile().model_dump(mode="json")
    payload["overlay_profile_id"] = "tajika_nilakanthi_overlay_v1"
    try:
        PrashnaRadicalityProfile.model_validate(payload)
    except ValueError as exc:
        assert "baseline" in str(exc).casefold()
    else:
        raise AssertionError("baseline accepted a hidden overlay")
