"""Regenerate the golden chart fixture.

Run after an INTENTIONAL change to the facade output. Review the git diff of the
fixture before committing — an unexpected change means a calculation regression.

    python scripts/regen_golden.py

The golden values are Moshier-fallback specific (no .se1 files). The matching test
skips when Swiss ephemeris files are installed.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

from jyotish_agent.pyjhora_facade import BirthProfile, compute_chart

# Keep in sync with tests/test_pyjhora_facade_golden.py.
PROFILE = BirthProfile(
    name="Chennai Test",
    date=(1990, 1, 1),
    time=(12, 30, 0),
    latitude=13.0827,
    longitude=80.2707,
    timezone=5.5,
)
REFERENCE = (2026, 6, 7)
GOLDEN = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "golden_chennai_1990.json"


def main() -> int:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out = compute_chart(PROFILE, reference_date=REFERENCE)
    GOLDEN.write_text(json.dumps(out, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"wrote {GOLDEN}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
