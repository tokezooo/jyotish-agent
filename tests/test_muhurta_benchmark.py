from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_one_day_benchmark_runner_emits_config_metadata() -> None:
    root = Path(__file__).parents[1]
    completed = subprocess.run(
        [sys.executable, "scripts/benchmark_muhurta.py", "--runs", "1"],
        cwd=root, check=True, capture_output=True, text=True,
    )
    result = json.loads(completed.stdout.splitlines()[-1])
    assert result["case"] == "one_day_moscow_focused_work_90m"
    assert result["warm_runs"] == 1
    assert result["config_sha256"]
    assert result["rule_profile_sha256"]
    assert result["source_map_sha256"]
    assert result["ephemeris_mode"] in {"moshier", "swiss"}
    assert result["runner"] == "scripts/benchmark_muhurta.py"
