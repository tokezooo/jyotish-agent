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
import json, os, pathlib, re, sys, urllib.request, uuid
args = sys.argv[1:]
required = {
    "--print", "--no-builtin-tools", "--no-extensions", "--no-skills",
    "--no-context-files", "--extension", "--skill", "--tools"
}
assert required <= set(args), args
allowlist = args[args.index("--tools") + 1].split(",")
assert set(allowlist) == {
    "jyotish_create_research_run", "jyotish_screen_research_run",
    "jyotish_plan_research_run", "jyotish_calculate_research_run",
    "jyotish_retrieve_research_run", "jyotish_submit_answer"
}
assert os.environ.get("JYOTISH_REQUIRE_V2") == "1"
prompt_arg = next(item for item in args if item.startswith("@"))
prompt_path = pathlib.Path(prompt_arg[1:])
prompt = prompt_path.read_text()
assert "Which career factors?" in prompt
assert "Authored CLI Fixture" in prompt
request_line = next(line for line in prompt.splitlines() if line.startswith("CLI request JSON: "))
cli_request = json.loads(request_line.split(": ", 1)[1])
pathlib.Path(os.environ["FAKE_PI_CAPTURE"]).write_text(json.dumps({
    "args": args, "prompt_path": str(prompt_path), "run_id": cli_request["run_id"]
}))
if os.environ.get("FAKE_PI_MODE") == "validated":
    base = os.environ["JYOTISH_API_URL"]
    def post(path, payload):
        request = urllib.request.Request(
            base + path,
            data=json.dumps(payload).encode(),
            headers={"content-type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)
    run = post("/v2/research-runs", {
        "run_id": cli_request["run_id"],
        "operation_id": cli_request["create_operation_id"],
        "expected_revision": 0,
        "question": cli_request["question"],
        "birth_profile": cli_request["birth_profile"],
        "model_version": "fake-pi",
        "planner_version": "provisional-v1",
        "corpus_version": "test-corpus-v1",
        "contract_version": "2.0",
    })
    screened = post(f"/v2/research-runs/{run['run_id']}/screen", {
        "operation_id": f"op_{uuid.uuid4()}", "expected_revision": run["revision"]
    })
    planned = post(f"/v2/research-runs/{run['run_id']}/plan", {
        "operation_id": f"op_{uuid.uuid4()}", "expected_revision": screened["revision"],
        "intent": {"family": "career_factors_and_timing", "explicit_annual_scope": False},
        "classifier": {
            "classifier_model": "fake-pi-classifier", "classifier_version": "1",
            "prompt_hash": "a" * 64
        }
    })
    calculated = post(f"/v2/research-runs/{run['run_id']}/calculate", {
        "operation_id": f"op_{uuid.uuid4()}", "expected_revision": planned["revision"]
    })
    retrieved = post(f"/v2/research-runs/{run['run_id']}/retrieve", {
        "operation_id": f"op_{uuid.uuid4()}", "expected_revision": calculated["revision"],
        "query": "career timing", "limit": 8
    })
    claim_id = f"cl_{uuid.uuid4()}"
    submitted = post(f"/v2/research-runs/{run['run_id']}/answers", {
        "operation_id": f"op_{uuid.uuid4()}",
        "expected_revision": retrieved["revision"],
        "answer": {
            "schema_version": "2.0",
            "run_status": "calculated",
            "title": "Validated fake-Pi memo",
            "claims": [{
                "claim_type": "computed", "claim_id": claim_id,
                "materiality": "major", "confidence": 1.0,
                "supports": [calculated["evidence_ids"][0]],
                "caveats": [], "conflicts": []
            }],
            "limitations": ["Authored test artifact."], "followups": []
        }
    })
    assert submitted["valid"] is True
print("ARBITRARY_MODEL_STDOUT")
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


def _run_black_box(tmp_path: Path, mode: str) -> tuple[subprocess.CompletedProcess, dict, int]:
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
        "FAKE_PI_MODE": mode,
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
    captured = json.loads(capture.read_text(encoding="utf-8"))
    assert not Path(captured["prompt_path"]).exists()
    assert all("Authored CLI Fixture" not in arg for arg in captured["args"])
    with socket.socket() as sock:
        assert sock.connect_ex(("127.0.0.1", port)) != 0
    return completed, captured, port


def test_black_box_ask_rejects_arbitrary_fake_pi_stdout(tmp_path: Path):
    completed, _captured, _port = _run_black_box(tmp_path, "arbitrary")
    assert completed.returncode != 0
    assert json.loads(completed.stdout) == {
        "answer": cli.REQUIRED_V2_BLOCKER,
        "error_code": "VALIDATED_ARTIFACT_REQUIRED",
    }


def test_black_box_ask_outputs_only_verified_backend_artifact(tmp_path: Path):
    completed, _captured, _port = _run_black_box(tmp_path, "validated")
    assert completed.returncode == 0, completed.stderr
    output = json.loads(completed.stdout)
    assert output["answer"].startswith("# Validated fake-Pi memo")
    assert "ARBITRARY_MODEL_STDOUT" not in output["answer"]


def test_seeded_demo_inputs_are_small_authored_fixtures():
    profile = json.loads((ROOT / "examples" / "demo-profile.json").read_text())
    question = (ROOT / "examples" / "demo-question.txt").read_text().strip()
    assert profile["name"] == "Jyotish Demo Fixture"
    assert "career" in question.lower()
    assert len(question) < 200
