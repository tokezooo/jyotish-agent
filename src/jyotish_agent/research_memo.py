"""Deterministic provisional rendering from persisted run state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .research_store import canonical_json, sha256_text


@dataclass(frozen=True)
class ProvisionalMemo:
    markdown: str
    manifest: dict[str, Any]
    manifest_hash: str


def render_provisional_memo(
    run: dict[str, Any], events: list[dict[str, Any]]
) -> ProvisionalMemo:
    manifest = {
        "schema_version": "provisional-1",
        "run": run,
        "event_chain": [
            {
                "seq": event["seq"],
                "event_id": event["event_id"],
                "event_hash": event["event_hash"],
                "previous_event_hash": event["previous_event_hash"],
            }
            for event in events
        ],
    }
    manifest_hash = sha256_text(canonical_json(manifest))
    markdown = (
        f"# Research run {run['run_id']}\n\n"
        f"Status: {run['status']}\n\n"
        f"Reference date: {run['reference_date']}\n\n"
        f"Manifest SHA-256: `{manifest_hash}`\n"
    )
    return ProvisionalMemo(markdown=markdown, manifest=manifest, manifest_hash=manifest_hash)
