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
- Golden values are Moshier-fallback specific; the golden test skips if `.se1` files are installed.
- `ENGINE_LOCK` is held across apply+compute in the facade. True multi-request parallelism still needs a process/subprocess pool (Phase 3 concern when FastAPI lands).
- `karana` index→name mapping assumed 0-based; raw index always preserved if the name table is off.
- `rahu_ketu` node mode is captured for provenance but not yet wired to PyJHora (Phase 2 TODO in `config.py`).
