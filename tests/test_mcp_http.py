from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jyotish_agent.mcp_facade import JyotishMcpFacade
from jyotish_agent.mcp_http import (
    PUBLIC_SERVER_INSTRUCTIONS,
    _DirectPeerRateLimiter,
    _PublicMcpRequestGuard,
    build_public_server,
    create_http_app,
    main,
    public_facade_from_environment,
)
from jyotish_agent.mcp_models import CalculateResult


def _profile(name: str = "Caller") -> dict:
    return {
        "name": name,
        "date": "1990-01-01",
        "time": "12:00:00",
        "birth_time_confidence": "exact",
        "place": {
            "name": "Mumbai",
            "latitude": 19.076,
            "longitude": 72.8777,
            "timezone": {
                "kind": "iana",
                "zone_id": "Asia/Kolkata",
                "fold": 0,
            },
        },
    }


def _private_profile(tmp_path: Path) -> Path:
    directory = tmp_path / "profiles"
    directory.mkdir(mode=0o700)
    path = directory / "vlad.json"
    path.write_text(json.dumps(_profile("Vlad Private")), encoding="utf-8")
    path.chmod(0o600)
    return path


def _fake_chart(*_args, **_kwargs) -> dict:
    print("PRIVATE_CALCULATION_OUTPUT_MUST_NOT_REACH_LOGS")
    return {
        "normalized_input": {"fixture": True},
        "calculation_config": {"charts": ["D1"], "modules": []},
        "facts": {"ascendant": {"sign": "Pisces"}},
        "provenance": {"engine": "fixture", "engine_version": "1"},
    }


def _mcp_headers() -> dict[str, str]:
    return {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }


def _tools_list_request(request_id: int = 1) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/list",
        "params": {},
    }


def test_public_server_advertises_only_inline_calculate(tmp_path: Path) -> None:
    server = build_public_server(
        JyotishMcpFacade(tmp_path / "data", _private_profile(tmp_path))
    )
    tools = asyncio.run(server.list_tools())

    assert {tool.name for tool in tools} == {"calculate"}
    tool = tools[0]
    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.idempotentHint is True
    assert tool.outputSchema is not None

    request_schema = tool.inputSchema["$defs"]["PublicCalculateInput"]
    assert request_schema["properties"]["profile"]["const"] == "inline"
    assert "inline_profile" in request_schema["required"]
    assert {"get_profile", "search_sources", "research", "finalize_research"}.isdisjoint(
        {tool.name for tool in tools}
    )
    assert "Влад" not in PUBLIC_SERVER_INSTRUCTIONS
    assert "private source" not in PUBLIC_SERVER_INSTRUCTIONS.lower()


def test_public_calculate_never_selects_or_echoes_private_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    facade = JyotishMcpFacade(tmp_path / "data", _private_profile(tmp_path))
    monkeypatch.setattr("jyotish_agent.mcp_facade.compute_chart", _fake_chart)

    def forbidden_default_profile():
        raise AssertionError("public HTTP must never select the saved profile")

    monkeypatch.setattr(facade, "_default_profile", forbidden_default_profile)
    server = build_public_server(facade)

    async def call() -> tuple[dict, dict]:
        _content, invalid = await server.call_tool(
            "calculate",
            {
                "request": {
                    "profile": "default",
                    "question": "PRIVATE_REQUEST_VALUE_DO_NOT_ECHO",
                }
            },
        )
        _content, valid = await server.call_tool(
            "calculate",
            {
                "request": {
                    "profile": "inline",
                    "inline_profile": _profile(),
                    "question": "D1 facts",
                    "charts": ["D1"],
                }
            },
        )
        return invalid, valid

    invalid, valid = asyncio.run(call())
    rendered = json.dumps(invalid)
    assert invalid["error_code"] == "INLINE_PROFILE_REQUIRED"
    assert "PRIVATE_REQUEST_VALUE_DO_NOT_ECHO" not in rendered
    assert "Vlad Private" not in rendered
    assert valid["status"] == "completed"
    assert valid["profile_name"] == "Caller"
    assert "PRIVATE_CALCULATION_OUTPUT_MUST_NOT_REACH_LOGS" not in capsys.readouterr().out


def test_public_runtime_fails_closed_when_private_environment_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for variable in (
        "JYOTISH_AGENT_DATA_ROOT",
        "JYOTISH_DEFAULT_PROFILE_PATH",
        "JYOTISH_PRIVATE_SOURCES_ROOT",
    ):
        monkeypatch.setenv(variable, "/private/not-for-http")
        with pytest.raises(RuntimeError, match="PUBLIC_RUNTIME_PRIVATE_CONFIGURATION_FORBIDDEN"):
            public_facade_from_environment()
        monkeypatch.delenv(variable)

    runtime = public_facade_from_environment()
    assert runtime.default_profile_path is None
    assert not hasattr(runtime, "store")
    assert not hasattr(runtime, "service")


def test_http_app_exposes_only_health_and_streamable_mcp(tmp_path: Path) -> None:
    facade = JyotishMcpFacade(tmp_path / "data", _private_profile(tmp_path))
    app = create_http_app(facade)

    with TestClient(app) as client:
        assert {route.path for route in app.routes} == {"/mcp", "/health"}
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/v2/research-runs/not-exposed").status_code == 404
        assert client.get("/docs").status_code == 404
        for method in (client.get, client.delete):
            rejected_stream = method("/mcp", headers={"Accept": "text/event-stream"})
            assert rejected_stream.status_code == 405
            assert rejected_stream.json() == {"error_code": "METHOD_NOT_ALLOWED"}
            assert rejected_stream.headers["Allow"] == "POST"
            assert not rejected_stream.headers["content-type"].startswith(
                "text/event-stream"
            )
        headers = _mcp_headers()
        response = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        payload = response.json()
        assert payload["result"]["serverInfo"]["name"] == "jyotish-public"
        assert "finalize_research" not in payload["result"]["instructions"]
        assert "inspect_research" not in payload["result"]["instructions"]

        tools = client.post(
            "/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        assert tools.status_code == 200
        assert [item["name"] for item in tools.json()["result"]["tools"]] == [
            "calculate"
        ]

        call = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "calculate",
                    "arguments": {
                        "request": {"profile": "inline", "question": "D1 facts"}
                    },
                },
            },
        )
        assert call.status_code == 200
        assert call.json()["result"]["structuredContent"]["status"] == "needs_input"

        rejected = client.post(
            "/mcp",
            headers={**headers, "Host": "untrusted.invalid"},
            json={"jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": {}},
        )
        assert rejected.status_code == 421


def test_mcp_request_guard_rejects_sized_and_chunked_oversized_bodies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JYOTISH_MCP_MAX_BODY_BYTES", "1024")
    app = create_http_app(JyotishMcpFacade(tmp_path / "data", _private_profile(tmp_path)))

    with TestClient(app) as client:
        oversized = client.post(
            "/mcp",
            headers=_mcp_headers(),
            content=b"x" * 1025,
        )
    assert oversized.status_code == 413
    assert oversized.json() == {"error_code": "REQUEST_TOO_LARGE"}
    assert b"x" * 32 not in oversized.content

    called = False

    async def inner_app(_scope, _receive, _send) -> None:
        nonlocal called
        called = True

    guard = _PublicMcpRequestGuard(
        inner_app,
        max_body_bytes=1024,
        body_read_timeout_seconds=1,
        rate_limiter=_DirectPeerRateLimiter(per_minute=60, burst=10, max_keys=8),
    )

    async def exercise_chunked_request() -> list[dict]:
        messages = iter(
            [
                {"type": "http.request", "body": b"x" * 700, "more_body": True},
                {"type": "http.request", "body": b"y" * 325, "more_body": False},
            ]
        )
        sent: list[dict] = []

        async def receive() -> dict:
            return next(messages)

        async def send(message: dict) -> None:
            sent.append(message)

        await guard(
            {
                "type": "http",
                "method": "POST",
                "path": "/mcp",
                "headers": [(b"transfer-encoding", b"chunked")],
                "client": ("198.51.100.40", 31337),
            },
            receive,
            send,
        )
        return sent

    sent = asyncio.run(exercise_chunked_request())
    assert called is False
    assert sent[0]["status"] == 413
    assert json.loads(sent[1]["body"]) == {"error_code": "REQUEST_TOO_LARGE"}


def test_mcp_request_guard_times_out_slow_body_reads() -> None:
    called = False

    async def inner_app(_scope, _receive, _send) -> None:
        nonlocal called
        called = True

    guard = _PublicMcpRequestGuard(
        inner_app,
        max_body_bytes=1024,
        body_read_timeout_seconds=0.01,
        rate_limiter=_DirectPeerRateLimiter(per_minute=60, burst=10, max_keys=8),
    )

    async def exercise_slow_request() -> list[dict]:
        never_arrives = asyncio.Event()
        sent: list[dict] = []

        async def receive() -> dict:
            await never_arrives.wait()
            raise AssertionError("the slow receive should have been cancelled")

        async def send(message: dict) -> None:
            sent.append(message)

        await guard(
            {
                "type": "http",
                "method": "POST",
                "path": "/mcp",
                "headers": [(b"transfer-encoding", b"chunked")],
                "client": ("198.51.100.41", 31337),
            },
            receive,
            send,
        )
        return sent

    sent = asyncio.run(exercise_slow_request())
    assert called is False
    assert sent[0]["status"] == 408
    assert json.loads(sent[1]["body"]) == {"error_code": "REQUEST_TIMEOUT"}


@pytest.mark.parametrize("raw_timeout", ["0", "30.1", "not-a-duration", "nan"])
def test_body_read_timeout_configuration_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw_timeout: str
) -> None:
    monkeypatch.setenv("JYOTISH_MCP_BODY_READ_TIMEOUT_SECONDS", raw_timeout)
    facade = JyotishMcpFacade(tmp_path / "data", _private_profile(tmp_path))

    with pytest.raises(RuntimeError, match="PUBLIC_RUNTIME_GUARD_CONFIGURATION_INVALID"):
        create_http_app(facade)


def test_mcp_rate_limit_uses_direct_peer_not_forwarded_headers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JYOTISH_MCP_RATE_LIMIT_PER_MINUTE", "1")
    monkeypatch.setenv("JYOTISH_MCP_RATE_LIMIT_BURST", "1")
    app = create_http_app(JyotishMcpFacade(tmp_path / "data", _private_profile(tmp_path)))

    with TestClient(app, client=("198.51.100.88", 12345)) as client:
        first = client.post(
            "/mcp",
            headers={**_mcp_headers(), "X-Forwarded-For": "203.0.113.1"},
            json=_tools_list_request(1),
        )
        blocked = client.post(
            "/mcp",
            headers={**_mcp_headers(), "X-Forwarded-For": "203.0.113.2"},
            json=_tools_list_request(2),
        )

    assert first.status_code == 200
    assert blocked.status_code == 429
    assert blocked.json() == {"error_code": "RATE_LIMITED"}
    assert blocked.headers["Retry-After"] == "60"


def test_calculate_single_flight_returns_typed_busy_retry() -> None:
    class BlockingFacade:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.release = threading.Event()
            self.calls = 0

        def calculate(self, _value) -> CalculateResult:
            self.calls += 1
            self.started.set()
            self.release.wait(timeout=2)
            return CalculateResult(
                profile_name="Caller",
                selected_scope={},
                normalized_input={},
                facts={},
                warnings=[],
                provenance={},
            )

    facade = BlockingFacade()
    server = build_public_server(facade)  # type: ignore[arg-type]
    arguments = {
        "request": {
            "profile": "inline",
            "inline_profile": _profile(),
            "question": "D1 facts",
            "charts": ["D1"],
        }
    }

    async def exercise() -> tuple[dict, dict, int]:
        first_call = asyncio.create_task(server.call_tool("calculate", arguments))
        assert await asyncio.to_thread(facade.started.wait, 1)
        try:
            _content, busy = await server.call_tool("calculate", arguments)
            calls_while_busy = facade.calls
        finally:
            facade.release.set()
        _content, completed = await first_call
        return busy, completed, calls_while_busy

    busy, completed, calls_while_busy = asyncio.run(exercise())
    assert busy == {
        "mode": "quick",
        "status": "retry",
        "error_code": "CALCULATION_BUSY",
        "next_action": "retry_calculation",
        "retry_after_seconds": 1,
    }
    assert calls_while_busy == 1
    assert completed["status"] == "completed"


def test_cancelled_calculate_keeps_single_flight_until_worker_exits() -> None:
    class BlockingFacade:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.release = threading.Event()
            self.calls = 0

        def calculate(self, _value) -> CalculateResult:
            self.calls += 1
            self.started.set()
            self.release.wait(timeout=2)
            return CalculateResult(
                profile_name="Caller",
                selected_scope={},
                normalized_input={},
                facts={},
                warnings=[],
                provenance={},
            )

    facade = BlockingFacade()
    server = build_public_server(facade)  # type: ignore[arg-type]
    arguments = {
        "request": {
            "profile": "inline",
            "inline_profile": _profile(),
            "question": "D1 facts",
            "charts": ["D1"],
        }
    }

    async def exercise() -> tuple[dict, dict, int]:
        cancelled_call = asyncio.create_task(server.call_tool("calculate", arguments))
        assert await asyncio.to_thread(facade.started.wait, 1)
        cancelled_call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled_call

        _content, busy = await server.call_tool("calculate", arguments)
        assert facade.calls == 1

        facade.release.set()
        for _ in range(100):
            await asyncio.sleep(0)
            _content, subsequent = await server.call_tool("calculate", arguments)
            if subsequent["status"] == "completed":
                return busy, subsequent, facade.calls
        raise AssertionError("compute admission was not released after worker exit")

    busy, subsequent, calls = asyncio.run(exercise())
    assert busy["error_code"] == "CALCULATION_BUSY"
    assert subsequent["status"] == "completed"
    assert calls == 2


def test_main_disables_http_access_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    sentinel = object()
    monkeypatch.setenv("PORT", "8123")
    monkeypatch.setattr("jyotish_agent.mcp_http.create_http_app", lambda: sentinel)

    def fake_run(app, **kwargs):
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr("jyotish_agent.mcp_http.uvicorn.run", fake_run)
    main()

    assert captured == {
        "app": sentinel,
        "host": "0.0.0.0",
        "port": 8123,
        "log_level": "critical",
        "access_log": False,
    }


def test_docker_build_is_allowlisted_and_excludes_private_sources() -> None:
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (root / ".dockerignore").read_text(encoding="utf-8")

    assert "COPY src/ ./src/" in dockerfile
    assert "COPY ." not in dockerfile
    assert "private_sources/" in dockerignore
    assert "private_evidence/" in dockerignore
