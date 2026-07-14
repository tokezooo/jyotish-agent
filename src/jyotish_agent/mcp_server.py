"""Local Codex stdio MCP server for ordinary Jyotish conversation."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .mcp_facade import JyotishMcpFacade, facade_from_environment
from .jaimini_models import JaiminiResultModel
from .prashna_models import PrashnaResultModel
from .mcp_models import (
    CalculateInput,
    CalculateResult,
    FinalizedResearch,
    FinalizeResearchInput,
    InspectResearchInput,
    JaiminiMcpInput,
    PrashnaMcpInput,
    ProfileInput,
    ProfileResult,
    ResearchBundle,
    ResearchInput,
    ResearchInspection,
    SourceSearchInput,
    SourceSearchResult,
)


SERVER_INSTRUCTIONS = """Normal conversation is the default. Use quick, stateless tools for focused personal questions and follow-ups. Create a ResearchRun only for broad multi-factor analysis or when the user explicitly asks for deep research. Влад is the default profile; use an inline profile only when the user clearly identifies another person and supplies their birth data. For deep research, the final visible answer must equal finalize_research.markdown exactly; never expand or rewrite it. Keep evidence IDs, claim graphs, confidence machinery, hashes, and run-state details out of normal visible answers. Explain Jyotish as symbolic interpretation, not guaranteed prediction.

Routing:
- Conceptual Jyotish questions may be answered without tools.
- calculate and search_sources are stateless and do not create ResearchRuns.
- jaimini is stateless and returns signed computed facts; do not invent interpretation
  when interpretation_status is unavailable, and never infer an approximate range.
- prashna seals one explicit/captured question moment and supports only bounded work/project
  facts; reuse its opaque anchor token for clarification and never invent doctrine.
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
    def jaimini(request: JaiminiMcpInput) -> JaiminiResultModel:
        return JaiminiResultModel(root=runtime.jaimini(request))

    @server.tool(
        name="prashna",
        description=(
            "Compute signed time-chart facts for one low-risk work/project status question. "
            "Use an explicit event anchor or capture_now with place; reuse the opaque anchor "
            "token only for clarification. Governed interpretation is unavailable."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    def prashna(request: PrashnaMcpInput) -> PrashnaResultModel:
        return PrashnaResultModel(root=runtime.prashna(request))

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
