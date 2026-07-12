"""AnswerContract v2 validation, legacy adaptation, and canonical rendering."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .models import AnswerContract
from .research_models import AnswerContractV2, ComputedClaim, SourceClaim, SynthesisClaim
from .research_store import new_id, sha256_text


@dataclass(frozen=True)
class RenderedAnswer:
    markdown: str
    sha256: str


def validate_answer_contract(
    answer: AnswerContractV2, evidence_items: list[dict[str, Any]],
    *, birth_time_confidence: str = "exact",
) -> list[str]:
    evidence = {item["evidence_id"]: item for item in evidence_items}
    claims = {claim.claim_id: claim for claim in answer.claims}
    violations: list[str] = []
    unstable_paths = {item["payload"]["path"] for item in evidence_items
                      if item["evidence_type"] == "sensitivity_fact"
                      and item["payload"].get("stability") == "unstable"}
    forbidden = re.compile(
        r"\b(?:probabilit(?:y|ies)|probabilistic|probable|probably|unlikely|"
        r"likely|likelihood|chance|odds|"
        r"rectif(?:y|ies|ied|ication)|rectified)\b|\d+(?:\.\d+)?\s*%",
        re.IGNORECASE,
    )
    prose = [answer.title, *answer.limitations, *answer.followups]
    prose.extend(getattr(claim, "text", "") for claim in answer.claims)
    if any(forbidden.search(text) for text in prose):
        violations.append("probability language and birth-time rectification are prohibited")
    if len(claims) != len(answer.claims):
        violations.append("claim_id values must be unique")

    for claim in answer.claims:
        for conflict in claim.conflicts:
            if conflict == claim.claim_id or conflict not in claims:
                violations.append(
                    f"claim {claim.claim_id} conflict does not identify another claim"
                )
        if isinstance(claim, ComputedClaim):
            for support in claim.supports:
                item = evidence.get(support)
                if item is None:
                    violations.append(
                        f"claim {claim.claim_id} support does not exist: {support}"
                    )
                elif item["evidence_type"] != "computed_fact":
                    violations.append(
                        f"computed claim {claim.claim_id} requires computed_fact evidence"
                    )
        elif isinstance(claim, SourceClaim):
            for support in claim.supports:
                item = evidence.get(support)
                if item is None:
                    violations.append(
                        f"claim {claim.claim_id} support does not exist: {support}"
                    )
                elif item["evidence_type"] != "source_fragment":
                    violations.append(
                        f"source claim {claim.claim_id} requires source_fragment evidence"
                    )
        elif isinstance(claim, SynthesisClaim):
            for support in claim.supports:
                if support not in claims:
                    violations.append(
                        f"synthesis claim {claim.claim_id} support does not exist: {support}"
                    )

    def leaf_paths(claim_id: str, seen: frozenset[str] = frozenset()) -> set[str]:
        if claim_id in seen or claim_id not in claims:
            return set()
        claim = claims[claim_id]
        if isinstance(claim, ComputedClaim):
            return {evidence[s]["payload"].get("path", "") for s in claim.supports if s in evidence}
        if isinstance(claim, SynthesisClaim):
            return set().union(*(leaf_paths(s, seen | {claim_id}) for s in claim.supports))
        return set()

    for claim in answer.claims:
        paths = leaf_paths(claim.claim_id)
        if isinstance(claim, SynthesisClaim) and claim.materiality == "major" and paths & unstable_paths:
            if "BIRTH_TIME_SENSITIVITY_UNSTABLE" not in claim.caveats or claim.confidence > 0.5:
                violations.append("central synthesis using unstable evidence requires caveat and confidence <= 0.5")
        if birth_time_confidence == "unknown" and claim.materiality == "major" and any(
            path.startswith(("d9.", "d10.", "houses.", "ascendant.",
                             "bhava.d9.", "bhava.d10.",
                             "lagnas.d9.", "lagnas.d10.")) for path in paths
        ):
            violations.append("unknown birth time cannot support strong house/varga-sensitive conclusions")

    visiting: set[str] = set()
    visited: set[str] = set()
    cycle_found = False

    def visit(claim_id: str) -> None:
        nonlocal cycle_found
        if claim_id in visiting:
            cycle_found = True
            return
        if claim_id in visited:
            return
        visiting.add(claim_id)
        claim = claims[claim_id]
        if isinstance(claim, SynthesisClaim):
            for support in claim.supports:
                if support in claims:
                    visit(support)
        visiting.remove(claim_id)
        visited.add(claim_id)

    for claim_id in claims:
        visit(claim_id)
    if cycle_found:
        violations.append("claim support graph contains a cycle")

    def terminates(claim_id: str, path: frozenset[str]) -> bool:
        if claim_id in path:
            return False
        claim = claims[claim_id]
        if isinstance(claim, ComputedClaim):
            return bool(claim.supports) and all(
                support in evidence and evidence[support]["evidence_type"] == "computed_fact"
                for support in claim.supports
            )
        if isinstance(claim, SourceClaim):
            return bool(claim.supports) and all(
                support in evidence and evidence[support]["evidence_type"] == "source_fragment"
                for support in claim.supports
            )
        return bool(claim.supports) and all(
            support in claims and terminates(support, path | {claim_id})
            for support in claim.supports
        )

    for claim in answer.claims:
        if isinstance(claim, SynthesisClaim) and not terminates(claim.claim_id, frozenset()):
            violations.append(
                f"synthesis claim {claim.claim_id} does not terminate in computed/source evidence"
            )
    return list(dict.fromkeys(violations))


def _inline(value: Any) -> str:
    return str(value).replace("`", "\\`")


def render_answer_markdown(
    answer: AnswerContractV2, evidence_items: list[dict[str, Any]]
) -> RenderedAnswer:
    evidence = {item["evidence_id"]: item for item in evidence_items}
    lines = [f"# {answer.title}", "", "## Claims", ""]
    for claim in answer.claims:
        label = claim.claim_type.capitalize()
        header = (
            f"**{label} · {claim.materiality} · confidence {claim.confidence:.2f}**"
        )
        if isinstance(claim, ComputedClaim):
            facts = []
            for support in claim.supports:
                payload = evidence[support]["payload"]
                facts.append(
                    f"`{_inline(payload['path'])}` = `{_inline(payload['value'])}`"
                )
            text = "; ".join(facts)
        else:
            text = claim.text
        lines.append(f"- {header}: {text}")
        if claim.caveats:
            lines.append(f"  - Caveats: {'; '.join(claim.caveats)}")
        if claim.conflicts:
            lines.append(f"  - Conflicts: {', '.join(claim.conflicts)}")

    if answer.limitations:
        lines.extend(["", "## Limitations", ""])
        lines.extend(f"- {item}" for item in answer.limitations)
    if answer.followups:
        lines.extend(["", "## Follow-ups", ""])
        lines.extend(f"- {item}" for item in answer.followups)
    markdown = "\n".join(lines).rstrip() + "\n"
    return RenderedAnswer(markdown=markdown, sha256=sha256_text(markdown))


def adapt_v1_answer(answer: AnswerContract) -> list[dict[str, Any]]:
    """Lossy compatibility adapter; never upgrades legacy prose to sourced claims."""
    return [
        {
            "claim_id": new_id("cl_"),
            "claim_type": "legacy_computed_claim",
            "path": fact.path,
            "value": fact.value,
            "provenance_status": "missing",
            "legacy_summary": answer.summary,
        }
        for fact in answer.facts_used
    ]
