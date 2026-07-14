# TODOs

## Deferred Scope

- Public SaaS deployment.
- User accounts and persistence beyond local fixtures.
- Chart rendering or GUI.
- Marriage compatibility.
- Remedies, gemstones, and deterministic prediction workflows.
- Broad yoga/dosha coverage beyond a small verified list.
- Automatic place/timezone resolver.
- Qualified source admission and human adjudication for Jaimini, Prashna, and Muhurta.
- Governed Jaimini doctrine, Prashna judgement, and Muhurta ranking/personalization.
- 10–20 real/concierge sessions and reviewer material-error/value measurements.
- Doctrinal-quality held-out evals after governed sources and qualified reviewers exist.
- Real deep Codex conversational cases for all three domains; current evidence is quick plus inspection.
- Complete held-out release evals with independent Jaimini geometry values and school-labeling cases.

## Additive domain release status (2026-07-14)

- [x] Jaimini Core v1 signed geometry/timing and exact/approximate sensitivity.
- [x] Praśna work/project facts with sealed explicit/capture/replay anchors.
- [x] Muhūrta general/focused-work boundaries, hard constraints, and near misses.
- [x] Read-only MCP tools, snapshots, privacy projection, RU/EN docs, benchmark, audit.
- [ ] Admit governed sources/reviewers before enabling prose or ranking.
- [x] Run real Codex conversational RU/EN quick and inspection smokes for all three domains.
- [x] Run held-out calculation/trust adversarial domain evals (15 independently authored cases).
- [ ] Run one real deep Codex case per domain; inspection does not satisfy the plan's deep-mode gate.
- [ ] Add held-out independent Jaimini geometry expected values and school-labeling cases.
- [ ] Run adjudicated real/concierge sessions and doctrinal-quality held-out evals.

## Next Implementation Tasks

- [x] Decide AGPL-safe PyJHora usage model: **local-only** (private repo; AGPL distribution obligations not triggered).
- [x] Add `pyproject.toml` and baseline Python package.
- [x] Add PyJHora headless import smoke test.
- [x] Add ephemeris/data availability check (`scripts/check_pyjhora_data.py`, `--strict` + liveness compute).
- [x] Implement D1/D9/panchanga/Vimshottari facade (`src/jyotish_agent/pyjhora_facade.py`).
- [x] Add one golden birth-profile fixture (`tests/fixtures/golden_chennai_1990_moshier.json`; renamed mode-keyed in Phase 7).
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

## Known limits (post-Phase-9)

- Prose-citation check is PARTIAL (Phase 9): it flags "<Planet> in <Sign>" claims that contradict the charts (common English phrasing only). It does NOT catch paraphrases ("occupies", "exalted in"), other phrasings/languages, or non-placement claims (aspects/dashas). Cross-chart claims are validated at planet-level union (a claim true in any computed chart passes). The skill rule (cite everything) remains primary.
- `jyotish_check_answer` / `jyotish_screen_question` are NOT harness-forced — a non-compliant agent could skip them. True enforcement needs Pi-harness support (a required-tool / pre-response hook) that the extension layer cannot provide; documented as best-effort. **Not closeable in our code.**
- Safety screen is best-effort keyword-based, now English + Russian (Phase 9), with context regexes for collision-prone terms (cancer/рак vs the sign Cancer/Раке). Still misses paraphrases/other languages.
- Golden values are Moshier-fallback specific; install `.se1` for Swiss parity (Phase 7).

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
- (Phase 6.2) Whole-sign houses: every planet carries a `house` (from its chart's own lagna), and `facts["houses"]` is a 12-entry D1 bhava table (sign + classical lord). Citation paths `d<N>.<Planet>.house`, `houses.<N>.sign/.lord`. Per-varga bhava tables (sign+lord for D9 etc.) are out of MVP scope; classical single-lord rulerships only.
- (Phase 6.3) Graha drishti (D1 aspects): all planets aspect 7th; Mars 4/7/8, Jupiter 5/7/9, Saturn 3/7/10. `facts["aspects"]` per planet (aspected signs/houses/planets). Citation path `aspects.<From>.<To>`=`true`. Scope: D1-only, conjunctions not treated as aspects, Rahu/Ketu 7th-only (node special aspects are school-dependent — revisit).

## Feature-breadth milestone: CLOSED at 6.3

Interpretive surface (all citation-enforced): D1/D2/D3/D7/D9/D10/D12 + per-planet whole-sign houses + D1 bhava table with house lords + D1 graha drishti + Vimshottari + panchanga.

- 6.4 (broad yogas/doshas) remains deferred (text-dependent, high correctness-risk). A NARROW set shipped in Phase 10 (below) per the agreed scoping; broad coverage stays out.

### Phase 7: Swiss `.se1` ephemeris parity (DONE)

- `scripts/install_ephemeris.py` downloads sepl/semo/seas `_18.se1` into PyJHora's ephe dir (not committed; licensed separately). `ephemeris_mode()` then reports `swiss` and star-based ayanamsas (TRUE_CITRA etc.) compute instead of crashing.
- Golden fixtures keyed by mode: `golden_chennai_1990_{moshier,swiss}.json`. CI without `.se1` runs the Moshier baseline; both paths verified (83 pass, 2 mode-specific skips each).
- Parity: Swiss vs Moshier agree to within 0.1° (same sign) — confirms the fallback was a faithful approximation (LAHIRI Sun differed by ~5e-6°). True external-reference parity (vs astro.com/JHora published values) still needs trusted source data — future.

### Phase 8: per-varga bhava + varga lagnas + node aspects (DONE)
- `facts["lagnas"]` (each chart's own lagna; `d1` aliases `ascendant`) and `facts["bhava"]` (each chart's 12-house table; `d1` aliases `houses`). Chart keys lowercased (`d1`/`d9`). Citation paths `lagnas.<chart>.sign`, `bhava.<chart>.<N>.sign/.lord`.
- `config.node_aspects` ("standard" 7th-only | "jupiter_like" 5/7/9) tunes Rahu/Ketu drishti; bad value -> 422.

### Phase 9: trust-boundary hardening (DONE, partial)
- Prose-contradiction detection wired into `/answers/validate` (flags "<Planet> in <Sign>" claims that contradict the charts; best-effort English phrasing, negation-aware, planet-level union). See Known limits.
- Multilingual safety screen: English + Russian keywords, with context regexes so the zodiac sign Cancer/Раке is not screened as the disease cancer/рак.
- Harness-forced gates: NOT done — a Pi-harness limitation (documented in Known limits), not closeable in the extension layer.

### Phase 10: narrow geometric yogas (DONE)
- `src/jyotish_agent/yogas.py`: 3 unambiguous positional yogas — Gajakesari (Jupiter in a kendra from the Moon), Chandra-Mangala (Moon+Mars same rasi), Budha-Aditya (Sun+Mercury same rasi). D1 only. Each emits `present` + the exact `definition` + `basis` geometry. No orbs/strength/combustion/cancellation (stated). Citation atom `yogas.<Name>.present`. Broad yoga coverage stays deferred.

### Milestone 3: Strength, Points, Time (DONE 2026-07-11, /autoplan-reviewed)

Opt-in fact modules via `config.modules` (default empty; unknown or unimplemented -> 422):

- Phase 11 `shadbala`: six-fold strength, 7 grahas, component labels pinned by classical naisargika constants; atoms `shadbala.<P>.rupas/.strength_ratio/.components.<name>`.
- Phase 12 `ashtakavarga`: raw BAV/SAV (pre-sodhana, stated), SAV==337 invariant, BAV Lagna row kept, strict bindu validation; atoms `ashtakavarga.sav.<Sign>`, `ashtakavarga.bav.<P>.<Sign>`.
- Phase 13 `transits`: gochara at noon-anchored reference_date (offset-aware `transits.anchor`), houses from natal Moon AND natal lagna, Gochara×SAV join (`sav_points`) when both modules on; Saturn cross-checked externally (sidereal Pisces, June 2026).
- Phase 14 `yogas_engine`: two-tier per gate decision — engine scan per configured chart (~284 checks, stdout captured, error count + status field, prediction prose excluded, stable snake_case keys); verified `yogas` tier authoritative, mismatch surfaces as warning; skill mandates hedged phrasing.
- Phase 15 `varshaphal`: Tajaka annual chart under its honest name (NOT progressions), pravesh-bracketed year selection (solar-return boundaries, noon-anchored), munthi included; year lord dropped — engine's lord_of_the_year has real bugs (mean-year drift + candidate-index return), documented.

Each phase: dev subagent -> adversarial review (Codex; Phase 15 [subagent-only], Codex usage limit) -> fixes -> merge. 183 Python tests (was 115 pre-milestone).

### Candidate future milestones (not started)
- Extend the prose check beyond literal "<Planet> in <Sign>" English phrasing (aspects/dashas, paraphrase, other languages). Harness-forced check/screen gates need Pi support. External-reference parity (vs astro.com/JHora). More vargas/yogas only with the same verification bar.

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
