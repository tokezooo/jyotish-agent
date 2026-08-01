from __future__ import annotations

import json
from pathlib import Path

from jyotish_agent.doctrine.project_audit import build_project_release_audit


ROOT = Path(__file__).parents[2]
EVIDENCE = ROOT / "docs/evidence/doctrine"


def test_project_release_audit_is_generated_from_current_domain_evidence() -> None:
    recorded = json.loads((EVIDENCE / "project-release.json").read_text())
    generated = build_project_release_audit(
        EVIDENCE,
        verification=recorded["verification"],
        private_source_scan=recorded["private_source_scan"],
    )
    assert generated == recorded
    assert recorded["all_domains_available"]
    assert not recorded["public_release_ready"]
    assert {item["domain"] for item in recorded["domains"]} == {
        "jaimini",
        "prashna",
        "muhurta",
    }
    assert recorded["private_source_scan"] == {
        "status": "passed",
        "tracked_private_source_count": 0,
    }
    assert not any("held_out" in item for item in recorded["blockers"])
    muhurta = next(
        item for item in recorded["domains"] if item["domain"] == "muhurta"
    )
    assert muhurta["available"] is True
    assert muhurta["admission_state"] == "private_experimental"
    jaimini = next(
        item for item in recorded["domains"] if item["domain"] == "jaimini"
    )
    assert jaimini["available"] is True
    assert jaimini["admission_state"] == "experimental_full"
    assert jaimini["gate_statuses"]["specialist_review"] == "missing"
