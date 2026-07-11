"""Thin argparse golden path over FastAPI and Pi print mode."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlparse

from pydantic import ValidationError

from .research_models import ResearchBirthProfileRequest
from .research_store import canonical_json, default_data_root

DEFAULT_API_URL = "http://127.0.0.1:8000"
REQUIRED_V2_BLOCKER = (
    "Jyotish research answer blocked: no backend-validated final answer is available."
)
PI_TOOLS = (
    "jyotish_create_research_run",
    "jyotish_screen_research_run",
    "jyotish_calculate_research_run",
    "jyotish_submit_answer",
)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class CliError(RuntimeError):
    def __init__(self, message: str, exit_code: int):
        super().__init__(message)
        self.exit_code = exit_code


def _api_base() -> str:
    return os.environ.get("JYOTISH_API_URL", DEFAULT_API_URL).rstrip("/")


def _get_json(base: str, path: str) -> dict | None:
    try:
        with urllib.request.urlopen(f"{base}{path}", timeout=2) as response:
            body = json.loads(response.read().decode("utf-8"))
        return body if isinstance(body, dict) else None
    except (OSError, ValueError, urllib.error.URLError):
        return None


def _health(base: str) -> dict | None:
    return _get_json(base, "/health")


def _loopback_address(base: str) -> tuple[str, int]:
    parsed = urlparse(base)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise CliError("JYOTISH_API_URL must be a loopback HTTP URL", 3)
    return parsed.hostname, parsed.port or 80


def _start_api(base: str) -> subprocess.Popen[bytes]:
    host, port = _loopback_address(base)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "jyotish_agent.api:app",
            "--host",
            host,
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=PROJECT_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if _health(base):
            return process
        if process.poll() is not None:
            break
        time.sleep(0.05)
    _stop_process(process)
    raise CliError("FastAPI failed to start on the configured loopback URL", 3)


def _stop_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _load_profile(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CliError("could not read profile JSON", 2) from exc
    if not isinstance(value, dict):
        raise CliError("profile JSON must be an object", 2)
    try:
        ResearchBirthProfileRequest.model_validate(value)
    except ValidationError as exc:
        raise CliError("profile JSON does not match the birth-profile contract", 2) from exc
    return value


def _private_prompt(
    question: str,
    profile: dict,
    *,
    run_id: str,
    create_operation_id: str,
) -> Path:
    runtime = default_data_root() / "runtime"
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(runtime, 0o700)
    cli_request = {
        "run_id": run_id,
        "create_operation_id": create_operation_id,
        "question": question,
        "birth_profile": profile,
    }
    prompt = (
        "Use only the Jyotish research tools. Create a v2 run, screen it, calculate "
        "it, construct AnswerContract 2.0, and submit it. The final response must be "
        "the backend canonical Markdown. Use the exact assigned run_id and create "
        "operation_id below; do not substitute another identity.\n\n"
        f"CLI request JSON: {canonical_json(cli_request)}\n"
        f"Question: {question}\n"
        f"Birth profile JSON: {canonical_json(profile)}\n"
    )
    descriptor, raw_path = tempfile.mkstemp(prefix="ask-", suffix=".txt", dir=runtime)
    path = Path(raw_path)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(prompt)
    except Exception:
        os.close(descriptor)
        path.unlink(missing_ok=True)
        raise
    return path


def _validated_artifact(base: str, run_id: str) -> str | None:
    run = _get_json(base, f"/v2/research-runs/{run_id}")
    event_body = _get_json(base, f"/v2/research-runs/{run_id}/events")
    if not run or run.get("run_id") != run_id or run.get("status") != "validated":
        return None
    events = event_body.get("events") if isinstance(event_body, dict) else None
    if not isinstance(events, list) or not events:
        return None
    latest = events[-1]
    if not isinstance(latest, dict) or latest.get("event_type") != "research_run.answer_submitted":
        return None
    payload = latest.get("payload")
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        return None
    markdown = result.get("markdown")
    claimed_hash = result.get("markdown_sha256")
    if (
        result.get("run_id") != run_id
        or result.get("status") != "validated"
        or result.get("valid") is not True
        or not isinstance(result.get("answer_id"), str)
        or not result["answer_id"].startswith("ans_")
        or not isinstance(markdown, str)
        or not markdown
        or not isinstance(claimed_hash, str)
    ):
        return None
    actual_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    return markdown if actual_hash == claimed_hash else None


def _emit_required_v2_blocker(as_json: bool) -> int:
    if as_json:
        print(
            json.dumps(
                {
                    "answer": REQUIRED_V2_BLOCKER,
                    "error_code": "VALIDATED_ARTIFACT_REQUIRED",
                },
                sort_keys=True,
            )
        )
    else:
        print(REQUIRED_V2_BLOCKER)
    return 5


def _doctor(_args: argparse.Namespace) -> int:
    base = _api_base()
    _loopback_address(base)
    health = _health(base)
    pi = shutil.which("pi")
    print(f"FastAPI: {'ok' if health else 'unreachable'} ({base})")
    print(f"Pi: {pi or 'not found'}")
    return 0 if health and pi else 1


def _dev(_args: argparse.Namespace) -> int:
    base = _api_base()
    _loopback_address(base)
    if _health(base):
        print(f"FastAPI already running at {base}")
        return 0
    process = _start_api(base)
    print(f"FastAPI running at {base}; press Ctrl-C to stop")
    try:
        return process.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        _stop_process(process)


def _ask(args: argparse.Namespace) -> int:
    profile = _load_profile(Path(args.chart))
    pi = shutil.which("pi")
    if not pi:
        raise CliError("Pi executable not found on PATH", 4)
    base = _api_base()
    _loopback_address(base)
    child = None
    prompt_path = None
    run_id = f"rr_{uuid.uuid4()}"
    create_operation_id = f"op_{uuid.uuid4()}"
    try:
        if not _health(base):
            child = _start_api(base)
        prompt_path = _private_prompt(
            args.question,
            profile,
            run_id=run_id,
            create_operation_id=create_operation_id,
        )
        command = [
            pi,
            "--print",
            "--no-session",
            "--no-builtin-tools",
            "--tools",
            ",".join(PI_TOOLS),
            "--no-extensions",
            "--extension",
            str(PROJECT_ROOT / ".pi" / "extensions" / "jyotish.ts"),
            "--no-skills",
            "--skill",
            str(PROJECT_ROOT / ".pi" / "skills" / "jyotish-reading" / "SKILL.md"),
            "--no-context-files",
            f"@{prompt_path}",
        ]
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            env={
                **os.environ,
                "JYOTISH_API_URL": base,
                "JYOTISH_REQUIRE_V2": "1",
            },
            text=True,
            capture_output=True,
            check=False,
        )
        answer = _validated_artifact(base, run_id)
        if completed.returncode != 0 or answer is None:
            return _emit_required_v2_blocker(args.json)
        if args.json:
            print(json.dumps({"answer": answer}, ensure_ascii=False, sort_keys=True))
        else:
            print(answer)
        return 0
    finally:
        if prompt_path is not None:
            prompt_path.unlink(missing_ok=True)
        _stop_process(child)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jyotish")
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor = subparsers.add_parser("doctor", help="check FastAPI and Pi availability")
    doctor.set_defaults(handler=_doctor)
    dev = subparsers.add_parser("dev", help="run loopback FastAPI until interrupted")
    dev.set_defaults(handler=_dev)
    ask = subparsers.add_parser("ask", help="run the v2 research workflow through Pi")
    ask.add_argument("question")
    ask.add_argument("--chart", required=True, help="birth profile JSON path")
    ask.add_argument("--json", action="store_true", help="wrap canonical output in JSON")
    ask.set_defaults(handler=_ask)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return int(args.handler(args))
    except CliError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
