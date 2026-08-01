from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from jyotish_agent.doctrine.ingestion import (
    PageBoundsPyPdfExtractor,
    PyPdfExtractor,
    _extract_anchors,
    _normalize_text,
)
from jyotish_agent.doctrine.jaimini_pack import (
    JaiminiOverlayFailure,
    JaiminiOverlayFragmentLedger,
    JaiminiOverlayRegistry,
    JaiminiRuleInventory,
    JaiminiRuleStatus,
    load_jaimini_overlay_activation_contract,
)
from jyotish_agent.doctrine.sources import load_source_manifest
from jyotish_agent.research_store import canonical_json


ROOT = Path(__file__).parents[2]
LEDGER_PATH = (
    ROOT / "src/jyotish_agent/data/doctrine/jaimini-overlay-fragments.json"
)
AUDIT_PATH = ROOT / "docs/evidence/doctrine/jaimini-overlay-fragments.json"
KN_LEDGER_PATH = (
    ROOT / "src/jyotish_agent/data/doctrine/jaimini-kn-rao-overlay-fragments.json"
)
KN_AUDIT_PATH = ROOT / "docs/evidence/doctrine/jaimini-kn-rao-ocr-review.json"
RELEASE_PATH = ROOT / "docs/evidence/doctrine/jaimini-release.json"
MANIFEST_PATH = ROOT / "src/jyotish_agent/data/doctrine/jaimini-sources.json"
INVENTORY_PATH = ROOT / "src/jyotish_agent/data/doctrine/jaimini-rules.json"
OVERLAYS_PATH = ROOT / "src/jyotish_agent/data/doctrine/jaimini-overlays.json"
CORE_PATH = ROOT / "src/jyotish_agent/data/jaimini/jaimini_core_v1.json"
UPADESA_SOURCE_ID = "jaimini_sanjay_rath_upadesa_sutras_1997"
NARAYANA_SOURCE_ID = "jaimini_sanjay_rath_narayana_dasa_2004"
KN_RAO_SOURCE_ID = "jaimini_kn_rao_chara_dasha_vani_scan_2010"


def _context_parts():
    return (
        load_source_manifest(MANIFEST_PATH),
        JaiminiRuleInventory.model_validate_json(
            INVENTORY_PATH.read_text(encoding="utf-8")
        ),
        JaiminiOverlayRegistry.model_validate_json(
            OVERLAYS_PATH.read_text(encoding="utf-8")
        ),
    )


def _activation_contract(ledger_path: Path = LEDGER_PATH):
    return load_jaimini_overlay_activation_contract(
        ledger_path=ledger_path,
        manifest_path=MANIFEST_PATH,
        baseline_inventory_path=INVENTORY_PATH,
        overlay_registry_path=OVERLAYS_PATH,
    )


def _ledger() -> JaiminiOverlayFragmentLedger:
    return _activation_contract().ledger


def _kn_ledger() -> JaiminiOverlayFragmentLedger:
    return _activation_contract(KN_LEDGER_PATH).ledger


def test_overlay_fragment_ledger_is_hash_bound_and_context_valid() -> None:
    ledger = _ledger()

    assert ledger.overlay_id == "sanjay_rath"
    assert ledger.school == "sanjay_rath"
    assert ledger.activation_status == "unavailable"
    assert ledger.doctrine_admitted is False
    assert ledger.product_rule_use_allowed is False
    assert len(ledger.fragments) >= 8
    assert len(ledger.bindings) >= 10
    assert {fragment.source_id for fragment in ledger.fragments} == {
        UPADESA_SOURCE_ID,
        NARAYANA_SOURCE_ID,
    }
    assert all(fragment.admission_status == "quarantined" for fragment in ledger.fragments)
    assert all(fragment.excerpt_permission == "none" for fragment in ledger.fragments)
    assert all(fragment.permitted_excerpt is None for fragment in ledger.fragments)


def test_kn_rao_overlay_fragment_ledger_is_separate_and_fail_closed() -> None:
    ledger = _kn_ledger()

    assert ledger.ledger_id == "jaimini_kn_rao_overlay_fragments_v1"
    assert ledger.overlay_id == "kn_rao_practical"
    assert ledger.school == "kn_rao_practical"
    assert ledger.unresolved_sources == ()
    assert {fragment.source_id for fragment in ledger.fragments} == {KN_RAO_SOURCE_ID}
    assert [fragment.page_number for fragment in ledger.fragments] == [
        32,
        35,
        39,
        40,
        43,
        44,
    ]
    assert [fragment.printed_page for fragment in ledger.fragments] == [
        33,
        36,
        40,
        41,
        44,
        45,
    ]
    assert all(fragment.school == "kn_rao_practical" for fragment in ledger.fragments)
    assert all(fragment.admission_status == "quarantined" for fragment in ledger.fragments)
    assert all(fragment.excerpt_permission == "none" for fragment in ledger.fragments)
    assert all(fragment.permitted_excerpt is None for fragment in ledger.fragments)
    assert all(
        binding.status == JaiminiRuleStatus.QUARANTINED_CONFLICT
        and binding.discrepancy
        for binding in ledger.bindings
    )
    assert {binding.rule_id for binding in ledger.bindings} == {
        "chara_dasha.progression",
        "chara_dasha.antardasha",
        "chara_dasha.duration",
        "co_lords.resolution",
    }
    assert ledger.activation_allowed is False
    with pytest.raises(JaiminiOverlayFailure) as raised:
        ledger.require_activation_ready()
    assert raised.value.code == "OVERLAY_FRAGMENT_LEDGER_QUARANTINED"


def test_overlay_bindings_cover_bounded_families_and_make_conflicts_explicit() -> None:
    ledger = _ledger()
    by_rule: dict[str, list[object]] = {}
    for binding in ledger.bindings:
        by_rule.setdefault(binding.rule_id, []).append(binding)

    assert {
        "rasi_drishti.modal_sign_aspects",
        "argala.houses",
        "argala.count_obstruction",
        "karakas.scheme",
        "karakas.rahu_reversal",
        "arudha.exception",
        "svamsa.d9_lagna",
        "karakamsa.d9_atmakaraka",
        "co_lords.resolution",
        "chara_dasha.progression",
        "chara_dasha.duration",
        "chara_dasha.antardasha",
    } <= set(by_rule)
    assert all(
        binding.status == JaiminiRuleStatus.QUARANTINED_CONFLICT
        and binding.discrepancy
        for rule_id in (
            "co_lords.resolution",
            "chara_dasha.progression",
            "chara_dasha.duration",
            "chara_dasha.antardasha",
        )
        for binding in by_rule[rule_id]
    )
    assert all(
        binding.status != JaiminiRuleStatus.ADMITTED
        for binding in ledger.bindings
    )


def test_quarantined_ledger_cannot_activate_or_compile_overlay() -> None:
    ledger = _ledger()

    assert ledger.activation_allowed is False
    with pytest.raises(JaiminiOverlayFailure) as raised:
        ledger.require_activation_ready()
    assert raised.value.code == "OVERLAY_FRAGMENT_LEDGER_QUARANTINED"


def test_fragment_and_binding_identities_fail_closed_on_substitution() -> None:
    payload = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    payload["fragments"][0]["full_text_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="fragment draft identity"):
        JaiminiOverlayFragmentLedger.model_validate(payload)

    payload = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    payload["bindings"][0]["paraphrase"] = "Substituted claim."
    with pytest.raises(ValueError, match="binding identity"):
        JaiminiOverlayFragmentLedger.model_validate(payload)


def test_overlay_ledger_identity_and_school_cannot_be_substituted() -> None:
    payload = json.loads(KN_LEDGER_PATH.read_text(encoding="utf-8"))
    payload["overlay_id"] = "sanjay_rath"
    with pytest.raises(ValueError, match="ledger identity"):
        JaiminiOverlayFragmentLedger.model_validate(payload)

    payload = json.loads(KN_LEDGER_PATH.read_text(encoding="utf-8"))
    payload["fragments"][0]["school"] = "sanjay_rath"
    with pytest.raises(ValueError, match="cannot blend schools"):
        JaiminiOverlayFragmentLedger.model_validate(payload)

    payload = json.loads(KN_LEDGER_PATH.read_text(encoding="utf-8"))
    payload.pop("unresolved_sources")
    with pytest.raises(ValueError, match="unresolved_sources"):
        JaiminiOverlayFragmentLedger.model_validate(payload)


def test_context_validation_rejects_page_offset_substitution() -> None:
    ledger = _ledger()
    manifest, inventory, registry = _context_parts()
    fragment = ledger.fragments[0].model_copy(update={"printed_page": 999})
    mutated = ledger.model_copy(
        update={"fragments": (fragment, *ledger.fragments[1:])}
    )

    with pytest.raises(ValueError, match="page coordinates"):
        mutated.validate_context(
            manifest=manifest,
            baseline_inventory=inventory,
            overlay_registry=registry,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("activation_status", "available", "unavailable quarantine state"),
        ("doctrine_admitted", True, "unavailable quarantine state"),
        ("product_rule_use_allowed", True, "unavailable quarantine state"),
        ("source_manifest_sha256", "0" * 64, "source manifest"),
        ("baseline_inventory_sha256", "0" * 64, "baseline inventory"),
    ],
)
def test_context_validation_rejects_release_identity_mutations(
    field: str, value: object, message: str
) -> None:
    ledger = _ledger()
    manifest, inventory, registry = _context_parts()
    mutated = ledger.model_copy(update={field: value})

    with pytest.raises(ValueError, match=message):
        mutated.validate_context(
            manifest=manifest,
            baseline_inventory=inventory,
            overlay_registry=registry,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "source_id",
            "jaimini_kn_rao_chara_dasha_vani_scan_2010",
            "named overlay",
        ),
        ("school", "kn_rao_practical", "cannot blend schools"),
    ],
)
def test_context_validation_rejects_fragment_identity_mutations(
    field: str, value: str, message: str
) -> None:
    ledger = _ledger()
    manifest, inventory, registry = _context_parts()
    fragment = ledger.fragments[0].model_copy(update={field: value})
    mutated = ledger.model_copy(
        update={"fragments": (fragment, *ledger.fragments[1:])}
    )

    with pytest.raises(ValueError, match=message):
        mutated.validate_context(
            manifest=manifest,
            baseline_inventory=inventory,
            overlay_registry=registry,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("rule_id", "unknown.overlay_rule", "unknown baseline rule"),
        ("status", JaiminiRuleStatus.ADMITTED, "must remain quarantined"),
    ],
)
def test_context_validation_rejects_binding_mutations(
    field: str, value: object, message: str
) -> None:
    ledger = _ledger()
    manifest, inventory, registry = _context_parts()
    binding = ledger.bindings[0].model_copy(update={field: value})
    mutated = ledger.model_copy(
        update={"bindings": (binding, *ledger.bindings[1:])}
    )

    with pytest.raises(ValueError, match=message):
        mutated.validate_context(
            manifest=manifest,
            baseline_inventory=inventory,
            overlay_registry=registry,
        )


def test_safe_loader_cannot_return_without_context_validation(tmp_path: Path) -> None:
    payload = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    payload["baseline_inventory_sha256"] = "0" * 64
    substituted = tmp_path / "substituted-ledger.json"
    substituted.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="baseline inventory"):
        load_jaimini_overlay_activation_contract(
            ledger_path=substituted,
            manifest_path=MANIFEST_PATH,
            baseline_inventory_path=INVENTORY_PATH,
            overlay_registry_path=OVERLAYS_PATH,
        )


def test_tracked_projection_contains_no_source_text_or_private_locator() -> None:
    ledger_payload = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    audit_payload = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    kn_ledger_payload = json.loads(KN_LEDGER_PATH.read_text(encoding="utf-8"))
    kn_audit_payload = json.loads(KN_AUDIT_PATH.read_text(encoding="utf-8"))
    rendered = json.dumps(
        {
            "ledger": ledger_payload,
            "audit": audit_payload,
            "kn_ledger": kn_ledger_payload,
            "kn_audit": kn_audit_payload,
        },
        sort_keys=True,
    ).casefold()

    assert "private_sources" not in rendered
    assert "/users/" not in rendered
    assert ".pdf" not in rendered
    assert "local_file" not in rendered
    assert "permitted_excerpt" in ledger_payload["fragments"][0]
    assert all(
        fragment["permitted_excerpt"] is None for fragment in ledger_payload["fragments"]
    )
    assert "text" not in ledger_payload
    assert "text" not in kn_ledger_payload
    assert "excerpt" not in kn_audit_payload


def test_reviewed_kn_rao_source_is_absent_from_unresolved_queues() -> None:
    assert _ledger().unresolved_sources == ()
    assert _kn_ledger().unresolved_sources == ()


def test_baseline_reassessment_updates_inventory_without_mutating_frozen_core() -> None:
    assert hashlib.sha256(INVENTORY_PATH.read_bytes()).hexdigest() == (
        "3cf4ed52580a14cf93cc6ac18dd259114c867c36a44eb16c220ecc3a53483dd0"
    )
    assert hashlib.sha256(CORE_PATH.read_bytes()).hexdigest() == (
        "ea5aea06b15b98df63ca32c290f4ebc7ae1d2d494171aa4730bb25c467dda5bb"
    )


def test_private_upadesa_pages_match_tracked_normalized_page_commitments() -> None:
    manifest = load_source_manifest(MANIFEST_PATH)
    source = next(
        item for item in manifest.sources if item.source_id == UPADESA_SOURCE_ID
    )
    private_path = ROOT / "private_sources" / source.local_file
    if not private_path.is_file():
        pytest.skip("private Upadesa source is unavailable in this checkout")

    extracted = PyPdfExtractor().extract(private_path)
    ledger = _ledger()
    for fragment in (
        item for item in ledger.fragments if item.source_id == UPADESA_SOURCE_ID
    ):
        text = _normalize_text(extracted[fragment.page_number - 1].text)
        anchors = _extract_anchors(text)
        page_payload = {
            "page_number": fragment.page_number,
            "printed_page": fragment.printed_page,
            "language": fragment.language,
            "text": text,
            "source_method": "embedded_text",
            "confidence": 1.0,
            "admission_status": "admitted",
            "anchors": [anchor.model_dump(mode="json") for anchor in anchors],
        }
        assert hashlib.sha256(text.encode("utf-8")).hexdigest() == (
            fragment.full_text_sha256
        )
        assert hashlib.sha256(canonical_json(page_payload).encode("utf-8")).hexdigest() == (
            fragment.normalized_content_sha256
        )


def test_private_narayana_pages_replay_crop_aware_commitments_without_duplicates() -> None:
    manifest = load_source_manifest(MANIFEST_PATH)
    source = next(
        item for item in manifest.sources if item.source_id == NARAYANA_SOURCE_ID
    )
    private_path = ROOT / "private_sources" / source.local_file
    if not private_path.is_file():
        pytest.skip("private Narayana source is unavailable in this checkout")

    bounded = PageBoundsPyPdfExtractor().extract(private_path)
    default = PyPdfExtractor().extract(private_path)
    ledger = _ledger()
    fragments = sorted(
        (
            fragment
            for fragment in ledger.fragments
            if fragment.source_id == NARAYANA_SOURCE_ID
        ),
        key=lambda fragment: fragment.page_number,
    )

    assert [fragment.page_number for fragment in fragments] == list(range(46, 54))
    assert [fragment.printed_page for fragment in fragments] == list(range(46, 54))
    bounded_hashes: list[str] = []
    for fragment in fragments:
        text = _normalize_text(bounded[fragment.page_number - 1].text)
        anchors = _extract_anchors(text)
        page_payload = {
            "page_number": fragment.page_number,
            "printed_page": fragment.printed_page,
            "language": fragment.language,
            "text": text,
            "source_method": "embedded_text",
            "confidence": 1.0,
            "admission_status": "admitted",
            "anchors": [anchor.model_dump(mode="json") for anchor in anchors],
        }
        page_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        bounded_hashes.append(page_hash)
        assert page_hash == fragment.full_text_sha256
        assert hashlib.sha256(canonical_json(page_payload).encode("utf-8")).hexdigest() == (
            fragment.normalized_content_sha256
        )

    assert len(set(bounded_hashes)) == 8
    assert _normalize_text(default[45].text) != _normalize_text(bounded[45].text)
    assert _normalize_text(default[46].text) != _normalize_text(bounded[46].text)
    assert _normalize_text(default[46].text) == _normalize_text(default[47].text)
    assert _normalize_text(bounded[46].text) != _normalize_text(bounded[47].text)


def test_private_kn_rao_pages_replay_reviewed_ocr_commitments() -> None:
    manifest = load_source_manifest(MANIFEST_PATH)
    source = next(item for item in manifest.sources if item.source_id == KN_RAO_SOURCE_ID)
    private_path = ROOT / "private_sources" / source.local_file
    if not private_path.is_file():
        pytest.skip("private K. N. Rao source is unavailable in this checkout")

    extracted = PyPdfExtractor().extract(private_path)
    ledger = _kn_ledger()
    for fragment in ledger.fragments:
        text = _normalize_text(extracted[fragment.page_number - 1].text)
        anchors = _extract_anchors(text)
        page_payload = {
            "page_number": fragment.page_number,
            "printed_page": fragment.printed_page,
            "language": fragment.language,
            "text": text,
            "source_method": "embedded_text",
            "confidence": 1.0,
            "admission_status": "admitted",
            "anchors": [anchor.model_dump(mode="json") for anchor in anchors],
        }
        assert hashlib.sha256(text.encode("utf-8")).hexdigest() == (
            fragment.full_text_sha256
        )
        assert hashlib.sha256(canonical_json(page_payload).encode("utf-8")).hexdigest() == (
            fragment.normalized_content_sha256
        )


def test_kn_rao_ocr_review_audit_is_hash_bound_and_not_an_admission() -> None:
    ledger = _kn_ledger()
    audit = json.loads(KN_AUDIT_PATH.read_text(encoding="utf-8"))
    manifest = load_source_manifest(MANIFEST_PATH)
    source = next(item for item in manifest.sources if item.source_id == KN_RAO_SOURCE_ID)

    assert audit["source_id"] == KN_RAO_SOURCE_ID
    assert audit["source_file_sha256"] == source.sha256
    assert audit["source_manifest_sha256"] == manifest.manifest_sha256
    assert audit["ledger_sha256"] == ledger.ledger_sha256
    assert all(
        page["agent_visual_review"] == "passed"
        for page in audit["reviewed_pages"]
    )
    assert [page["pdf_page"] for page in audit["reviewed_pages"]] == [
        32,
        35,
        39,
        40,
        43,
        44,
    ]
    assert all(page["tesseract_confidence"] >= 0.80 for page in audit["reviewed_pages"])
    assert all(page["token_sequence_ratio"] >= 0.80 for page in audit["reviewed_pages"])
    assert audit["doctrine_admitted"] is False
    assert audit["product_rule_use_allowed"] is False
    assert audit["specialist_review_missing"] is True


def test_privacy_safe_audit_is_bound_to_ledger_and_preserves_release_blockers() -> None:
    ledger = _ledger()
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    release = json.loads(RELEASE_PATH.read_text(encoding="utf-8"))

    assert audit["ledger_sha256"] == ledger.ledger_sha256
    assert audit["source_manifest_sha256"] == ledger.source_manifest_sha256
    assert audit["baseline_inventory_sha256"] == ledger.baseline_inventory_sha256
    assert audit["fragment_source_ids"] == sorted(
        {fragment.source_id for fragment in ledger.fragments}
    )
    assert audit["normalized_pages"] == sorted(
        [
            {
                "source_id": fragment.source_id,
                "page_number": fragment.page_number,
                "printed_page": fragment.printed_page,
            }
            for fragment in ledger.fragments
        ],
        key=lambda item: (item["source_id"], item["page_number"]),
    )
    assert audit["fragment_count"] == len(ledger.fragments)
    assert audit["binding_count"] == len(ledger.bindings)
    assert audit["anchored_unreviewed_binding_count"] == sum(
        binding.status == JaiminiRuleStatus.ANCHORED_UNREVIEWED
        for binding in ledger.bindings
    )
    assert audit["conflict_binding_count"] == sum(
        binding.status == JaiminiRuleStatus.QUARANTINED_CONFLICT
        for binding in ledger.bindings
    )
    assert audit["admitted_binding_count"] == sum(
        binding.status == JaiminiRuleStatus.ADMITTED for binding in ledger.bindings
    )
    assert audit["unresolved_sources"] == [
        {
            "source_id": item.source_id,
            "blocker_code": item.blocker_code,
        }
        for item in ledger.unresolved_sources
    ]
    assert audit["doctrine_admitted"] == ledger.doctrine_admitted
    assert audit["product_rule_use_allowed"] == ledger.product_rule_use_allowed
    assert audit["release_id"] == release["release_id"]
    assert audit["release_evidence_sha256"] == hashlib.sha256(
        RELEASE_PATH.read_bytes()
    ).hexdigest()
    assert audit["release_admission_state"] == release["admission_state"]
    assert audit["release_promoted"] == release["available"]
    assert audit["overlay_activated"] == ledger.activation_allowed
    expected_release_blockers = sorted(
        [
            f"gate:{gate['gate_id']}"
            for gate in release["gates"]
            if gate["status"] == "missing"
        ]
        + [
            f"blocker:{blocker.split(':', 1)[0]}"
            for blocker in (
                release["blockers"] + release.get("public_release_blockers", [])
            )
        ]
    )
    assert audit["preserved_release_blockers"] == expected_release_blockers
