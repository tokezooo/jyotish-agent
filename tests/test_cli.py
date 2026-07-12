from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

from jyotish_agent import cli


ROOT = Path(__file__).resolve().parents[1]


def test_inspect_uses_supervised_loopback_api_without_store_path(monkeypatch, capsys):
    run_id = "rr_00000000-0000-4000-8000-000000000000"
    child = object()
    calls: list[object] = []
    monkeypatch.setattr(cli, "_api_base", lambda: "http://127.0.0.1:8765")
    monkeypatch.setattr(cli, "_health", lambda _base: None)
    monkeypatch.setattr(cli, "_start_api", lambda base: calls.append(("start", base)) or child)
    monkeypatch.setattr(cli, "_stop_process", lambda process: calls.append(("stop", process)))
    monkeypatch.setattr(
        cli, "default_data_root",
        lambda: (_ for _ in ()).throw(AssertionError("inspect must not open the store")),
    )
    monkeypatch.setattr(
        cli, "_get_required_json",
        lambda base, path: calls.append(("get", base, path)) or {
            "run": {"run_id": run_id, "status": "created", "revision": 1},
            "intent": None, "plan": None, "events": [], "evidence": [], "answers": [],
        },
    )

    assert cli._inspect_run(SimpleNamespace(run_id=run_id, json=True)) == 0
    assert json.loads(capsys.readouterr().out)["run"]["run_id"] == run_id
    assert calls == [
        ("start", "http://127.0.0.1:8765"),
        ("get", "http://127.0.0.1:8765", f"/v2/research-runs/{run_id}/inspect"),
        ("stop", child),
    ]


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


def test_health_requires_research_v2_capability(monkeypatch):
    monkeypatch.setattr(
        cli,
        "_get_json",
        lambda _base, _path: {"status": "ok", "engine_version": "4.8.6"},
    )
    assert cli._health("http://127.0.0.1:8000") is None

    monkeypatch.setattr(
        cli,
        "_get_json",
        lambda _base, _path: {
            "status": "ok",
            "engine_version": "4.8.6",
            "research_api_version": "2.0",
        },
    )
    assert cli._health("http://127.0.0.1:8000") == {
        "status": "ok",
        "engine_version": "4.8.6",
        "research_api_version": "2.0",
    }


def test_ask_rejects_invalid_profile_before_starting_children(tmp_path: Path, capsys):
    profile = tmp_path / "bad.json"
    profile.write_text("[]", encoding="utf-8")
    assert cli.main(["ask", "Question?", "--chart", str(profile)]) == 2
    assert "profile JSON must be an object" in capsys.readouterr().err


def test_private_prompt_neutrally_classifies_non_career_question(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JYOTISH_AGENT_DATA_ROOT", str(tmp_path / "data"))
    prompt_path = cli._private_prompt(
        "Will I marry?",
        {"name": "Non-career fixture"},
        run_id="rr_11111111-1111-4111-8111-111111111111",
        create_operation_id="op_11111111-1111-4111-8111-111111111111",
    )
    try:
        prompt = prompt_path.read_text(encoding="utf-8")
    finally:
        prompt_path.unlink()

    assert "Will I marry?" in prompt
    assert "career_factors_and_timing" in prompt
    assert "unknown" in prompt
    assert "composite" in prompt
    assert "unsupported" in prompt
    assert "typed career intent" not in prompt


def test_private_prompt_preserves_write_error_after_fdopen_owns_descriptor(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("JYOTISH_AGENT_DATA_ROOT", str(tmp_path / "data"))
    real_fdopen = cli.os.fdopen

    class FailingHandle:
        def __init__(self, descriptor: int):
            self.handle = real_fdopen(descriptor, "w", encoding="utf-8")

        def __enter__(self):
            return self

        def write(self, _value: str):
            raise RuntimeError("authored write failure")

        def __exit__(self, *_args):
            self.handle.close()

    monkeypatch.setattr(
        cli.os,
        "fdopen",
        lambda descriptor, *_args, **_kwargs: FailingHandle(descriptor),
    )

    with pytest.raises(RuntimeError, match="authored write failure"):
        cli._private_prompt(
            "Question?",
            {"name": "Fixture"},
            run_id="rr_11111111-1111-4111-8111-111111111111",
            create_operation_id="op_11111111-1111-4111-8111-111111111111",
        )

    assert list((tmp_path / "data" / "runtime").glob("ask-*.txt")) == []


def _run_black_box(
    tmp_path: Path, mode: str, env_overrides: dict[str, str] | None = None
) -> tuple[subprocess.CompletedProcess, dict, int]:
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
    env.update(env_overrides or {})
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
    completed, captured, _port = _run_black_box(tmp_path, "validated")
    assert completed.returncode == 0, completed.stderr
    output = json.loads(completed.stdout)
    assert output["answer"].startswith("# Validated fake-Pi memo")
    assert "ARBITRARY_MODEL_STDOUT" not in output["answer"]
    artifact = tmp_path / "data" / "artifacts" / captured["run_id"] / "answer.md"
    assert artifact.read_text(encoding="utf-8") == output["answer"]
    assert artifact.stat().st_mode & 0o777 == 0o600


def test_black_box_temporary_home_doctor_ask_inspect_replay_hash_shutdown(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _executable, capture = _fake_pi(bin_dir)
    profile = tmp_path / "profile.json"
    _profile(profile)
    port = _free_port()
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "JYOTISH_API_URL": f"http://127.0.0.1:{port}",
        "JYOTISH_AGENT_DATA_ROOT": str(tmp_path / "data"),
        "FAKE_PI_CAPTURE": str(capture),
        "FAKE_PI_MODE": "validated",
    }
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "jyotish_agent.api:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        # One server lifecycle, exact operator order: doctor -> ask -> inspect -> replay.
        for _ in range(100):
            doctor = subprocess.run(
                [sys.executable, "-m", "jyotish_agent.cli", "doctor"],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            if doctor.returncode == 0:
                break
            import time
            time.sleep(0.05)
        assert doctor.returncode == 0, doctor.stdout + doctor.stderr
        completed = subprocess.run(
            [
                sys.executable, "-m", "jyotish_agent.cli", "ask",
                "Which career factors?", "--chart", str(profile), "--json",
            ],
            cwd=ROOT, env=env, text=True, capture_output=True, timeout=30, check=False,
        )
        assert completed.returncode == 0, completed.stderr
        captured = json.loads(capture.read_text(encoding="utf-8"))
        inspect = subprocess.run(
            [sys.executable, "-m", "jyotish_agent.cli", "run", "inspect", captured["run_id"], "--json"],
            cwd=ROOT, env=env, text=True, capture_output=True, check=False,
        )
        assert inspect.returncode == 0, inspect.stderr
        inspected = json.loads(inspect.stdout)
        assert inspected["run"]["status"] == "validated"
        stale_mirror = tmp_path / "data" / "runtime" / f"{captured['run_id']}.pi.json"
        stale_mirror.parent.mkdir(mode=0o700, exist_ok=True)
        stale_mirror.write_text('{"memo_hash":"stale"}', encoding="utf-8")
        replay = subprocess.run(
            [sys.executable, "-m", "jyotish_agent.cli", "run", "replay", captured["run_id"], "--json"],
            cwd=ROOT, env=env, text=True, capture_output=True, check=False,
        )
        assert replay.returncode == 0, replay.stderr
        replayed = json.loads(replay.stdout)
        assert len(replayed["memo_hash"]) == 64
        answer = inspected["answers"][-1]["payload"]["markdown"]
        assert replayed["memo_hash"] == __import__("hashlib").sha256(answer.encode()).hexdigest()
    finally:
        server.terminate()
        server.wait(timeout=5)
    with socket.socket() as sock:
        assert sock.connect_ex(("127.0.0.1", port)) != 0


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("missing_version", "MISSING_PINNED_VERSION"),
        ("memo_hash", "MEMO_HASH_MISMATCH"),
    ],
)
def test_cli_replay_surfaces_exact_registry_branch(tmp_path: Path, mutation: str, expected_code: str):
    completed, captured, port = _run_black_box(tmp_path, "validated")
    assert completed.returncode == 0, completed.stderr
    database = tmp_path / "data" / "research.sqlite3"
    with sqlite3.connect(database) as connection:
        if mutation == "missing_version":
            connection.execute(
                "DELETE FROM available_versions WHERE run_id=? AND version_type='corpus'",
                (captured["run_id"],),
            )
        else:
            connection.execute("DROP TRIGGER answers_no_update")
            row = connection.execute(
                "SELECT payload_json FROM answers WHERE run_id=?", (captured["run_id"],)
            ).fetchone()
            payload = json.loads(row[0])
            payload["markdown"] += "\ncorrupt"
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            import hashlib
            connection.execute(
                "UPDATE answers SET payload_json=?, payload_hash=? WHERE run_id=?",
                (encoded, hashlib.sha256(encoded.encode()).hexdigest(), captured["run_id"]),
            )
    env = {
        **os.environ,
        "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "JYOTISH_API_URL": f"http://127.0.0.1:{port}",
        "JYOTISH_AGENT_DATA_ROOT": str(tmp_path / "data"),
    }
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "jyotish_agent.api:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            if subprocess.run(
                [sys.executable, "-m", "jyotish_agent.cli", "doctor"], cwd=ROOT, env=env,
                text=True, capture_output=True, check=False,
            ).returncode == 0:
                break
            import time
            time.sleep(0.05)
        replay = subprocess.run(
            [sys.executable, "-m", "jyotish_agent.cli", "run", "replay", captured["run_id"], "--json"],
            cwd=ROOT, env=env, text=True, capture_output=True, check=False,
        )
        assert replay.returncode == 4
        assert replay.stderr.strip() == f"offline replay failed: {expected_code}"
    finally:
        server.terminate()
        server.wait(timeout=5)


def test_seeded_demo_inputs_are_small_authored_fixtures():
    profile = json.loads((ROOT / "examples" / "demo-profile.json").read_text())
    question = (ROOT / "examples" / "demo-question.txt").read_text().strip()
    assert profile["name"] == "Jyotish Demo Fixture"
    assert "career" in question.lower()
    assert len(question) < 200
