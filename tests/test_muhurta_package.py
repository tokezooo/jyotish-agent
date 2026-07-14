from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path


def test_wheel_contains_muhurta_governance_data(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(tmp_path)], cwd=root, check=True, capture_output=True)
    wheel = next(tmp_path.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    assert "jyotish_agent/data/muhurta/muhurta_focused_work_v1.json" in names
    assert "jyotish_agent/data/muhurta/muhurta_focused_work_v1_sources.json" in names
    assert "jyotish_agent/data/muhurta/adjudication_fixtures_v1.json" in names
