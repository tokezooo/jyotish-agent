from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _private_profile(tmp_path: Path) -> Path:
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
                    "timezone": {"kind": "iana", "zone_id": "Europe/London", "fold": 0},
                },
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def test_stdio_initializes_lists_and_calls_profile(tmp_path: Path):
    import asyncio

    asyncio.run(_stdio_initializes_lists_and_calls_profile(tmp_path))


async def _stdio_initializes_lists_and_calls_profile(tmp_path: Path):
    profile = _private_profile(tmp_path)
    env = {
        **os.environ,
        "JYOTISH_AGENT_DATA_ROOT": str(tmp_path / "data"),
        "JYOTISH_DEFAULT_PROFILE_PATH": str(profile),
    }
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "jyotish_agent.mcp_server"],
        env=env,
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            tools = await session.list_tools()
            result = await session.call_tool("get_profile", {"request": {}})

    assert initialized.serverInfo.name == "jyotish"
    assert len(tools.tools) == 8
    assert result.isError is False
    assert result.structuredContent["profile"]["name"] == "Vlad"
