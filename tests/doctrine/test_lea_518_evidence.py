from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import ValidationError

from jyotish_agent.doctrine.evidence import (
    EvidenceFailure,
    EvidenceStore,
    FragmentDraft,
    FragmentRef,
)
from jyotish_agent.doctrine.sources import SourceManifest
from jyotish_agent.research_store import canonical_json


def _manifest(**updates: object) -> SourceManifest:
    source: dict[str, object] = {
        "source_id": "jaimini_subodhini_v1",
        "title": "Nilakantha Subodhini fixture",
        "author_or_commentator": "Nilakantha",
        "translator_editor": "Fixture editor",
        "edition": "Fixture edition 1",
        "publisher": "Fixture publisher",
        "year": 2026,
        "isbn": None,
        "languages": ["sa", "en"],
        "domain": "jaimini",
        "school_role": "baseline",
        "license_class": "copyrighted_local",
        "local_file": "jaimini/subodhini/fixture.pdf",
        "sha256": hashlib.sha256(b"source-v1").hexdigest(),
        "page_offset": 0,
        "scan_quality": "good",
        "ocr_required": False,
        "ocr_status": "not_required",
    }
    source.update(updates)
    return SourceManifest.model_validate(
        {"schema_version": "1.0", "sources": [source]}
    )


def _draft(manifest: SourceManifest, **updates: object) -> FragmentDraft:
    text = str(updates.pop("text", "Career indications require contextual reading."))
    payload: dict[str, object] = {
        "source_id": "jaimini_subodhini_v1",
        "source_manifest_sha256": manifest.manifest_sha256,
        "page_number": 10,
        "printed_page": 10,
        "anchor_kind": "sutra",
        "anchor_label": "1.2.3",
        "language": "en",
        "content_role": "commentary",
        "school": "nilakantha_subodhini",
        "scope": "career",
        "full_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "normalized_content_sha256": hashlib.sha256(text.strip().encode()).hexdigest(),
        "excerpt_permission": "short_quote",
        "permitted_excerpt": text,
        "admission_status": "admitted",
    }
    payload.update(updates)
    return FragmentDraft.model_validate(payload)


def test_append_is_idempotent_but_content_mutation_creates_immutable_revision() -> None:
    manifest = _manifest()
    store = EvidenceStore(manifest)
    first = store.append(_draft(manifest))
    duplicate = store.append(_draft(manifest))
    changed = store.append(_draft(manifest, text="A revised contextual reading."))

    assert duplicate == first
    assert first.revision == 1
    assert changed.fragment_id == first.fragment_id
    assert changed.revision == 2
    assert first.permitted_excerpt == "Career indications require contextual reading."
    assert store.resolve(FragmentRef.from_fragment(first)) == first
    assert store.resolve(FragmentRef.from_fragment(changed)) == changed
    supersession = [item for item in store.relations if item.relation_type == "supersedes"]
    assert len(supersession) == 1
    assert supersession[0].source.revision == 2
    assert supersession[0].target.revision == 1


def test_every_fragment_binds_to_current_manifest_and_known_source() -> None:
    manifest = _manifest()
    store = EvidenceStore(manifest)
    substituted = _manifest(page_offset=3)

    with pytest.raises(EvidenceFailure) as raised:
        store.append(
            _draft(manifest).model_copy(
                update={"source_manifest_sha256": substituted.manifest_sha256}
            )
        )
    assert raised.value.code == "SOURCE_MANIFEST_SUBSTITUTED"

    with pytest.raises(EvidenceFailure) as unknown:
        store.append(_draft(manifest).model_copy(update={"source_id": "unknown_source"}))
    assert unknown.value.code == "SOURCE_UNKNOWN"


def test_conflicting_commentaries_coexist_without_hidden_merging() -> None:
    manifest = _manifest()
    store = EvidenceStore(manifest)
    root = store.append(
        _draft(
            manifest,
            anchor_label="1.2.3-root",
            content_role="root_text",
            school="jaimini_sutra",
            scope="career",
            excerpt_permission="none",
            permitted_excerpt=None,
        )
    )
    translation = store.append(
        _draft(
            manifest,
            anchor_label="1.2.3-translation",
            content_role="translation",
            school="fixture_translation",
            text="The translation permits a career reading.",
        )
    )
    first = store.append(
        _draft(
            manifest,
            anchor_label="1.2.3-comment-a",
            school="school_a",
            text="Career visibility is emphasized.",
        )
    )
    second = store.append(
        _draft(
            manifest,
            anchor_label="1.2.3-comment-b",
            school="school_b",
            text="Career visibility is not emphasized.",
        )
    )
    store.relate(translation, root, "translation_of", scope="1.2.3")
    store.relate(first, translation, "commentary_on", scope="career")
    store.relate(second, translation, "commentary_on", scope="career")
    store.relate(first, second, "contradicts", scope="career")

    results = store.lookup("career", limit=10, projection="public")
    excerpts = {item.permitted_excerpt for item in results}
    assert "Career visibility is emphasized." in excerpts
    assert "Career visibility is not emphasized." in excerpts
    assert first.fragment_id != second.fragment_id
    assert any(item.relation_type == "contradicts" for item in store.relations)


def test_public_lookup_is_bounded_and_never_returns_paths_hashes_ids_or_full_text() -> None:
    manifest = _manifest()
    store = EvidenceStore(manifest)
    admitted = store.append(_draft(manifest))
    store.append(
        _draft(
            manifest,
            anchor_label="1.2.4",
            text="Quarantined career wording.",
            admission_status="quarantined",
        )
    )
    public = store.lookup("career", limit=1, projection="public")
    assert len(public) == 1
    payload = json.dumps(public[0].model_dump(mode="json"), sort_keys=True)
    for secret in (
        admitted.fragment_id,
        admitted.revision_sha256,
        admitted.full_text_sha256,
        "fixture.pdf",
        "private_sources",
    ):
        assert secret not in payload
    assert "Career indications require contextual reading." in payload
    with pytest.raises(ValueError, match="limit"):
        store.lookup("career", limit=0, projection="public")
    with pytest.raises(ValueError, match="limit"):
        store.lookup("career", limit=101, projection="public")


def test_inspection_projection_and_resolution_detect_stale_or_substituted_refs() -> None:
    manifest = _manifest()
    store = EvidenceStore(manifest)
    first = store.append(_draft(manifest))
    second = store.append(_draft(manifest, text="Revised career commentary."))

    inspected = store.lookup("career", limit=10, projection="inspection")
    assert {(item.fragment_id, item.revision) for item in inspected} == {
        (first.fragment_id, 1),
        (second.fragment_id, 2),
    }
    with pytest.raises(EvidenceFailure) as stale:
        store.resolve(FragmentRef.from_fragment(first), require_current=True)
    assert stale.value.code == "SOURCE_FRAGMENT_STALE"

    substituted = FragmentRef(
        fragment_id=second.fragment_id,
        revision=second.revision,
        revision_sha256="f" * 64,
    )
    with pytest.raises(EvidenceFailure) as wrong_hash:
        store.resolve(substituted)
    assert wrong_hash.value.code == "SOURCE_FRAGMENT_SUBSTITUTED"


def test_export_contains_only_permitted_material_and_is_deterministic() -> None:
    manifest = _manifest()
    store = EvidenceStore(manifest)
    store.append(_draft(manifest))
    store.append(
        _draft(
            manifest,
            anchor_label="1.2.5",
            content_role="root_text",
            school="jaimini_sutra",
            excerpt_permission="none",
            permitted_excerpt=None,
            text="COPYRIGHTED FULL TEXT MUST NOT EXPORT",
        )
    )
    first = store.export_permitted()
    second = store.export_permitted()
    assert first == second
    encoded = canonical_json(first)
    assert "Career indications require contextual reading." in encoded
    assert "COPYRIGHTED FULL TEXT MUST NOT EXPORT" not in encoded
    assert "local_file" not in encoded
    assert "fixture.pdf" not in encoded
    assert first["store_sha256"] == store.store_sha256


def test_short_quote_permission_has_a_hard_length_ceiling() -> None:
    manifest = _manifest()
    with pytest.raises(ValidationError, match="600"):
        _draft(manifest, text="x" * 601)


def test_rule_compilation_catalog_contains_only_current_admitted_refs() -> None:
    manifest = _manifest()
    store = EvidenceStore(manifest)
    old = store.append(_draft(manifest))
    current = store.append(_draft(manifest, text="Current admitted commentary."))
    store.append(
        _draft(
            manifest,
            anchor_label="1.2.6",
            text="Quarantined commentary.",
            admission_status="quarantined",
        )
    )

    catalog = store.admitted_catalog(limit=10)
    assert catalog == (FragmentRef.from_fragment(current),)
    assert FragmentRef.from_fragment(old) not in catalog
    with pytest.raises(ValueError, match="limit"):
        store.admitted_catalog(limit=0)
