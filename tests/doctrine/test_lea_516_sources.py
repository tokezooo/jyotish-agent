from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from jyotish_agent.doctrine.sources import (
    SourceManifest,
    SourceRecord,
    SourceVerifier,
    load_source_manifest,
)


ROOT = Path(__file__).parents[2]
EXAMPLES = ROOT / "src/jyotish_agent/data/doctrine/example-sources.json"


def _record(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "source_id": "jaimini_subodhini_2025",
        "title": "Nilakantha's Subodhini",
        "author_or_commentator": "Neelakantha",
        "translator_editor": "Example editor",
        "edition": "Example edition 1",
        "publisher": "Example publisher",
        "year": 2025,
        "isbn": "example-only",
        "languages": ["sa", "en"],
        "domain": "jaimini",
        "school_role": "baseline",
        "license_class": "copyrighted_local",
        "local_file": "jaimini/subodhini/example.pdf",
        "sha256": hashlib.sha256(b"fixture source bytes").hexdigest(),
        "page_offset": 0,
        "scan_quality": "good",
        "ocr_required": True,
        "ocr_status": "required",
    }
    payload.update(updates)
    return payload


def _manifest(*records: dict[str, object]) -> SourceManifest:
    return SourceManifest.model_validate(
        {"schema_version": "1.0", "sources": list(records)}
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_id", "ambiguous id"),
        ("title", ""),
        ("edition", ""),
        ("languages", []),
        ("sha256", "not-a-digest"),
        ("local_file", "/tmp/book.pdf"),
        ("local_file", "../book.pdf"),
        ("year", 0),
    ],
)
def test_source_record_rejects_incomplete_or_unsafe_fields(
    field: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        SourceRecord.model_validate(_record(**{field: value}))

    with pytest.raises(ValidationError):
        SourceRecord.model_validate({**_record(), "unexpected": True})


def test_source_record_rejects_inconsistent_ocr_contract() -> None:
    with pytest.raises(ValidationError, match="ocr_status"):
        SourceRecord.model_validate(_record(ocr_required=False, ocr_status="required"))
    with pytest.raises(ValidationError, match="ocr_required"):
        SourceRecord.model_validate(
            _record(ocr_required=True, ocr_status="not_required")
        )


def test_manifest_rejects_duplicate_ids_and_ambiguous_editions() -> None:
    first = _record()
    with pytest.raises(ValidationError, match="duplicate source_id"):
        _manifest(first, first)

    same_edition = _record(
        source_id="jaimini_subodhini_duplicate",
        local_file="jaimini/subodhini/duplicate.pdf",
    )
    with pytest.raises(ValidationError, match="duplicate edition identity"):
        _manifest(first, same_edition)


def test_verifier_reports_missing_and_hash_drift_deterministically_without_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "private_sources"
    root.mkdir()
    present = root / "jaimini" / "subodhini" / "example.pdf"
    present.parent.mkdir(parents=True)
    present.write_bytes(b"different bytes")
    manifest = _manifest(
        _record(),
        _record(
            source_id="prashna_marga_example",
            title="Prasna Marga example",
            edition="Example edition 2",
            languages=["sa", "en"],
            domain="prashna",
            local_file="prashna/prasna-marga/example.pdf",
        ),
    )

    first = SourceVerifier.verify(manifest, root)
    second = SourceVerifier.verify(manifest, root)

    assert first == second
    assert [finding.code for finding in first.findings] == [
        "SOURCE_HASH_MISMATCH",
        "SOURCE_FILE_MISSING",
    ]
    rendered = json.dumps(first.model_dump(mode="json"), sort_keys=True)
    assert str(tmp_path) not in rendered
    assert "private_sources" not in rendered
    assert "example.pdf" not in rendered
    assert "different bytes" not in rendered


def test_verifier_accepts_matching_files_and_rejects_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "private_sources"
    source = root / "jaimini" / "subodhini" / "example.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"fixture source bytes")
    manifest = _manifest(_record())

    report = SourceVerifier.verify(manifest, root)
    assert report.findings == ()
    assert report.verified_source_ids == ("jaimini_subodhini_2025",)

    source.unlink()
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"fixture source bytes")
    source.symlink_to(outside)
    unsafe = SourceVerifier.verify(manifest, root)
    assert [finding.code for finding in unsafe.findings] == ["SOURCE_PATH_UNSAFE"]


def test_manifest_identity_is_order_independent_and_changes_with_metadata() -> None:
    jaimini = _record()
    prashna = _record(
        source_id="prashna_marga_example",
        title="Prasna Marga example",
        edition="Example edition 2",
        domain="prashna",
        local_file="prashna/prasna-marga/example.pdf",
    )
    forward = _manifest(jaimini, prashna)
    reverse = _manifest(prashna, jaimini)
    changed = _manifest(jaimini, {**prashna, "page_offset": 12})

    assert forward.manifest_sha256 == reverse.manifest_sha256
    assert forward.manifest_sha256 != changed.manifest_sha256


def test_tracked_examples_cover_required_domains_and_school_roles() -> None:
    manifest = load_source_manifest(EXAMPLES)
    assert {
        (source.domain.value, source.school_role.value) for source in manifest.sources
    } >= {
        ("jaimini", "baseline"),
        ("jaimini", "overlay"),
        ("prashna", "baseline"),
        ("muhurta", "baseline"),
    }
    assert all(
        source.local_file.parts[0] == source.domain.value for source in manifest.sources
    )


def test_private_source_root_is_lfs_tracked_and_runtime_packages_remain_clean() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "private_sources/" not in gitignore
    assert "private_sources/**/*.pdf filter=lfs" in attributes
    assert "private_sources/**/*.doc filter=lfs" in attributes
    for protected_path in (
        "private_sources/**/.env",
        "private_sources/**/.venv/",
        "private_sources/**/.git/",
        "private_sources/**/profiles/",
        "private_sources/**/*.sqlite",
        "private_sources/**/*.log",
        "private_sources/**/output/",
        "private_sources/**/tmp/",
    ):
        assert protected_path in gitignore
    packaged = ROOT / "src/jyotish_agent"
    assert list(packaged.rglob("*.pdf")) == []
    assert list((ROOT / "tests").rglob("*.pdf")) == []
