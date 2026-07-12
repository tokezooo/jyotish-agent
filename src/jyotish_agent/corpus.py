"""Governed corpus normalization and manifest loading."""

from __future__ import annotations

import json
import hashlib
import re
import unicodedata
from pathlib import Path
from typing import Any


def normalize_search_text(value: str) -> str:
    """Normalize Unicode transliteration to a conservative FTS alias form."""
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_like = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^\w]+", " ", ascii_like.casefold(), flags=re.UNICODE).strip()


def builtin_manifest_path() -> Path:
    return Path(__file__).with_name("data") / "corpus_manifest.json"


def load_builtin_manifest() -> dict[str, Any]:
    manifest = json.loads(builtin_manifest_path().read_text(encoding="utf-8"))
    for source in manifest["sources"]:
        for fragment in source["fragments"]:
            fragment["checksum"] = hashlib.sha256(
                fragment["text"].encode("utf-8")
            ).hexdigest()
        source_payload = {
            key: value
            for key, value in source.items()
            if key not in {"manifest_checksum", "review"}
        }
        source["manifest_checksum"] = hashlib.sha256(
            json.dumps(
                source_payload,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    return manifest
