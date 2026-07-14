from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from jyotish_agent.mcp_facade import JyotishMcpFacade, McpFacadeError
from jyotish_agent import mcp_models


def _profile(tmp_path: Path) -> Path:
    directory = tmp_path / "profiles"
    directory.mkdir(mode=0o700)
    path = directory / "founder.json"
    path.write_text(
        json.dumps(
            {
                "name": "Synthetic Founder",
                "date": "1990-01-01",
                "time": "12:30:00",
                "birth_time_confidence": "exact",
                "place": {
                    "name": "Chennai",
                    "latitude": 13.0827,
                    "longitude": 80.2707,
                    "timezone": {"kind": "iana", "zone_id": "Asia/Kolkata", "fold": 0},
                },
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def test_mcp_facade_exact_and_approximate_are_stateless_and_fail_closed(tmp_path: Path):
    assert hasattr(mcp_models, "JaiminiMcpInput")
    facade = JyotishMcpFacade(tmp_path / "data", _profile(tmp_path))
    before = facade.store.count_runs()
    exact = facade.jaimini(
        mcp_models.JaiminiMcpInput(
            question="Как мои показатели Джаймини связаны с ролью solo founder и карьерой?",
            birth={"confidence": "exact"},
            gender="male",
            reference_date="2026-07-14",
        )
    )
    approximate = facade.jaimini(
        mcp_models.JaiminiMcpInput(
            question="What Jaimini factors relate to my founder role and career?",
            birth={
                "confidence": "approximate",
                "earliest_time": "12:25:00",
                "latest_time": "12:35:00",
            },
            gender="male",
            reference_date="2026-07-14",
        )
    )
    assert facade.store.count_runs() == before
    assert exact.status == approximate.status == "completed"
    assert exact.interpretation_status == approximate.interpretation_status == "unavailable"
    assert approximate.anchor_summary == "approximate birth anchor; 3 samples at 5-minute steps"


def test_mcp_facade_rejects_fixed_timezone_without_leaking_profile(tmp_path: Path):
    path = _profile(tmp_path)
    payload = json.loads(path.read_text())
    payload["place"]["timezone"] = {"kind": "fixed_offset_legacy", "offset_hours": 5.5}
    path.write_text(json.dumps(payload), encoding="utf-8")
    facade = JyotishMcpFacade(tmp_path / "data", path)
    with pytest.raises(McpFacadeError, match="JAIMINI_IANA_TIMEZONE_REQUIRED") as error:
        facade.jaimini(
            mcp_models.JaiminiMcpInput(
                question="Career?", birth={"confidence": "exact"}, gender="male"
            )
        )
    assert "Chennai" not in str(error.value)
    assert "1990" not in str(error.value)


def test_realistic_ru_en_stdio_exact_and_ten_minute_range(tmp_path: Path):
    asyncio.run(_stdio_scenarios(tmp_path))


async def _stdio_scenarios(tmp_path: Path):
    env = {
        **os.environ,
        "JYOTISH_AGENT_DATA_ROOT": str(tmp_path / "data"),
        "JYOTISH_DEFAULT_PROFILE_PATH": str(_profile(tmp_path)),
    }
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "jyotish_agent.mcp_server"],
        env=env,
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            exact = await session.call_tool(
                "jaimini",
                {"request": {
                    "question": "Как мои показатели Джаймини связаны с ролью solo founder и карьерой?",
                    "birth": {"confidence": "exact"},
                    "gender": "male",
                    "reference_date": "2026-07-14",
                }},
            )
            approximate = await session.call_tool(
                "jaimini",
                {"request": {
                    "question": "What Jaimini factors relate to my founder role and career?",
                    "birth": {"confidence": "approximate", "earliest_time": "12:25:00", "latest_time": "12:35:00"},
                    "gender": "male",
                    "reference_date": "2026-07-14",
                }},
            )
    assert exact.isError is False
    assert approximate.isError is False
    assert exact.structuredContent["status"] == "completed"
    assert exact.structuredContent["interpretation_status"] == "unavailable"
    assert approximate.structuredContent["anchor_summary"] == "approximate birth anchor; 3 samples at 5-minute steps"
    assert len(json.dumps(approximate.structuredContent, ensure_ascii=False).encode()) < 512 * 1024
    serialized = json.dumps(approximate.structuredContent, ensure_ascii=False)
    assert "What Jaimini factors" not in serialized
    assert '"latitude"' not in serialized and '"longitude"' not in serialized
