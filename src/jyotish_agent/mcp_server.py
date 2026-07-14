"""Local Codex stdio MCP server for ordinary Jyotish conversation."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.func_metadata import ArgModelBase
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict

from .mcp_facade import JyotishMcpFacade, facade_from_environment
from .jaimini_models import JaiminiResultModel
from .prashna_models import PrashnaResultModel
from .muhurta_models import MuhurtaResultModel
from .mcp_models import (
    CalculateInput,
    CalculateResult,
    FinalizedResearch,
    FinalizeResearchInput,
    InspectResearchInput,
    JaiminiFullMcpInput,
    JaiminiFullReleaseResult,
    JaiminiMcpInput,
    MuhurtaFullMcpInput,
    MuhurtaFullReleaseResult,
    MuhurtaMcpInput,
    PrashnaFullMcpInput,
    PrashnaFullReleaseResult,
    PrashnaMcpInput,
    ProfileInput,
    ProfileResult,
    ResearchBundle,
    ResearchInput,
    ResearchInspection,
    SourceSearchInput,
    SourceSearchResult,
)


class _PrashnaPublishedArguments(BaseModel):
    """Strict discovery schema, kept separate from the total privacy adapter."""

    model_config = ConfigDict(extra="forbid")
    request: PrashnaMcpInput


class _PrashnaWireArguments(ArgModelBase):
    """Accept every outer shape so invalid values reach our sanitized envelope."""

    request: Any = None
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    def model_dump_one_level(self) -> dict[str, Any]:
        return {
            "request": self.request,
            "outer_arguments": dict(self.model_extra or {}),
        }


class _PrashnaFullPublishedArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: PrashnaFullMcpInput


class _PrashnaFullWireArguments(ArgModelBase):
    request: Any = None
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    def model_dump_one_level(self) -> dict[str, Any]:
        return {
            "request": self.request,
            "outer_arguments": dict(self.model_extra or {}),
        }


class _JaiminiPublishedArguments(BaseModel):
    """Strict Jaimini discovery schema, separate from total wire parsing."""

    model_config = ConfigDict(extra="forbid")
    request: JaiminiMcpInput


class _JaiminiWireArguments(ArgModelBase):
    """Route every malformed Jaimini shape to the privacy-safe domain result."""

    request: Any = None
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    def model_dump_one_level(self) -> dict[str, Any]:
        return {
            "request": self.request,
            "outer_arguments": dict(self.model_extra or {}),
        }


class _JaiminiFullPublishedArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: JaiminiFullMcpInput


class _JaiminiFullWireArguments(ArgModelBase):
    request: Any = None
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    def model_dump_one_level(self) -> dict[str, Any]:
        return {
            "request": self.request,
            "outer_arguments": dict(self.model_extra or {}),
        }


class _MuhurtaPublishedArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: MuhurtaMcpInput


class _MuhurtaWireArguments(ArgModelBase):
    request: Any = None
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    def model_dump_one_level(self) -> dict[str, Any]:
        return {
            "request": self.request,
            "outer_arguments": dict(self.model_extra or {}),
        }


class _MuhurtaFullPublishedArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: MuhurtaFullMcpInput


class _MuhurtaFullWireArguments(ArgModelBase):
    request: Any = None
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    def model_dump_one_level(self) -> dict[str, Any]:
        return {
            "request": self.request,
            "outer_arguments": dict(self.model_extra or {}),
        }


SERVER_INSTRUCTIONS = """Normal conversation is the default. Use quick, stateless tools for focused personal questions and follow-ups. Create a ResearchRun only for broad multi-factor analysis or when the user explicitly asks for deep research. Влад is the default profile; use an inline profile only when the user clearly identifies another person and supplies their birth data. For deep research, the final visible answer must equal finalize_research.markdown exactly; never expand or rewrite it. Keep evidence IDs, claim graphs, confidence machinery, hashes, and run-state details out of normal visible answers. Explain Jyotish as symbolic interpretation, not guaranteed prediction.

Routing:
- Conceptual Jyotish questions may be answered without tools.
- calculate and search_sources are stateless and do not create ResearchRuns.
- jaimini is stateless and returns signed computed facts; do not invent interpretation
  when interpretation_status is unavailable, and never infer an approximate range.
- jaimini_full is an additive governed interpretation surface. Respect its admission
  status; when unavailable, report blockers and use jaimini facts without inventing prose.
- prashna seals one explicit/captured question moment and supports only bounded work/project
  facts; reuse its opaque anchor token for clarification and never invent doctrine. While
  source review is pending, report literal computed facts/statuses only: do not infer a
  practical obstacle, theme, advice, or area to watch from planets, houses, signs, or lords.
- prashna_full is the additive governed interpretation surface. Respect its release audit;
- muhurta_full is the private source-bound experimental surface. It ranks only the
  immutable classical baseline and never books or persists an event;
  when unavailable, report blockers and do not convert computed facts into a judgement.
- muhurta searches calculated event boundaries for general/private focused-work sessions;
  ranking and interpretation remain unavailable until their governed source pack is admitted.
- research creates exactly one authoritative run and returns evidence for synthesis.
- finalize_research validates and saves a deep memo; inspect_research retrieves it.
- Do not infer missing birth data for another person and do not overwrite the default profile.
"""


READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
WRITE_ONCE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)


def build_server(facade: JyotishMcpFacade | None = None) -> FastMCP:
    """Build a server around an injected facade or the private local environment."""
    runtime = facade or facade_from_environment()
    server = FastMCP(
        "jyotish",
        instructions=SERVER_INSTRUCTIONS,
        log_level="ERROR",
    )

    @server.tool(
        name="get_profile",
        description="Read the selected birth profile. Defaults to Влад's private profile.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    def get_profile(request: ProfileInput) -> ProfileResult:
        return runtime.get_profile(request)

    @server.tool(
        name="calculate",
        description=(
            "Calculate selected chart facts without creating a ResearchRun. "
            "Charts: D1/D2/D3/D7/D9/D10/D12. Optional modules only: "
            "shadbala, ashtakavarga, transits, varshaphal; omit modules for "
            "ascendant, houses, planets, panchanga, or Vimshottari facts."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    def calculate(request: CalculateInput) -> CalculateResult:
        return runtime.calculate(request)

    @server.tool(
        name="jaimini",
        description=(
            "Compute bounded signed Jaimini Core facts for an exact birth time or an "
            "explicit 5-minute-step approximate range. Interpretation remains unavailable; "
            "a verified source pack and governed analysis renderer are both required."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    def jaimini(
        request: Any = None,
        outer_arguments: dict[str, Any] | None = None,
    ) -> JaiminiResultModel:
        return JaiminiResultModel(
            root=runtime.jaimini_payload(request, outer_arguments=outer_arguments)
        )

    jaimini_tool = server._tool_manager.get_tool("jaimini")
    assert jaimini_tool is not None
    jaimini_tool.parameters = _JaiminiPublishedArguments.model_json_schema()
    jaimini_tool.fn_metadata.arg_model = _JaiminiWireArguments

    @server.tool(
        name="jaimini_full",
        description=(
            "Request the governed Full Jaimini experimental surface in quick, full, deep, "
            "or inspection mode. It fails closed with explicit acquisition/admission "
            "blockers until the source-bound profile is eligible."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    def jaimini_full(
        request: Any = None,
        outer_arguments: dict[str, Any] | None = None,
    ) -> JaiminiFullReleaseResult:
        return runtime.jaimini_full_payload(request, outer_arguments=outer_arguments)

    jaimini_full_tool = server._tool_manager.get_tool("jaimini_full")
    assert jaimini_full_tool is not None
    jaimini_full_tool.parameters = {
        "type": "object",
        "properties": {"request": JaiminiFullMcpInput.model_json_schema()},
        "required": ["request"],
        "additionalProperties": False,
    }
    jaimini_full_tool.fn_metadata.arg_model = _JaiminiFullWireArguments

    @server.tool(
        name="prashna",
        description=(
            "Compute signed time-chart facts for one low-risk work/project status question. "
            "Use an explicit event anchor or capture_now with place; reuse the opaque anchor "
            "token only for clarification. capture_now requires an idempotency_key and retries "
            "are process-local for the 256 most recent identities. Governed interpretation is unavailable."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    def prashna(
        request: Any = None,
        outer_arguments: dict[str, Any] | None = None,
    ) -> PrashnaResultModel:
        return PrashnaResultModel(
            root=runtime.prashna_payload(
                request,
                outer_arguments=outer_arguments,
            )
        )

    # FastMCP normally uses one generated Pydantic model for both discovery and
    # execution. Decouple them here: discovery remains fully strict, while the
    # execution model is total and sends every malformed outer/nested value to the
    # privacy-safe INPUT_INVALID domain result instead of a value-echoing ToolError.
    prashna_tool = server._tool_manager.get_tool("prashna")
    assert prashna_tool is not None
    prashna_tool.parameters = _PrashnaPublishedArguments.model_json_schema()
    prashna_tool.fn_metadata.arg_model = _PrashnaWireArguments

    @server.tool(
        name="prashna_full",
        description=(
            "Request the source-bound Full Prashna experimental surface. It preserves "
            "the sealed-anchor contract and fails closed with release-audit blockers "
            "until the production doctrine profile is admitted."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    def prashna_full(
        request: Any = None,
        outer_arguments: dict[str, Any] | None = None,
    ) -> PrashnaFullReleaseResult:
        return runtime.prashna_full_payload(request, outer_arguments=outer_arguments)

    prashna_full_tool = server._tool_manager.get_tool("prashna_full")
    assert prashna_full_tool is not None
    prashna_full_tool.parameters = {
        "type": "object",
        "properties": {"request": PrashnaFullMcpInput.model_json_schema()},
        "required": ["request"],
        "additionalProperties": False,
    }
    prashna_full_tool.fn_metadata.arg_model = _PrashnaFullWireArguments

    @server.tool(
        name="muhurta",
        description=(
            "Search calendar-ready astronomical boundaries for general or private focused-work "
            "sessions. No booking or persistence occurs. Doctrinal ranking and interpretation "
            "remain unavailable until a governed source pack is admitted."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    def muhurta(
        request: Any = None, outer_arguments: dict[str, Any] | None = None
    ) -> MuhurtaResultModel:
        return MuhurtaResultModel(
            root=runtime.muhurta_payload(request, outer_arguments=outer_arguments)
        )

    muhurta_tool = server._tool_manager.get_tool("muhurta")
    assert muhurta_tool is not None
    muhurta_tool.parameters = _MuhurtaPublishedArguments.model_json_schema()
    muhurta_tool.fn_metadata.arg_model = _MuhurtaWireArguments

    @server.tool(
        name="muhurta_full",
        description=(
            "Search the private source-bound Expanded Muhurta baseline in quick, full, "
            "deep, or inspection mode. It supports only bounded low-risk activities, "
            "blocks high-stakes elections, and never books or persists an event."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    def muhurta_full(
        request: Any = None,
        outer_arguments: dict[str, Any] | None = None,
    ) -> MuhurtaFullReleaseResult:
        return runtime.muhurta_full_payload(request, outer_arguments=outer_arguments)

    muhurta_full_tool = server._tool_manager.get_tool("muhurta_full")
    assert muhurta_full_tool is not None
    muhurta_full_tool.parameters = {
        "type": "object",
        "properties": {"request": MuhurtaFullMcpInput.model_json_schema()},
        "required": ["request"],
        "additionalProperties": False,
    }
    muhurta_full_tool.fn_metadata.arg_model = _MuhurtaFullWireArguments

    @server.tool(
        name="search_sources",
        description="Search approved Jyotish source fragments without creating a ResearchRun.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    def search_sources(request: SourceSearchInput) -> SourceSearchResult:
        return runtime.search_sources(request)

    @server.tool(
        name="research",
        description=(
            "Start one deep ResearchRun for a broad career factors and timing analysis. "
            "Use request fields question, profile/inline_profile, reference_date, "
            "explicit_annual_scope, retrieval_query, source_limit, and model_version only; "
            "do not send topic, language, depth, or horizon fields."
        ),
        annotations=WRITE_ONCE,
        structured_output=True,
    )
    def research(request: ResearchInput) -> ResearchBundle:
        return runtime.research(request)

    @server.tool(
        name="finalize_research",
        description=(
            "Validate and persist a readable memo from one run. Send run_id, the "
            "research result revision as expected_revision, title, and findings. Each "
            "finding needs text, supports (evidence IDs from facts/sources), materiality, "
            "confidence, and optional caveats; limitations and followups are optional."
        ),
        annotations=WRITE_ONCE,
        structured_output=True,
    )
    def finalize_research(request: FinalizeResearchInput) -> FinalizedResearch:
        return runtime.finalize_research(request)

    @server.tool(
        name="inspect_research",
        description="Read a saved research answer; include provenance only when explicitly requested.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    def inspect_research(request: InspectResearchInput) -> ResearchInspection:
        return runtime.inspect_research(request)

    return server


def main() -> None:
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
