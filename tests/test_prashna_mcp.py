from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from jyotish_agent.mcp_facade import JyotishMcpFacade
from jyotish_agent.mcp_models import PrashnaMcpInput


PLACE = {
    "name": "Moscow",
    "latitude": 55.7558,
    "longitude": 37.6173,
    "zone_id": "Europe/Moscow",
}


def test_mcp_facade_prashna_is_stateless_and_clock_is_injected(tmp_path: Path):
    facade = JyotishMcpFacade(
        tmp_path / "data",
        None,
        clock=lambda: dt.datetime(2026, 7, 14, 9, 0, tzinfo=dt.UTC),
    )
    before = facade.store.count_runs()
    result = facade.prashna(
        PrashnaMcpInput(question="Что мешает моему проекту?", capture_now=True, place=PLACE)
    )
    assert result.status == "completed"
    assert facade.store.count_runs() == before


def test_realistic_ru_en_stdio_anchor_reuse_and_mismatch(tmp_path: Path):
    asyncio.run(_stdio(tmp_path))


async def _stdio(tmp_path: Path):
    env = {**os.environ, "JYOTISH_AGENT_DATA_ROOT": str(tmp_path / "data")}
    params = StdioServerParameters(command=sys.executable, args=["-m", "jyotish_agent.mcp_server"], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            before = list((tmp_path / "data").glob("**/*"))
            ru = await session.call_tool("prashna", {"request": {
                "question": "Что сейчас мешает моему рабочему проекту?",
                "anchor": {"asked_at": "2026-07-14T12:00:00+03:00", "place": PLACE},
            }})
            captured = await session.call_tool("prashna", {"request": {
                "question": "What is blocking my work project right now?",
                "capture_now": True,
                "place": PLACE,
            }})
            token = captured.structuredContent["anchor_token"]
            en = await session.call_tool("prashna", {"request": {
                "question": "Which obstacle in this work project is most visible?",
                "anchor_token": token,
            }})
            mismatch = await session.call_tool("prashna", {"request": {
                "question": "Will my relationship last?",
                "anchor_token": token,
            }})
            after = list((tmp_path / "data").glob("**/*"))
    assert ru.isError is captured.isError is en.isError is mismatch.isError is False
    assert ru.structuredContent["status"] == captured.structuredContent["status"] == en.structuredContent["status"] == "completed"
    assert captured.structuredContent["anchor_summary"].startswith("sealed question moment:")
    assert mismatch.structuredContent["error_code"] == "ANCHOR_MISMATCH"
    assert mismatch.structuredContent["next_action"] == "create_new_anchor"
    assert before == after
    payload = json.dumps(ru.structuredContent, ensure_ascii=False)
    assert "Что сейчас" not in payload
    assert '"latitude"' not in payload and '"longitude"' not in payload
    assert len(payload.encode()) < 512 * 1024
