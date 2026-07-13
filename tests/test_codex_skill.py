from __future__ import annotations

from pathlib import Path
import re

import yaml


SKILL_ROOT = Path(__file__).parents[1] / ".agents" / "skills" / "jyotish-consultant"


def test_skill_frontmatter_and_codex_dependency():
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\nname: jyotish-consultant\n")
    assert "description:" in skill.split("---", 2)[1]

    metadata = yaml.safe_load(
        (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
    )
    assert metadata["policy"]["allow_implicit_invocation"] is True
    dependency = metadata["dependencies"]["tools"][0]
    assert dependency["type"] == "mcp"
    assert dependency["value"] == "jyotish"
    assert "$jyotish-consultant" in metadata["interface"]["default_prompt"]


def test_skill_routes_conversation_without_forcing_runs():
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    required = [
        "ResearchRun only for deep work",
        "Follow-up questions",
        "default profile",
        "another person",
        "calculate",
        "research",
        "finalize_research",
        "ordinary conversational prose",
        "return its `markdown` verbatim",
    ]
    for phrase in required:
        assert phrase in skill
    assert "references/career.md" in skill
    assert "references/timing.md" in skill
    assert "references/evidence.md" in skill
    assert "references/safety.md" in skill


def test_skill_tree_contains_no_private_profile_values():
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in SKILL_ROOT.rglob("*")
        if path.is_file()
    )
    assert re.search(r"\b\d{4}-\d{2}-\d{2}\b", combined) is None
    assert re.search(r"\b\d{1,2}:\d{2}\b", combined) is None
    assert "inline_profile:" not in combined
