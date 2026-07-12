"""Governed corpus normalization and manifest loading."""

from __future__ import annotations

import json
import hashlib
import re
import unicodedata
from pathlib import Path
from typing import Any

from .research_store import canonical_json


_SOURCE_MANIFEST_FIELDS = (
    "source_version_id",
    "work_id",
    "title",
    "source_class",
    "language",
    "edition",
    "provenance_url",
    "rights_note",
)
_FRAGMENT_MANIFEST_FIELDS = (
    "fragment_id",
    "ordinal",
    "locator",
    "text",
    "transliteration_aliases",
    "checksum",
)


def normalize_search_text(value: str) -> str:
    """Normalize Unicode transliteration to a conservative FTS alias form."""
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_like = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^\w]+", " ", ascii_like.casefold(), flags=re.UNICODE).strip()


def builtin_manifest_path() -> Path:
    return Path(__file__).with_name("data") / "corpus_manifest.json"


def canonical_manifest_payload(
    source: dict[str, Any], fragments: list[dict[str, Any]]
) -> dict[str, Any]:
    """Select and order exactly the immutable fields covered by a manifest hash."""
    selected_fragments = [
        {field: fragment[field] for field in _FRAGMENT_MANIFEST_FIELDS}
        for fragment in fragments
    ]
    selected_fragments.sort(key=lambda item: (item["ordinal"], item["fragment_id"]))
    return {
        **{field: source[field] for field in _SOURCE_MANIFEST_FIELDS},
        "fragments": selected_fragments,
    }


def canonical_manifest_checksum(
    source: dict[str, Any], fragments: list[dict[str, Any]]
) -> str:
    return hashlib.sha256(
        canonical_json(canonical_manifest_payload(source, fragments)).encode("utf-8")
    ).hexdigest()


def load_builtin_manifest() -> dict[str, Any]:
    manifest = json.loads(builtin_manifest_path().read_text(encoding="utf-8"))
    for source in manifest["sources"]:
        for fragment in source["fragments"]:
            fragment["checksum"] = hashlib.sha256(
                fragment["text"].encode("utf-8")
            ).hexdigest()
        source["manifest_checksum"] = canonical_manifest_checksum(
            source, source["fragments"]
        )
    return manifest
