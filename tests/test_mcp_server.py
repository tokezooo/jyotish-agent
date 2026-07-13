from __future__ import annotations

import json
import asyncio
from pathlib import Path

from jyotish_agent.mcp_facade import JyotishMcpFacade
from jyotish_agent.mcp_server import SERVER_INSTRUCTIONS, build_server


def _profile_path(tmp_path: Path) -> Path:
    directory = tmp_path / "profiles"
    directory.mkdir(mode=0o700)
    path = directory / "vlad.json"
    path.write_text(
        json.dumps(
            {
                "name": "Vlad",
                "date": "2000-01-01",
                "time": "12:00:00",
                "birth_time_confidence": "exact",
                "place": {
                    "name": "Test City",
                    "latitude": 51.5,
                    "longitude": -0.12,
                    "timezone": {
                        "kind": "iana_with_asserted_offset",
                        "zone_id": "Europe/London",
                        "asserted_offset_hours": 0,
                        "fold": 0,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def test_server_metadata_and_tool_contract(tmp_path: Path):
    facade = JyotishMcpFacade(tmp_path / "data", _profile_path(tmp_path))
    server = build_server(facade)
    tools = asyncio.run(server.list_tools())

    assert "Normal conversation is the default" in SERVER_INSTRUCTIONS[:512]
    assert "ResearchRun" in SERVER_INSTRUCTIONS[:512]
    assert "must equal finalize_research.markdown exactly" in SERVER_INSTRUCTIONS[:512]
    assert {tool.name for tool in tools} == {
        "get_profile",
        "calculate",
        "search_sources",
        "research",
        "finalize_research",
        "inspect_research",
    }
    by_name = {tool.name: tool for tool in tools}
    assert by_name["calculate"].outputSchema is not None
    assert by_name["calculate"].annotations.readOnlyHint is True
    assert by_name["calculate"].annotations.idempotentHint is True
    assert by_name["research"].annotations.readOnlyHint is False
    assert by_name["research"].annotations.idempotentHint is False
    assert by_name["finalize_research"].annotations.destructiveHint is False


def test_in_process_get_profile_is_structured(tmp_path: Path):
    facade = JyotishMcpFacade(tmp_path / "data", _profile_path(tmp_path))
    server = build_server(facade)
    _content, result = asyncio.run(
        server.call_tool("get_profile", {"request": {}})
    )

    assert isinstance(result, dict)
    assert result["mode"] == "profile"
    assert result["profile"]["name"] == "Vlad"
