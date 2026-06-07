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
- [ ] Add FastAPI endpoints (Phase 3).
- [ ] Add structured RFC-7807-style errors + validation (Phase 3).
- [ ] Add Pydantic request/response models (Phase 3, replacing facade dataclasses at the boundary).
- [ ] Add Pi extension tool registrations (Phase 4).
- [ ] Add Jyotish reading skill with fact-citation rules (Phase 5).

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
