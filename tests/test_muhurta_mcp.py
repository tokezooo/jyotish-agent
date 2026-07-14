from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import ToolAnnotations

from jyotish_agent.mcp_facade import JyotishMcpFacade
from jyotish_agent.mcp_models import MuhurtaMcpInput
from jyotish_agent.mcp_server import build_server


def _payload(**updates):
    value = {
        "activity": "focused_work_session_v1",
        "place": {"name": "Moscow", "latitude": 55.7558, "longitude": 37.6173, "zone_id": "Europe/Moscow"},
        "start": "2026-07-15T00:00:00+03:00",
        "end": "2026-07-16T00:00:00+03:00",
        "duration_minutes": 90,
        "hard_constraints": {"require_daylight": True},
    }
    value.update(updates)
    return value


def test_exactly_one_additive_read_only_idempotent_tool(tmp_path: Path) -> None:
    facade = JyotishMcpFacade(tmp_path, None)
    server = build_server(facade)
    tool = server._tool_manager.get_tool("muhurta")
    assert tool is not None
    assert tool.annotations == ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    names = set(server._tool_manager._tools)
    assert {"calculate", "jaimini", "prashna", "muhurta"} <= names
    assert len([name for name in names if name == "muhurta"]) == 1


def test_mcp_ru_en_no_window_limit_and_no_persistence(tmp_path: Path) -> None:
    facade = JyotishMcpFacade(tmp_path, None)
    ru = facade.muhurta(MuhurtaMcpInput.model_validate(_payload()))
    en = facade.muhurta(MuhurtaMcpInput.model_validate(_payload(
        place={"name": "Kolkata", "latitude": 22.5726, "longitude": 88.3639, "zone_id": "Asia/Kolkata"},
        start="2026-07-15T00:00:00+05:30", end="2026-07-18T00:00:00+05:30", duration_minutes=60,
    )))
    empty = facade.muhurta(MuhurtaMcpInput.model_validate(_payload(hard_constraints={"excluded_weekdays": [2]})))
    assert ru.mode == en.mode == empty.mode == "muhurta"
    assert ru.status == en.status == empty.status == "completed"
    assert empty.windows == ()
    assert not list(tmp_path.rglob("*.json")) and not list(tmp_path.rglob("*.db"))
    dumped = json.dumps(ru.model_dump(mode="json"), ensure_ascii=False)
    assert "55.7558" not in dumped and "37.6173" not in dumped


def test_malformed_payload_is_privacy_safe(tmp_path: Path) -> None:
    facade = JyotishMcpFacade(tmp_path, None)
    secret = "PRIVATE PLACE AND CONSTRAINT"
    result = facade.muhurta_payload({"activity": secret, "place": {"name": secret}})
    dumped = result.model_dump_json()
    assert result.status == "needs_input"
    assert result.error_code == "INPUT_INVALID"
    assert secret not in dumped


def test_real_process_stdio_ru_en_empty_limits_and_safety(tmp_path: Path) -> None:
    asyncio.run(_stdio_cases(tmp_path))


async def _stdio_cases(tmp_path: Path) -> None:
    env = {**os.environ, "JYOTISH_AGENT_DATA_ROOT": str(tmp_path / "data")}
    params = StdioServerParameters(command=sys.executable, args=["-m", "jyotish_agent.mcp_server"], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            ru = await session.call_tool("muhurta", {"request": _payload()})
            en = await session.call_tool("muhurta", {"request": _payload(
                place={"name": "Kolkata", "latitude": 22.5726, "longitude": 88.3639, "zone_id": "Asia/Kolkata"},
                start="2026-07-15T00:00:00+05:30", end="2026-07-18T00:00:00+05:30", duration_minutes=60,
            )})
            empty = await session.call_tool("muhurta", {"request": _payload(hard_constraints={"excluded_weekdays": [2]})})
            oversized = await session.call_tool("muhurta", {"request": _payload(end="2026-08-20T00:00:00+03:00")})
            cancelled = await session.call_tool("muhurta", {"request": _payload(cancel_requested=True)})
            unsafe = await session.call_tool("muhurta", {"request": _payload(activity="elective_medical")})
    assert all(result.isError is False for result in (ru, en, empty, oversized, cancelled, unsafe))
    assert ru.structuredContent["status"] == en.structuredContent["status"] == "completed"
    assert empty.structuredContent["windows"] == []
    assert oversized.structuredContent["error_code"] == "SEARCH_RANGE_TOO_LARGE"
    assert oversized.structuredContent["next_action"] == "narrow_search_range"
    assert cancelled.structuredContent["status"] == "incomplete"
    assert unsafe.structuredContent["error_code"] == "HIGH_STAKES_ACTIVITY"
    for result in (ru, en):
        payload = json.dumps(result.structuredContent, ensure_ascii=False)
        assert '"latitude"' not in payload and '"longitude"' not in payload
        assert len(payload.encode()) < 512 * 1024
