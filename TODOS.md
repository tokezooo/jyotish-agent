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
- [ ] Add Pi extension tool registrations (Phase 4).
- [ ] Add Jyotish reading skill with fact-citation rules (Phase 5).

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
