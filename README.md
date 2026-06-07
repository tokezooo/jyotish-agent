# Jyotish Agent

Agentic Jyotish assistant built around deterministic Vedic astrology calculations from
PyJHora and a Pi-based agent harness.

The first milestone is deliberately narrow:

- normalize birth data into a stable chart request
- compute D1, D9, panchanga, and Vimshottari facts through a Python service
- expose those facts to Pi as explicit tools
- let the LLM explain only from cited calculation facts, not from hidden intuition

## Current State

Phases 1–4 are in place: Python 3.12 project, headless PyJHora deps pinned,
ephemeris/data check, the calculation facade (`compute_chart()` → deterministic
ascendant, D1, D9, panchanga basics, current Vimshottari period, golden-tested),
a FastAPI service exposing validation and chart computation, and a Pi extension
exposing those as agent tools. The interpretation contract (Phase 5) is not
implemented yet. See:

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

## API

```bash
uv run uvicorn jyotish_agent.api:app --reload   # http://127.0.0.1:8000 (docs at /docs)
```

- `POST /birth-profiles/validate` — normalize a birth profile, return soft warnings.
- `POST /charts/compute` — deterministic fact set (ascendant, D1, D9, panchanga,
  current Vimshottari period) plus warnings and provenance.
- `GET /health` — liveness.

Errors are RFC 7807 `application/problem+json` with `problem` / `cause` / `fix`
fields. Birth data is never logged or echoed into error bodies.

Regenerate the golden test fixture after intentional output changes:

```bash
uv run python scripts/regen_golden.py
```

## Pi extension

The repo holds two toolchains: `src/jyotish_agent/` is the Python service, `.pi/` is
the Pi agent harness (extension + skill). The extension calls the HTTP API above, so
**start the service first**, then load the extension.

```bash
bun install                                   # TS deps for the extension
bun run typecheck                             # tsc against real Pi types
bun test ./.pi/extensions/jyotish.test.ts     # pure-helper + schema + HTTP tests

uv run uvicorn jyotish_agent.api:app          # terminal 1: the service
pi --extension .pi/extensions/jyotish.ts      # terminal 2: a Pi session with the tools
```

Tools registered: `jyotish_validate_birth_data`, `jyotish_compute_chart`. Set
`JYOTISH_API_URL` to point at a non-default service (loopback HTTP by default; a
non-loopback non-HTTPS URL triggers a plaintext-PII warning). The `jyotish-reading`
skill (`.pi/skills/`) tells the agent to cite only computed facts.

Note: the `pi.registerTool` wiring needs a live Pi session and is not covered by the
bun tests (which cover the pure helpers, the typebox schema as a Python-model drift
guard, and the HTTP path via a mocked `fetch`).

## Source References

- PyJHora: https://github.com/naturalstupid/PyJHora
- Pi: https://pi.dev/docs/latest

