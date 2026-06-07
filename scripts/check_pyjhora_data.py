"""Startup check: verify PyJHora imports headless, has data, and actually computes.

PyJHora stopped bundling ephemeris files in wheels from version 3.6.6; without
``.se1`` files under ``jhora/data/ephe`` pyswisseph falls back to its built-in
Moshier ephemeris (lower precision, and star-based ayanamsas crash). Run this
before computing any chart.

The check also does a liveness compute: a missing import or absent .se1 is not the
only failure mode — the configured ayanamsa might crash at compute time. We run one
known chart under the product default (LAHIRI) so a green check means charts work.

Usage:
    python scripts/check_pyjhora_data.py            # warn-only (degraded == OK, exit 0)
    python scripts/check_pyjhora_data.py --strict   # require .se1 files (exit 1 if absent)

Exit codes:
    0  ok
    1  import / data / liveness problem (message includes problem / cause / fix)
"""

from __future__ import annotations

import sys
from pathlib import Path


def _fail(problem: str, cause: str, fix: str) -> int:
    print("PYJHORA DATA CHECK: FAIL", file=sys.stderr)
    print(f"  problem: {problem}", file=sys.stderr)
    print(f"  cause:   {cause}", file=sys.stderr)
    print(f"  fix:     {fix}", file=sys.stderr)
    return 1


def _liveness_compute() -> tuple[bool, str]:
    """Compute one known chart under LAHIRI. Returns (ok, detail)."""
    try:
        import warnings

        from jyotish_agent.config import CalculationConfig, apply_config

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from jhora import utils
            from jhora.horoscope.chart import charts
            from jhora.panchanga import drik

            apply_config(CalculationConfig())  # LAHIRI
            place = drik.Place("Chennai", 13.0827, 80.2707, 5.5)
            jd = utils.julian_day_number((1990, 1, 1), (12, 30, 0))
            chart = charts.rasi_chart(jd, place)
        return (len(chart) == 10, f"{len(chart)} placements")
    except Exception as exc:  # noqa: BLE001 - report any compute failure verbatim
        return (False, f"{type(exc).__name__}: {exc}")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    strict = "--strict" in argv

    # Headless import: never touch jhora.ui.* (pulls PyQt into a server process).
    try:
        import jhora
    except ImportError as exc:
        return _fail(
            problem="PyJHora is not importable",
            cause=f"import jhora failed: {exc}",
            fix="Install deps: `uv sync` (or `pip install PyJHora==4.8.6`).",
        )

    pkg_dir = Path(jhora.__file__).resolve().parent
    ephe_dir = pkg_dir / "data" / "ephe"
    se_files = list(ephe_dir.glob("*.se1")) if ephe_dir.is_dir() else []

    if not se_files:
        if strict:
            return _fail(
                problem="No Swiss ephemeris (.se1) files installed",
                cause=f"{ephe_dir} has no .se1 files; Moshier fallback would be used",
                fix="Copy se*.se1 into jhora/data/ephe, or drop --strict for local MVP.",
            )
        # Degraded but acceptable for the local MVP. Still verify charts compute.
        live_ok, live_detail = _liveness_compute()
        if not live_ok:
            return _fail(
                problem="Chart liveness compute failed under Moshier fallback",
                cause=live_detail,
                fix="Check the default ayanamsa is Moshier-safe (LAHIRI) or install .se1.",
            )
        print("PYJHORA DATA CHECK: OK (DEGRADED PRECISION)")
        print(f"  jhora:   {jhora.__file__}")
        print(f"  ephe:    {ephe_dir} (no .se1 files)")
        print("  mode:    pyswisseph Moshier fallback (no Swiss ephemeris files)")
        print(f"  live:    LAHIRI D1 ok ({live_detail})")
        print("  note:    for full parity, copy se*.se1 into jhora/data/ephe.")
        return 0

    live_ok, live_detail = _liveness_compute()
    if not live_ok:
        return _fail(
            problem="Chart liveness compute failed",
            cause=live_detail,
            fix="Verify ephemeris files are valid and the default ayanamsa loads.",
        )
    print("PYJHORA DATA CHECK: OK")
    print(f"  jhora:   {jhora.__file__}")
    print(f"  ephe:    {ephe_dir}")
    print(f"  se1:     {len(se_files)} file(s)")
    print(f"  live:    LAHIRI D1 ok ({live_detail})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
