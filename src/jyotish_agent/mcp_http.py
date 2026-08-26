"""Public, no-auth Streamable HTTP MCP surface for ChatGPT.

This runtime is intentionally separate from :mod:`jyotish_agent.mcp_server`.
The local stdio server can access saved profiles, private sources, and durable
ResearchRuns.  None of those capabilities is safe on an anonymous endpoint.

Deployment invariant: run one Railway replica with one Uvicorn worker. The
anonymous rate and calculation-admission guards are intentionally process-local
and must not be mistaken for a distributed abuse-control system.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import io
import math
import os
import time
from collections import OrderedDict
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from threading import Lock, RLock
from typing import Annotated, Any, Callable, Literal

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.func_metadata import ArgModelBase
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, RootModel, ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .mcp_facade import JyotishMcpFacade, McpFacadeError
from .mcp_models import AllowedChart, AllowedModule, CalculateInput, CalculateResult
from .research_models import ResearchBirthProfileRequest


PUBLIC_SERVER_INSTRUCTIONS = """This is a public, anonymous Jyotish calculation service. It has no saved profiles, no source-search capability, and no ResearchRun history. Always provide the complete caller-supplied inline birth profile; a saved/default profile is unavailable. The tool returns computed symbolic facts only. Do not present them as certain predictions or as medical, legal, financial, or safety advice.

Available tool:
- calculate: natal-chart facts from one inline birth profile.

The anonymous runtime performs one calculation at a time. If it returns
CALCULATION_BUSY, retry the same request after the supplied short delay.
"""


READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

_FORBIDDEN_PUBLIC_ENVIRONMENT = (
    "JYOTISH_AGENT_DATA_ROOT",
    "JYOTISH_DEFAULT_PROFILE_PATH",
    "JYOTISH_PRIVATE_SOURCES_ROOT",
)
_DEFAULT_ALLOWED_HOSTS = ("testserver", "localhost:*", "127.0.0.1:*")
_DEFAULT_ALLOWED_ORIGINS = ("https://chatgpt.com", "https://chat.openai.com")
_DEFAULT_MCP_MAX_BODY_BYTES = 262_144
_DEFAULT_MCP_RATE_LIMIT_PER_MINUTE = 120
_DEFAULT_MCP_RATE_LIMIT_BURST = 30
_DEFAULT_MCP_RATE_LIMIT_MAX_KEYS = 1_024
_DEFAULT_MCP_BODY_READ_TIMEOUT_SECONDS = 5.0
_MAX_MCP_BODY_CHUNKS = 1_024
_PUBLIC_OUTPUT_LOCK = RLock()
_PUBLIC_COMPUTE_LOCK = Lock()


@dataclass(slots=True)
class _RateLimitBucket:
    tokens: float
    updated_at: float


class _DirectPeerRateLimiter:
    """A bounded token bucket keyed only by the ASGI direct peer address.

    Forwarded headers are intentionally ignored. Railway's proxy address is not a
    trustworthy user identity unless a separately reviewed proxy configuration is
    introduced, so accepting ``X-Forwarded-For`` here would allow trivial spoofing.
    """

    def __init__(
        self,
        *,
        per_minute: int,
        burst: int,
        max_keys: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._per_second = per_minute / 60
        self._burst = float(burst)
        self._max_keys = max_keys
        self._clock = clock
        self._entries: OrderedDict[str, _RateLimitBucket] = OrderedDict()
        self._lock = Lock()
        # Buckets are useless once completely refilled. Keep a modest floor so
        # low-rate configurations do not retain peer keys indefinitely.
        self._stale_after_seconds = max(60.0, 2 * self._burst / self._per_second)

    def admit(self, peer: str) -> tuple[bool, int]:
        """Return admission and a sanitized integer Retry-After value."""
        now = self._clock()
        with self._lock:
            self._discard_stale(now)
            bucket = self._entries.get(peer)
            if bucket is None:
                if len(self._entries) >= self._max_keys:
                    self._entries.popitem(last=False)
                bucket = _RateLimitBucket(tokens=self._burst, updated_at=now)
                self._entries[peer] = bucket
            else:
                self._entries.move_to_end(peer)

            elapsed = max(0.0, now - bucket.updated_at)
            bucket.tokens = min(
                self._burst,
                bucket.tokens + elapsed * self._per_second,
            )
            bucket.updated_at = now
            if bucket.tokens >= 1:
                bucket.tokens -= 1
                return True, 0

            seconds_until_one_token = (1 - bucket.tokens) / self._per_second
            return False, max(1, math.ceil(seconds_until_one_token))

    def _discard_stale(self, now: float) -> None:
        while self._entries:
            _, oldest = next(iter(self._entries.items()))
            if now - oldest.updated_at <= self._stale_after_seconds:
                return
            self._entries.popitem(last=False)


class _PublicMcpRequestGuard:
    """Bound anonymous ``/mcp`` request size and request rate before FastMCP.

    Only POST is supported: this stateless JSON-response endpoint intentionally
    declines SSE listening streams. POST bodies are fully bounded and replayed
    to the mounted FastMCP app. This catches chunked requests with no
    Content-Length before the JSON parser can allocate an unbounded body. The
    guard applies no policy to ``/health``.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_body_bytes: int,
        body_read_timeout_seconds: float,
        rate_limiter: _DirectPeerRateLimiter,
    ) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.body_read_timeout_seconds = body_read_timeout_seconds
        self.rate_limiter = rate_limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") != "/mcp":
            await self.app(scope, receive, send)
            return

        # This stateless JSON-response server does not offer an SSE listening
        # stream. Reject non-POST methods before FastMCP can open one.
        if scope.get("method", "GET").upper() != "POST":
            await _send_public_error(
                send,
                status_code=405,
                payload={"error_code": "METHOD_NOT_ALLOWED"},
                headers={"Allow": "POST"},
            )
            return

        admitted, retry_after = self.rate_limiter.admit(_direct_peer(scope))
        if not admitted:
            await _send_public_error(
                send,
                status_code=429,
                payload={"error_code": "RATE_LIMITED"},
                headers={"Retry-After": str(retry_after)},
            )
            return

        content_length = _content_length(scope)
        if content_length is not None and content_length > self.max_body_bytes:
            await _send_public_error(
                send,
                status_code=413,
                payload={"error_code": "REQUEST_TOO_LARGE"},
            )
            return

        try:
            async with asyncio.timeout(self.body_read_timeout_seconds):
                body, disconnected = await _read_body_with_limit(
                    receive,
                    self.max_body_bytes,
                )
        except TimeoutError:
            await _send_public_error(
                send,
                status_code=408,
                payload={"error_code": "REQUEST_TIMEOUT"},
            )
            return
        if disconnected:
            return
        if body is None:
            await _send_public_error(
                send,
                status_code=413,
                payload={"error_code": "REQUEST_TOO_LARGE"},
            )
            return

        replayed = False

        async def replay_receive() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        await self.app(scope, replay_receive, send)


def _direct_peer(scope: Scope) -> str:
    """Use only the socket peer ASGI provides; never trust forwarded headers."""
    client = scope.get("client")
    if isinstance(client, tuple) and client and isinstance(client[0], str):
        return client[0]
    return "unknown"


def _content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", []):
        if name.lower() != b"content-length":
            continue
        try:
            parsed = int(value)
        except ValueError:
            return None
        return parsed if parsed >= 0 else None
    return None


async def _read_body_with_limit(
    receive: Receive,
    max_body_bytes: int,
) -> tuple[bytes | None, bool]:
    chunks: list[bytes] = []
    total = 0
    chunk_count = 0
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return None, True
        if message["type"] != "http.request":
            continue
        chunk_count += 1
        if chunk_count > _MAX_MCP_BODY_CHUNKS:
            return None, False
        chunk = message.get("body", b"")
        total += len(chunk)
        if total > max_body_bytes:
            return None, False
        chunks.append(chunk)
        if not message.get("more_body", False):
            return b"".join(chunks), False


async def _send_public_error(
    send: Send,
    *,
    status_code: int,
    payload: dict[str, str],
    headers: dict[str, str] | None = None,
) -> None:
    response = JSONResponse(payload, status_code=status_code, headers=headers)

    async def disconnected_receive() -> Message:
        return {"type": "http.disconnect"}

    await response({"type": "http"}, disconnected_receive, send)


class _PublicStatelessFacade(JyotishMcpFacade):
    """Reuse the calculation adapter without constructing SQLite or a profile store."""

    def __init__(self) -> None:
        # ``calculate`` only needs these inherited attributes.  Avoiding the base
        # constructor guarantees the public process never opens a ResearchRun DB.
        self.data_root = Path("/nonexistent-public-jyotish-runtime")
        self.default_profile_path = None
        self.clock = lambda: dt.datetime.now(dt.UTC)


class PublicCalculateInput(BaseModel):
    """Strict public input: only a caller-owned inline birth profile is legal."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    profile: Literal["inline"] = "inline"
    inline_profile: ResearchBirthProfileRequest
    question: str = Field(min_length=1, max_length=2_000)
    charts: list[AllowedChart] = Field(
        default_factory=lambda: ["D1", "D9"], min_length=1, max_length=7
    )
    modules: list[AllowedModule] = Field(default_factory=list, max_length=4)
    reference_date: dt.date | None = None

    def to_internal(self) -> CalculateInput:
        return CalculateInput.model_validate(self.model_dump(mode="python"))


class _PublicCalculateCompleted(CalculateResult):
    status: Literal["completed"] = "completed"


class _PublicCalculateNeedsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["quick"] = "quick"
    status: Literal["needs_input"] = "needs_input"
    error_code: Literal["INLINE_PROFILE_REQUIRED"]
    next_action: Literal["provide_complete_inline_profile"]


class _PublicCalculateRetry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["quick"] = "quick"
    status: Literal["retry"] = "retry"
    error_code: Literal["CALCULATION_BUSY", "CALCULATION_UNAVAILABLE"]
    next_action: Literal["retry_calculation"] = "retry_calculation"
    retry_after_seconds: Literal[1] = 1


PublicCalculateResult = Annotated[
    _PublicCalculateCompleted | _PublicCalculateNeedsInput | _PublicCalculateRetry,
    Field(discriminator="status"),
]


class PublicCalculateResultModel(RootModel[PublicCalculateResult]):
    pass


class _PublicWireArguments(ArgModelBase):
    """Make malformed outer tool calls privacy-safe rather than value-echoing."""

    request: Any = None
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    def model_dump_one_level(self) -> dict[str, Any]:
        return {
            "request": self.request,
            "outer_arguments": dict(self.model_extra or {}),
        }


class _PublicCalculatePublishedArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    request: PublicCalculateInput


@contextmanager
def _suppress_runtime_output():
    """Prevent noisy third-party calculation output from reaching Railway logs."""
    # PyJHora has import/calculation-time ``print`` calls.  The public service must
    # not forward local paths or request-derived diagnostics to process logs.
    with _PUBLIC_OUTPUT_LOCK:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            yield


def _calculate_public(
    runtime: JyotishMcpFacade,
    request: object,
    outer_arguments: dict[str, Any] | None,
) -> PublicCalculateResultModel:
    """Synchronous helper used by unit tests and non-HTTP callers.

    The public ASGI tool uses the async counterpart below so it can reject a
    second calculation before submitting any work to a thread executor.
    """
    parsed_or_result = _parse_public_request(request, outer_arguments)
    if isinstance(parsed_or_result, PublicCalculateResultModel):
        return parsed_or_result
    if not _PUBLIC_COMPUTE_LOCK.acquire(blocking=False):
        return _calculation_retry("CALCULATION_BUSY")
    try:
        return _calculate_admitted(runtime, parsed_or_result)
    finally:
        _PUBLIC_COMPUTE_LOCK.release()


async def _calculate_public_async(
    runtime: JyotishMcpFacade,
    request: object,
    outer_arguments: dict[str, Any] | None,
) -> PublicCalculateResultModel:
    """Admit at most one PyJHora calculation per process without queueing.

    The lock is acquired on the event loop *before* a worker is scheduled. A
    concurrent request therefore returns a typed retry result instead of waiting
    behind the computation or accumulating in a thread-pool work queue.
    """
    parsed_or_result = _parse_public_request(request, outer_arguments)
    if isinstance(parsed_or_result, PublicCalculateResultModel):
        return parsed_or_result
    if not _PUBLIC_COMPUTE_LOCK.acquire(blocking=False):
        return _calculation_retry("CALCULATION_BUSY")
    try:
        worker = asyncio.create_task(
            asyncio.to_thread(
                _calculate_admitted,
                runtime,
                parsed_or_result,
            )
        )
    except BaseException:
        # No worker was accepted, so there is nothing left to protect.
        _PUBLIC_COMPUTE_LOCK.release()
        raise

    def release_after_worker(worker: asyncio.Task[PublicCalculateResultModel]) -> None:
        # ``asyncio.shield`` below deliberately lets the thread keep running if
        # this HTTP request is cancelled. Only this completion callback may open
        # admission for another PyJHora calculation.
        try:
            # The cancelled HTTP caller may no longer await this task. Consume an
            # unexpected worker exception so it cannot become a noisy, possibly
            # request-correlated asyncio warning in public process logs.
            worker.result()
        except BaseException:
            pass
        finally:
            _PUBLIC_COMPUTE_LOCK.release()

    worker.add_done_callback(release_after_worker)
    return await asyncio.shield(worker)


def _parse_public_request(
    request: object,
    outer_arguments: dict[str, Any] | None,
) -> PublicCalculateInput | PublicCalculateResultModel:
    if outer_arguments or not isinstance(request, dict):
        return _inline_profile_required()
    try:
        return PublicCalculateInput.model_validate(request)
    except (ValidationError, ValueError, TypeError):
        return _inline_profile_required()


def _calculate_admitted(
    runtime: JyotishMcpFacade,
    parsed: PublicCalculateInput,
) -> PublicCalculateResultModel:
    try:
        with _suppress_runtime_output():
            result = runtime.calculate(parsed.to_internal())
    except (McpFacadeError, ValidationError, ValueError, TypeError):
        return _inline_profile_required()
    except Exception:
        # Never leak third-party exception text through a ToolError.  Such text can
        # contain a local path or caller-provided value.
        return _calculation_retry("CALCULATION_UNAVAILABLE")
    return PublicCalculateResultModel(
        root=_PublicCalculateCompleted.model_validate(result.model_dump(mode="python"))
    )


def _inline_profile_required() -> PublicCalculateResultModel:
    return PublicCalculateResultModel(
        root=_PublicCalculateNeedsInput(
            error_code="INLINE_PROFILE_REQUIRED",
            next_action="provide_complete_inline_profile",
        )
    )


def _calculation_retry(
    error_code: Literal["CALCULATION_BUSY", "CALCULATION_UNAVAILABLE"],
) -> PublicCalculateResultModel:
    return PublicCalculateResultModel(root=_PublicCalculateRetry(error_code=error_code))


def _replace_wire_schema(server: FastMCP) -> None:
    tool = server._tool_manager.get_tool("calculate")
    assert tool is not None
    tool.parameters = _PublicCalculatePublishedArguments.model_json_schema()
    tool.fn_metadata.arg_model = _PublicWireArguments


def build_public_server(facade: JyotishMcpFacade | None = None) -> FastMCP:
    """Build the intentionally restricted public MCP server."""
    runtime = facade or public_facade_from_environment()
    server = FastMCP(
        "jyotish-public",
        instructions=PUBLIC_SERVER_INSTRUCTIONS,
        log_level="CRITICAL",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=_port_from_environment(),
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        transport_security=_transport_security_settings(),
    )

    @server.custom_route("/health", methods=["GET"], include_in_schema=False)
    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @server.tool(
        name="calculate",
        description=(
            "Calculate selected natal-chart facts from a complete caller-supplied "
            "inline birth profile. Saved/default profiles are unavailable."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def calculate(
        request: Any = None,
        outer_arguments: dict[str, Any] | None = None,
    ) -> PublicCalculateResultModel:
        return await _calculate_public_async(runtime, request, outer_arguments)

    _replace_wire_schema(server)
    return server


def _configured_values(name: str, defaults: tuple[str, ...]) -> list[str]:
    values = [
        value.strip()
        for value in os.environ.get(name, "").split(",")
        if value.strip()
    ]
    return values or list(defaults)


def _allowed_hosts() -> list[str]:
    values = _configured_values("JYOTISH_ALLOWED_HOSTS", _DEFAULT_ALLOWED_HOSTS)
    railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
    if railway_domain:
        values.append(railway_domain)
    allowed: list[str] = []
    for value in values:
        if value not in allowed:
            allowed.append(value)
        if ":" not in value and f"{value}:*" not in allowed:
            allowed.append(f"{value}:*")
    return allowed


def _transport_security_settings() -> TransportSecuritySettings:
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_allowed_hosts(),
        allowed_origins=_configured_values(
            "JYOTISH_ALLOWED_ORIGINS", _DEFAULT_ALLOWED_ORIGINS
        ),
    )


def _port_from_environment() -> int:
    raw = os.environ.get("PORT", "8080")
    try:
        port = int(raw)
    except ValueError as exc:
        raise RuntimeError("PUBLIC_RUNTIME_PORT_INVALID") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("PUBLIC_RUNTIME_PORT_INVALID")
    return port


def _bounded_integer_from_environment(
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("PUBLIC_RUNTIME_GUARD_CONFIGURATION_INVALID") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError("PUBLIC_RUNTIME_GUARD_CONFIGURATION_INVALID")
    return value


def _max_body_bytes_from_environment() -> int:
    return _bounded_integer_from_environment(
        "JYOTISH_MCP_MAX_BODY_BYTES",
        _DEFAULT_MCP_MAX_BODY_BYTES,
        minimum=1_024,
        maximum=1_048_576,
    )


def _body_read_timeout_from_environment() -> float:
    raw = os.environ.get(
        "JYOTISH_MCP_BODY_READ_TIMEOUT_SECONDS",
        str(_DEFAULT_MCP_BODY_READ_TIMEOUT_SECONDS),
    )
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError("PUBLIC_RUNTIME_GUARD_CONFIGURATION_INVALID") from exc
    if not math.isfinite(value) or not 0.1 <= value <= 30.0:
        raise RuntimeError("PUBLIC_RUNTIME_GUARD_CONFIGURATION_INVALID")
    return value


def _rate_limiter_from_environment() -> _DirectPeerRateLimiter:
    per_minute = _bounded_integer_from_environment(
        "JYOTISH_MCP_RATE_LIMIT_PER_MINUTE",
        _DEFAULT_MCP_RATE_LIMIT_PER_MINUTE,
        minimum=1,
        maximum=600,
    )
    burst = _bounded_integer_from_environment(
        "JYOTISH_MCP_RATE_LIMIT_BURST",
        _DEFAULT_MCP_RATE_LIMIT_BURST,
        minimum=1,
        maximum=600,
    )
    max_keys = _bounded_integer_from_environment(
        "JYOTISH_MCP_RATE_LIMIT_MAX_KEYS",
        _DEFAULT_MCP_RATE_LIMIT_MAX_KEYS,
        minimum=1,
        maximum=4_096,
    )
    return _DirectPeerRateLimiter(
        per_minute=per_minute,
        burst=burst,
        max_keys=max_keys,
    )


def public_facade_from_environment() -> JyotishMcpFacade:
    """Create a facade that cannot reach saved profiles or ResearchRun storage."""
    if any(os.environ.get(name) for name in _FORBIDDEN_PUBLIC_ENVIRONMENT):
        raise RuntimeError("PUBLIC_RUNTIME_PRIVATE_CONFIGURATION_FORBIDDEN")
    return _PublicStatelessFacade()


def create_http_app(facade: JyotishMcpFacade | None = None) -> Starlette:
    """Return an ASGI app exposing only ``/mcp`` and ``/health``."""
    app = build_public_server(facade).streamable_http_app()
    app.add_middleware(
        _PublicMcpRequestGuard,
        max_body_bytes=_max_body_bytes_from_environment(),
        body_read_timeout_seconds=_body_read_timeout_from_environment(),
        rate_limiter=_rate_limiter_from_environment(),
    )
    return app


def main() -> None:
    """Run the Railway-compatible anonymous Streamable HTTP service."""
    app = create_http_app()
    uvicorn.run(
        app,
        host=os.environ.get("HOST", "0.0.0.0"),
        port=_port_from_environment(),
        log_level="critical",
        access_log=False,
    )


if __name__ == "__main__":
    main()
