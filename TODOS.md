# TODOs

## Deferred Scope

- Public SaaS deployment.
- User accounts and persistence beyond local fixtures.
- Chart rendering or GUI.
- Marriage compatibility.
- Remedies, gemstones, and deterministic prediction workflows.
- Broad yoga/dosha coverage beyond a small verified list.
- Automatic place/timezone resolver.

## Next Implementation Tasks

- [x] Decide AGPL-safe PyJHora usage model: **local-only** (private repo; AGPL distribution obligations not triggered).
- [x] Add `pyproject.toml` and baseline Python package.
- [x] Add PyJHora headless import smoke test.
- [x] Add ephemeris/data availability check (`scripts/check_pyjhora_data.py`, `--strict` + liveness compute).
- [x] Implement D1/D9/panchanga/Vimshottari facade (`src/jyotish_agent/pyjhora_facade.py`).
- [x] Add one golden birth-profile fixture (`tests/fixtures/golden_chennai_1990.json`).
- [x] Add FastAPI endpoints (`/birth-profiles/validate`, `/charts/compute`, `/health`).
- [x] Add structured RFC-7807 problem+json errors (problem/cause/fix) + validation.
- [x] Add Pydantic request/response models at the HTTP boundary (engine stays dataclass-based).
- [x] Add Pi extension tool registrations (`.pi/extensions/jyotish.ts`: validate + compute).
- [x] Add Jyotish reading skill with fact-citation rules (`.pi/skills/jyotish-reading/SKILL.md`).
- [x] Phase 5: interpretation answer contract (summary/facts_used/uncertainty/followups) + answer-fact tests.

### Resolved in Phase-5 review (feat/phase-5-answer-contract, pre-merge)

- HMAC `facts_token`: `/charts/compute` signs facts; `/answers/validate` verifies, so the agent can't self-certify against forged facts (closes the client-supplied-facts hole). Set `JYOTISH_SIGNING_KEY` for multi-process.
- `facts_used` required non-empty; documented honestly that the check validates cited facts, not uncited prose claims.
- Non-finite (nan/inf) citations never match.
- Safety screen wired: `/questions/screen` endpoint + `jyotish_screen_question` tool (was dead code); documented as best-effort English keyword filter with redirect messages.
- README/skill updated; gate documented as skill-enforced (best-effort), not harness-forced.
- Tests: token integrity (valid/forged), empty facts_used rejected, antara/bhukti/pada/start-end atoms, case-sensitivity, non-finite, screen endpoint.

## Known limits (MVP, post-Phase-5)

- The citation check cannot read `summary` prose, so an *uncited* invented claim isn't caught by the validator — only by the skill rule. True enforcement would need answer-prose parsing or a constrained generation step.
- `jyotish_check_answer` / `jyotish_screen_question` are not harness-forced; a non-compliant agent could skip them.
- Safety screen is English keyword-based (studio is Russian-primary) — broaden or replace with model-judgement for production.
- Golden values are Moshier-fallback specific; install `.se1` for Swiss parity.

### Resolved in Phase-4 review (feat/phase-4-pi, pre-merge)

- `fetch()` wrapped: API-unreachable / timeout degrades to an RFC-7807-shaped error instead of crashing the tool. 30s client timeout combined with Pi's signal.
- `summarizeChart` guards every leaf (no `undefined°` fed to the LLM) and surfaces D9.
- typebox schemas mirror Pydantic: date/time patterns, `additionalProperties:false`, name bounds. Drift-guard test via `Value.Check`.
- Dual content blocks labeled; skill + guidelines tell the agent to cite the authoritative JSON, not the rounded summary.
- Service-supplied strings collapsed to one line (no instruction-injection via warnings/errors); non-loopback non-HTTPS `JYOTISH_API_URL` warns about plaintext PII.
- Tests: 11 bun tests (helpers + schema drift + mocked-fetch HTTP path); `pi.registerTool` wiring is e2e-only (documented).

## Phase 4 notes

- Repo is two toolchains: `src/jyotish_agent/` (Python service) + `.pi/` (Pi harness). `package.json`/`bun.lockb` sit beside `pyproject.toml`/`uv.lock`.
- (Phase 6.1) `charts` is now a first-class StringEnum array (D1/D2/D3/D7/D9/D10/D12); D1 always computed, unknown charts are a hard 422. Per-chart (varga) lagna is still dropped — only the D1 ascendant is surfaced.

### Resolved in Phase-3 review (feat/phase-3-api, pre-merge)

- Privacy/correctness: `/charts/compute` maps only `ConfigError` to 422; any other exception hits a catch-all 500 problem+json that never echoes internal/birth-derived detail. (Was a broad `except ValueError` leaking messages + mislabeling bugs.)
- Access-log middleware logs via `finally`, so 5xx/exception paths are no longer invisible.
- Typed `ChartComputeResponse` + `response_model` so Phase 4 Pi has an OpenAPI contract.
- `extra="forbid"` rejections report `(unexpected field)` instead of reflecting the client key.
- `name` capped (`max_length=200`); birth year constrained to 1800–2200.
- On-the-hour birth-time warning suppressed when confidence is `exact`.
- `reference_date` surfaced in `calculation_config` for reproducibility.
- Tests: validation/error/health run engine-free; added today()-default, 500-not-422, full-shape, ephemeris-gated star-mode coverage.

## Carried Phase-2 Notes

- Facade emits no wall-clock timestamp, so output is byte-stable; golden test relies on this.
- Golden values are Moshier-fallback specific; the golden test skips if `.se1` files are installed. (Weekday is calendar-derived and asserted unconditionally.)
- `ENGINE_LOCK` is held across apply+compute in the facade. True multi-request parallelism still needs a process/subprocess pool (Phase 3 concern when FastAPI lands).
- Regenerate the golden fixture with `python scripts/regen_golden.py` after intentional output changes; review the diff.

### Resolved in Phase-2 review (fix/phase-2-review)

- Off-by-one mislabels fixed: nakshatra/yoga are 1-based [1..27], karana is 1-based [1..60] (real 60-entry table). Guarded by `tests/test_names.py`.
- `rahu_ketu` node mode now wired via `const.set_node_mode` in `apply_config` (provenance no longer claims an unapplied setting).
- `_fmt_dt` uses `datetime`+`timedelta` (rolls past midnight correctly).
- `weekday` is the civil weekday, matching the calendar date in `normalized_input`.
- Pre-birth / out-of-span reference dates degrade to empty Vimshottari levels instead of crashing.
