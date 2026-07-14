"""Private source-manifest contract and privacy-safe verification."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from ..research_store import canonical_json
from .models import (
    DoctrineDomain,
    FrozenModel,
    LicenseClass,
    OcrStatus,
    ScanQuality,
    SchoolRole,
)


NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
SourceId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=96,
        pattern=r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$",
    ),
]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
LanguageCode = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[a-z]{2,3}(?:-[A-Z]{2})?$")
]


class SourceRecord(FrozenModel):
    """Bibliographic identity plus a local-only file commitment."""

    source_id: SourceId
    title: NonEmpty
    author_or_commentator: NonEmpty
    translator_editor: NonEmpty | None = None
    edition: NonEmpty
    publisher: NonEmpty | None = None
    year: int = Field(ge=1, le=3000)
    isbn: NonEmpty | None = None
    languages: tuple[LanguageCode, ...] = Field(min_length=1)
    domain: DoctrineDomain
    school_role: SchoolRole
    license_class: LicenseClass
    local_file: Path
    sha256: Sha256
    page_offset: int = Field(ge=-10_000, le=10_000)
    scan_quality: ScanQuality
    ocr_required: bool
    ocr_status: OcrStatus

    @field_validator("languages")
    @classmethod
    def _unique_languages(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("languages must be unique")
        return value

    @field_validator("local_file", mode="before")
    @classmethod
    def _safe_relative_file(cls, value: object) -> Path:
        if not isinstance(value, (str, os.PathLike)):
            raise ValueError("local_file must be a relative path")
        raw = os.fspath(value)
        if not raw or "\\" in raw or re.match(r"^[A-Za-z]:", raw):
            raise ValueError("local_file must use a relative POSIX-style path")
        path = Path(raw)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("local_file must stay below the private source root")
        return path

    @model_validator(mode="after")
    def _consistent_ocr_contract(self) -> "SourceRecord":
        if not self.ocr_required and self.ocr_status != OcrStatus.NOT_REQUIRED:
            raise ValueError("ocr_status must be not_required when OCR is disabled")
        if self.ocr_required and self.ocr_status == OcrStatus.NOT_REQUIRED:
            raise ValueError("ocr_required sources cannot use not_required status")
        return self


class SourceManifest(FrozenModel):
    """Versioned, canonically addressed private-source inventory."""

    schema_version: Literal["1.0"]
    sources: tuple[SourceRecord, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unambiguous_inventory(self) -> "SourceManifest":
        ids: set[str] = set()
        editions: set[tuple[str, str, str]] = set()
        for source in self.sources:
            if source.source_id in ids:
                raise ValueError(f"duplicate source_id: {source.source_id}")
            ids.add(source.source_id)
            identity = (
                source.domain.value,
                " ".join(source.title.casefold().split()),
                " ".join(source.edition.casefold().split()),
            )
            if identity in editions:
                raise ValueError("duplicate edition identity")
            editions.add(identity)
        return self

    @property
    def manifest_sha256(self) -> str:
        payload = self.model_dump(mode="json")
        payload["sources"] = sorted(payload["sources"], key=lambda item: item["source_id"])
        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


class SourceVerificationFinding(FrozenModel):
    code: Literal[
        "SOURCE_FILE_MISSING",
        "SOURCE_HASH_MISMATCH",
        "SOURCE_PATH_UNSAFE",
        "SOURCE_NOT_REGULAR_FILE",
    ]
    source_id: SourceId
    message: NonEmpty


class SourceVerificationReport(FrozenModel):
    manifest_sha256: Sha256
    verified_source_ids: tuple[SourceId, ...]
    findings: tuple[SourceVerificationFinding, ...]

    @property
    def ok(self) -> bool:
        return not self.findings


def load_source_manifest(path: Path) -> SourceManifest:
    """Load a strict JSON manifest without accepting duplicate JSON keys."""

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    raw = Path(path).read_text(encoding="utf-8")
    payload = json.loads(raw, object_pairs_hook=reject_duplicate_keys)
    return SourceManifest.model_validate(payload)


class SourceVerifier:
    """Verify local files while emitting no local paths or file content."""

    @staticmethod
    def verify(manifest: SourceManifest, root: Path) -> SourceVerificationReport:
        root = Path(root)
        findings: list[SourceVerificationFinding] = []
        verified: list[str] = []
        root_is_unsafe = root.is_symlink()
        root_resolved = root.resolve(strict=False)

        for source in sorted(manifest.sources, key=lambda item: item.source_id):
            candidate = root / source.local_file
            code: str | None = None
            message: str | None = None

            if root_is_unsafe or SourceVerifier._has_symlink_component(root, source.local_file):
                code = "SOURCE_PATH_UNSAFE"
                message = "Source path is not a safe child of the configured private root."
            else:
                try:
                    candidate.resolve(strict=False).relative_to(root_resolved)
                except ValueError:
                    code = "SOURCE_PATH_UNSAFE"
                    message = "Source path escapes the configured private root."

            if code is None and not candidate.exists():
                code = "SOURCE_FILE_MISSING"
                message = "Required local source file is missing."
            elif code is None and (candidate.is_symlink() or not candidate.is_file()):
                code = "SOURCE_NOT_REGULAR_FILE"
                message = "Source must be a regular non-symlink file."
            elif code is None:
                digest = SourceVerifier._sha256_file(candidate)
                if digest != source.sha256:
                    code = "SOURCE_HASH_MISMATCH"
                    message = "Source bytes do not match the committed manifest hash."

            if code is None:
                verified.append(source.source_id)
            else:
                findings.append(
                    SourceVerificationFinding(
                        code=code,
                        source_id=source.source_id,
                        message=message or "Source verification failed.",
                    )
                )

        return SourceVerificationReport(
            manifest_sha256=manifest.manifest_sha256,
            verified_source_ids=tuple(verified),
            findings=tuple(findings),
        )

    @staticmethod
    def _has_symlink_component(root: Path, relative: Path) -> bool:
        current = root
        if current.is_symlink():
            return True
        for part in relative.parts:
            current = current / part
            if os.path.lexists(current) and current.is_symlink():
                return True
        return False

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
