from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from jyotish_agent import cli


ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _profile(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "name": "Authored CLI Fixture",
                "date": "1990-01-01",
                "time": "12:30:00",
                "place": {
                    "name": "Chennai",
                    "latitude": 13.0827,
                    "longitude": 80.2707,
                    "timezone": 5.5,
                },
            }
        ),
        encoding="utf-8",
    )


def _fake_pi(bin_dir: Path) -> tuple[Path, Path]:
    capture = bin_dir / "capture.json"
    executable = bin_dir / "pi"
    executable.write_text(
        """#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
required = {
    "--print", "--no-builtin-tools", "--no-extensions", "--no-skills",
    "--no-context-files", "--extension", "--skill", "--tools"
}
assert required <= set(args), args
allowlist = args[args.index("--tools") + 1].split(",")
assert set(allowlist) == {
    "jyotish_create_research_run", "jyotish_screen_research_run",
    "jyotish_calculate_research_run", "jyotish_submit_answer"
}
prompt_arg = next(item for item in args if item.startswith("@"))
prompt_path = pathlib.Path(prompt_arg[1:])
prompt = prompt_path.read_text()
assert "Which career factors?" in prompt
assert "Authored CLI Fixture" in prompt
pathlib.Path(os.environ["FAKE_PI_CAPTURE"]).write_text(json.dumps({
    "args": args, "prompt_path": str(prompt_path)
}))
print("# Canonical fake answer")
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable, capture


def test_doctor_reports_backend_and_pi(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_health", lambda _base: {"status": "ok"})
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/fake/{name}")
    assert cli.main(["doctor"]) == 0
    output = capsys.readouterr().out
    assert "FastAPI: ok" in output
    assert "Pi: /fake/pi" in output


def test_ask_rejects_invalid_profile_before_starting_children(tmp_path: Path, capsys):
    profile = tmp_path / "bad.json"
    profile.write_text("[]", encoding="utf-8")
    assert cli.main(["ask", "Question?", "--chart", str(profile)]) == 2
    assert "profile JSON must be an object" in capsys.readouterr().err


def test_black_box_ask_uses_fake_pi_and_cleans_supervised_api(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _executable, capture = _fake_pi(bin_dir)
    profile = tmp_path / "profile.json"
    _profile(profile)
    port = _free_port()
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "JYOTISH_API_URL": f"http://127.0.0.1:{port}",
        "JYOTISH_AGENT_DATA_ROOT": str(tmp_path / "data"),
        "FAKE_PI_CAPTURE": str(capture),
    }
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "jyotish_agent.cli",
            "ask",
            "Which career factors?",
            "--chart",
            str(profile),
            "--json",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"answer": "# Canonical fake answer"}
    captured = json.loads(capture.read_text(encoding="utf-8"))
    assert not Path(captured["prompt_path"]).exists()
    assert all("Authored CLI Fixture" not in arg for arg in captured["args"])
    with socket.socket() as sock:
        assert sock.connect_ex(("127.0.0.1", port)) != 0


def test_seeded_demo_inputs_are_small_authored_fixtures():
    profile = json.loads((ROOT / "examples" / "demo-profile.json").read_text())
    question = (ROOT / "examples" / "demo-question.txt").read_text().strip()
    assert profile["name"] == "Jyotish Demo Fixture"
    assert "career" in question.lower()
    assert len(question) < 200
