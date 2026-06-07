# Jyotish Agent

Agentic Jyotish assistant built around deterministic Vedic astrology calculations from
PyJHora and a Pi-based agent harness.

The first milestone is deliberately narrow:

- normalize birth data into a stable chart request
- compute D1, D9, panchanga, and Vimshottari facts through a Python service
- expose those facts to Pi as explicit tools
- let the LLM explain only from cited calculation facts, not from hidden intuition

## Current State

Phase 1 (repo baseline) is in place: Python 3.12 project, headless PyJHora
calculation deps pinned, ephemeris/data check, and an import smoke test. The
facade, API, and Pi tooling (Phases 2–4) are not implemented yet. See:

- [PRD.md](PRD.md)
- [PLAN.md](PLAN.md)

## Quickstart

Requires [uv](https://docs.astral.sh/uv/). PyJHora is AGPL-3.0; this MVP is
**local-only** — do not distribute or deploy publicly (see [PLAN.md](PLAN.md)).

```bash
uv sync --extra dev                       # creates .venv on Python 3.12, installs deps
uv run python scripts/check_pyjhora_data.py   # verify PyJHora + ephemeris data
uv run pytest                             # run the test suite
```

Note: PyJHora wheels ship no Swiss ephemeris (`.se1`) files, so calculations run
through the pyswisseph **Moshier fallback** (repeatable, slightly lower precision).
For full Swiss-ephemeris parity, copy `se*.se1` into the installed
`jhora/data/ephe` directory.

## Source References

- PyJHora: https://github.com/naturalstupid/PyJHora
- Pi: https://pi.dev/docs/latest

