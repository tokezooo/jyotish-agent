"""Deterministic whole-project release audit assembled from domain evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_project_release_audit(
    evidence_root: Path,
    *,
    verification: dict[str, object],
    private_source_scan: dict[str, object],
) -> dict[str, object]:
    domains: list[dict[str, object]] = []
    blockers: list[str] = []
    for domain in ("jaimini", "prashna", "muhurta"):
        path = evidence_root / f"{domain}-release.json"
        release = json.loads(path.read_text(encoding="utf-8"))
        domain_blockers = release.get("blockers") or release.get(
            "public_release_blockers", []
        )
        domains.append(
            {
                "domain": domain,
                "release_id": release["release_id"],
                "evidence_sha256": _sha256(path),
                "admission_state": release["admission_state"],
                "available": release["available"],
                "gate_statuses": {
                    gate["gate_id"]: gate["status"] for gate in release["gates"]
                },
                "blockers": domain_blockers,
            }
        )
        blockers.extend(f"{domain}: {item}" for item in domain_blockers)
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "audit_id": "jyotish_doctrine_platform_v1",
        "domains": domains,
        "verification": verification,
        "private_source_scan": private_source_scan,
        "all_domains_available": all(item["available"] for item in domains),
        "public_release_ready": False,
        "blockers": blockers,
    }
    return {**payload, "audit_sha256": _canonical_sha256(payload)}
