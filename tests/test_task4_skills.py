from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_reading_skill_is_concise_router_with_one_level_references():
    skill = ROOT / ".pi" / "skills" / "jyotish-reading" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    assert len(text.splitlines()) < 100
    for name in ("career-research.md", "timing.md", "evidence.md", "safety.md"):
        assert name in text
        assert (skill.parent / "references" / name).is_file()


def test_corpus_curator_skill_validates_and_never_auto_approves():
    skill = ROOT / ".pi" / "skills" / "jyotish-corpus-curator"
    result = subprocess.run(
        [
            sys.executable,
            "/Users/vlad/.codex/skills/.system/skill-creator/scripts/quick_validate.py",
            str(skill),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    text = (skill / "SKILL.md").read_text(encoding="utf-8").lower()
    for term in ("manifest", "rights", "checksum", "locator", "review"):
        assert term in text
    assert "never auto-approve" in text
    openai_yaml = (skill / "agents" / "openai.yaml").read_text(encoding="utf-8")
    assert "$jyotish-corpus-curator" in openai_yaml
