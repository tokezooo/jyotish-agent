# Jyotish Agent

Agentic Jyotish assistant built around deterministic Vedic astrology calculations from
PyJHora and a Pi-based agent harness.

The first milestone is deliberately narrow:

- normalize birth data into a stable chart request
- compute D1, D9, panchanga, and Vimshottari facts through a Python service
- expose those facts to Pi as explicit tools
- let the LLM explain only from cited calculation facts, not from hidden intuition

## Current State

All five MVP phases are in place: Python 3.12 project, headless PyJHora deps pinned,
ephemeris/data check, the calculation facade (`compute_chart()` → deterministic
ascendant, D1, D9, panchanga basics, current Vimshottari period, golden-tested),
a FastAPI service, a Pi extension exposing the tools, and the fact-citation answer
contract that makes the trust boundary enforceable. See:

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

### Ephemeris (optional)

PyJHora wheels ship no Swiss ephemeris (`.se1`) files, so by default calculations run
through the pyswisseph **Moshier fallback** — repeatable and sub-arcsecond accurate
for modern dates, but star-based ayanamsas (TRUE_CITRA / TRUE_REVATI / TRUE_PUSHYA)
crash under it. To switch to full Swiss precision and enable those ayanamsas:

```bash
uv run python scripts/install_ephemeris.py          # downloads se1 into jhora/data/ephe
uv run python scripts/check_pyjhora_data.py --strict  # verifies Swiss mode
```

The `.se1` files are not committed (licensed separately; re-run after a fresh
`uv sync`). Golden test fixtures are keyed by mode
(`golden_chennai_1990_{moshier,swiss}.json`); CI without `.se1` runs the Moshier
baseline, and Swiss vs Moshier agree to within 0.1° (verified by a parity test).

## API

```bash
uv run uvicorn jyotish_agent.api:app --reload   # http://127.0.0.1:8000 (docs at /docs)
```

- `POST /birth-profiles/validate` — normalize a birth profile, return soft warnings.
- `POST /charts/compute` — deterministic fact set (ascendant + per-chart lagnas,
  divisional charts with whole-sign houses per planet, per-varga bhava tables with
  house lords, D1 graha drishti aspects, a narrow set of geometric yogas, panchanga,
  current Vimshottari period) plus warnings, provenance, and a `facts_token`.
  `config.node_aspects` ("standard" | "jupiter_like") tunes Rahu/Ketu drishti.
  `config.charts` selects divisional charts from D1, D2, D3, D7, D9, D10 (career),
  D12 — D1 is always included; defaults to D1+D9.
- `POST /answers/validate` — enforce the fact-citation contract: checks an answer's
  `facts_used` against the computed facts, and additionally scans the `summary` for
  "<Planet> in <Sign>" claims that contradict the charts (best-effort, common English
  phrasing only — not a full prose check). The `facts_token` (from `/charts/compute`)
  binds validation to real output, so an answer can't self-certify against forged facts.
- `POST /questions/screen` — best-effort keyword screen (medical/legal/financial/
  self-harm/deterministic-harm), English + Russian, with a suggested redirect.
  Advisory; the agent's own judgement is the primary safeguard.
- `GET /health` — liveness.

Errors are RFC 7807 `application/problem+json` with `problem` / `cause` / `fix`
fields. Birth data is never logged or echoed into error bodies.

Set `JYOTISH_SIGNING_KEY` to a fixed secret in any multi-process or multi-restart
deployment so `facts_token`s verify across workers (a random per-process key is used
if unset).

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

Tools registered: `jyotish_screen_question`, `jyotish_validate_birth_data`,
`jyotish_compute_chart`, `jyotish_check_answer`. Set `JYOTISH_API_URL` to point at a
non-default service (loopback HTTP by default; a non-loopback non-HTTPS URL triggers
a plaintext-PII warning). The `jyotish-reading` skill (`.pi/skills/`) drives the
flow: screen → compute → draft answer (summary / facts_used / uncertainty /
followups) → `jyotish_check_answer` → answer. Nothing in the harness *forces* the
check tool to run; the gate is enforced by the skill, so it is best-effort by
construction.

Note: the `pi.registerTool` wiring needs a live Pi session and is not covered by the
bun tests (which cover the pure helpers, the typebox schema as a Python-model drift
guard, and the HTTP path via a mocked `fetch`).

## Source References

- PyJHora: https://github.com/naturalstupid/PyJHora
- Pi: https://pi.dev/docs/latest

