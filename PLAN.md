<!-- /autoplan restore point: ~/.gstack/projects/jyotish-agent/main-autoplan-restore-20260711-015259.md -->
# Plan: Milestone 3 — Strength, Points, Time (Phases 11–15)

Reviewed by /autoplan (CEO + Eng/DX Claude subagents + Codex, 2026-07-11). All
mechanical review findings are folded in below; premises and user challenges are
resolved at the approval gate.

## Current Context

Working system (Phases 1–10 + fixes, main @ c406baf): PyJHora facade → FastAPI →
Pi tools with an enforceable fact-citation contract (facts_token server cache,
prose-contradiction check, safety screen). 115 Python + 13 bun tests. Live agent
verified on gemini-3.5-flash.

## Availability Probe (verified against installed PyJHora 4.8.6, incl. timing)

| Feature | PyJHora surface | Status / measured |
|---|---|---|
| Shadbala | `strength.shad_bala(jd, place)` | ✅ 2ms. Returns `[sthana, kaala, dig, cheshta, naisargika, drik, sum, rupa, strength_ratio]` — NOTE order: kaala BEFORE dig (verified at strength.py:995) |
| Ashtakavarga | `ashtakavarga.get_ashtaka_varga(h_to_p)` | ✅ <1ms. Raw (pre-sodhana) BAV/SAV; SAV sums to 337; BAV has 8 rows — row 7 is Lagna |
| Transits (gochara) | none — derive from own `divisional_chart` at reference date | ⚠️ noon-anchor convention must be explicit (Moon ~13°/day) |
| Progressions | none (Western) | ⚠️ Vedic analog = Tajaka varshaphal; `annual_chart(jd_dob, place, years=N)` = (N-1)th solar return; year bounded by PRAVESH (solar-return moment), not Jan 1 |
| Full yogas | `yoga.get_yoga_details(jd, place, divisional_chart_factor=f)` per chart (~30ms) | ✅ 284 distinct yoga keys. Composite all-charts call (0.69s, 23 vargas) DISCARDS per-chart presence — must call per configured chart |

## Premises (resolved at the /autoplan gate)

P-1. "Transits" = classical gochara at `reference_date` anchored at local noon
(documented convention, anchor time surfaced in facts), houses counted from natal
Moon and natal lagna. Vedha/kakshya out of scope (stated).

P-2. RESOLVED at gate (2026-07-11): Tajaka varshaphal under its own honest name
(module "varshaphal", not "progressions"), WITH munthi + year lord, solar-return
year bracketing. Western progressions stay out of scope.

P-3. RESOLVED at gate (2026-07-11): two-tier yoga facts. Verified `yogas` tier
(ours) is authoritative; `yogas_engine` tier ships with skill-forced verbal hedge,
stable keys, stdout capture, error count, status field. Mismatch: verified tier
wins, disagreement surfaces as warning.

P-1. RESOLVED at gate: approved as stated (noon anchor, from-Moon/from-lagna).
Full plan APPROVED; order 11 → 12 → 13 → 14 → 15.

## Architecture decision (all voices agreed): opt-in fact modules

`CalculationConfig.modules: tuple[str, ...]` mirroring `charts` — e.g.
`("shadbala", "ashtakavarga", "transits", "yogas_engine", "varshaphal")`, default
`()` (empty). Reasons: citation atoms would grow ~170 → ~450 always-on; yoga call
would grow the ENGINE_LOCK hold from ~10ms to ~0.7s (throughput cap ~1.4 req/s);
default golden fixtures stay byte-identical (back-compat); the agent requests only
what the question needs (skill documents when). A second all-modules golden covers
the new surface. Unknown module name → ConfigError → 422, same as charts.

## Phases

### Phase 11: Shadbala (module "shadbala")
- `strength.shad_bala(jd, place)` → `facts["shadbala"]` per planet (7 grahas):
  `{total_rupas, strength_ratio, components: {sthana, kaala, dig, cheshta,
  naisargika, drik}}` — component order per verified engine output (kaala before
  dig). Drik can be NEGATIVE (engine formula) — tests must allow it. No `rank`
  field (raw-rupas vs ratio ranks differ; agent can order by either number).
- Label verification: assert naisargika constants (Sun 60, Saturn ≈8.57 virupas —
  order-identifying) + one hand-checked dig bala.
- Atoms: `shadbala.<Planet>.rupas`, `shadbala.<Planet>.strength_ratio`,
  `shadbala.<Planet>.components.<name>`.
- Tests: golden values, component-sum ≈ total (negative drik allowed), naisargika
  label pins, atoms round-trip via /answers/validate.

### Phase 12: Ashtakavarga (module "ashtakavarga")
- Raw (pre-sodhana — stated in provenance) BAV/SAV → `facts["ashtakavarga"]`:
  `{sav: {<Sign>: points}×12, bav: {<Planet|Lagna>: {<Sign>: points}}}` — BAV row
  7 surfaced as "Lagna" (not dropped).
- Invariants: SAV total == 337; each BAV cell in 0..8; input h_to_p built from
  placements incl. nodes (pinned by test).
- Atoms: `ashtakavarga.sav.<Sign>`, `ashtakavarga.bav.<Planet>.<Sign>`.
- **Gochara×SAV join** (approved scope expansion, both-phase blast radius): when
  both `transits` and `ashtakavarga` modules are on, emit
  `transits.<Planet>.sav_points` = SAV of the transited sign — the classical
  transit-strength readout, zero new engine surface.

### Phase 13: Gochara transits (module "transits")
- Compute D1 positions at `reference_date` (noon-local anchor, anchor surfaced as
  `transits.anchor` fact) via the existing divisional path; emit per planet
  `{sign, house_from_moon, house_from_lagna}` + `natal_moon_sign`. NO
  transit-lagna-relative houses (meaningless — verified finding); `_placements`
  not reused as-is.
- Atoms: `transits.<Planet>.sign`, `transits.<Planet>.house_from_moon`,
  `transits.<Planet>.house_from_lagna` (+ `.sav_points` when joined).
- Tests: reference-date change moves transits; natal facts unchanged; Moon-sign
  ingress boundary both sides of an anchor; Saturn position cross-checked against
  an external ephemeris value (not the same engine).

### Phase 14: Engine yoga verdicts (module "yogas_engine") — GATED ON P-3
- If approved (two-tier): call `get_yoga_details(jd, place,
  divisional_chart_factor=f)` per configured chart (~30ms each). Emit
  `facts["yogas_engine"]`: `{<chart>: [{key, name, present: true}]}` keyed by the
  STABLE function key (e.g. `vesi_yoga`), not locale display names. Engine
  benefit/prediction prose EXCLUDED from facts (safety). stdout captured
  (`redirect_stdout`); suppressed-error count surfaced as
  `provenance.yoga_engine_errors`; golden asserts errors == 0; status field
  distinguishes `unavailable` from "none detected".
- Skill: engine verdicts must be verbally hedged ("PyJHora engine detects X;
  definition not independently verified"); absences phrased as "not among detected
  yogas", never as a fact. Mismatch policy: our verified `yogas` tier wins;
  disagreement surfaces as a warning.
- Atoms: `yogas_engine.<chart>.<key>.present` = "true" (detected only).

### Phase 15: Tajaka varshaphal (module "varshaphal") — GATED ON P-2
- If approved: select year N s.t. `pravesh_jd(N) <= ref_jd < pravesh_jd(N+1)`
  (solar-return bracketing, NOT calendar year); guard ref < birth. Emit annual
  lagna, annual D1 placements, pravesh moment (ISO via `_fmt_dt`, not the engine's
  to_dms string), munthi, year lord.
- Atoms: `varshaphal.lagna.sign`, `varshaphal.<Planet>.sign`,
  `varshaphal.munthi.sign`, `varshaphal.year_lord`.
- Tests: both sides of the pravesh boundary, ref-before-birth 422, determinism.

Cross-phase: per-module payload/atom-count budget regression test; lock-hold
latency test with all modules on; concurrent mixed-config test (no ayanamsa bleed,
p95 under the Pi client timeout). Each phase: own branch → build → /review
pre-merge → regen goldens (default golden must NOT change; all-modules golden
regens) → merge.

## NOT in scope
- Western secondary progressions / solar arcs (no engine support).
- Strength/points interpretation thresholds ("strong/weak" cutoffs — numbers only).
- Vedha/kakshya gochara refinements; Tajaka sahams/yogas beyond the annual basics.
- Ashtakavarga sodhana (trikona/ekadhipatya reductions) — raw tables only, stated.
- Muhurta, remedies, compatibility (unchanged).

## What already exists
- Whole-sign house math (reused for from-Moon/from-lagna counting) — Phase 6.2.
- Divisional compute at arbitrary dates (transit chart) — Phase 6.1.
- Citation/atom/token pipeline + server cache — Phases 5/9 + fix.
- Golden dual-mode fixture infra + regen script — Phase 7.
- ConfigError → 422 plumbing for new config fields — Phases 3/8.

## Failure Modes Registry
| Failure | User impact | Mitigation |
|---|---|---|
| Yoga fn throws under one ephemeris only | silent shrink of yoga list, goldens pass | stdout capture + error count in provenance + golden asserts 0 |
| Wrong annual chart near solar return | wrong varshaphal ~half the year | pravesh bracketing + boundary tests |
| Shadbala labels swapped | mislabeled strength components, no error | naisargika constant pins |
| Transit Moon ambiguous within day | disputed Moon sign | explicit noon anchor surfaced in facts + skill note |
| Payload bloat with all modules | agent context blowup, slow tools | opt-in modules, budget regression test |

## Decision Audit Trail

| # | Phase | Decision | Classification | Principle | Rationale | Rejected |
|---|---|---|---|---|---|---|
| 1 | Arch | Opt-in `config.modules`, default empty | Mechanical | P5/P1 | All 3 voices: atom×2.5 growth, 0.7s lock hold, golden churn if always-on | always-on facts |
| 2 | Arch | Single compute endpoint kept (no per-feature endpoints) | Mechanical | P5 | facts_token signs ONE facts block; split endpoints would need token merging | separate endpoints |
| 3 | P11 | Component order per engine (kaala before dig); no rank field; negative drik allowed | Mechanical | P1 | Verified at strength.py:995; const.shad_bala_factors cannot verify order — naisargika pins can | plan's original order |
| 4 | P12 | Raw pre-sodhana tables, BAV Lagna row kept, SAV==337 invariant | Mechanical | P1 | Verified engine output shape | dropping Lagna row |
| 5 | P12/13 | Gochara×SAV join emitted when both modules on | Auto-approved expansion | P2 | CEO voice: highest interpretive value per LOC; zero new engine surface; in blast radius | omitting the join |
| 6 | P13 | Noon-local anchor, surfaced in facts; no transit-lagna houses | Mechanical | P5 | Moon ~13°/day; transit-chart lagna at birth place is meaningless | reusing _placements as-is |
| 7 | P14 | Per-chart get_yoga_details, stable fn keys, stdout capture, error count, status field, prose excluded | Mechanical | P1/P5 | Composite API discards per-chart presence (verified); locale names unstable; print-and-continue hides failures | composite all-charts call |
| 8 | P15 | Pravesh-bracketed year selection; munthi + year lord included | Mechanical | P1 | Calendar-year formula wrong ~half the year (verified); bare annual chart interpretively inert | ref.year - birth.year + 1 |
| 9 | Goldens | Default golden unchanged; second all-modules golden | Mechanical | P1 | Default byte-stability = back-compat proof; feature surface still golden-tested | regen single golden |
| 10 | Scope | External-reference parity (JHora desktop / astro.com values) for shadbala+SAV | TASTE → included as validation task in P11/P12 tests | P1 | CEO voice: engine-agrees-with-itself isn't verification; published tables exist | self-consistency only |

## GSTACK REVIEW REPORT

| Review | Status | Findings |
|---|---|---|
| CEO Review | concerns_resolved_at_gate | P-3 trust dilution (critical→gated), P-2 semantics (gated), external parity added, SAV×gochara join added |
| Design Review | skipped | no UI scope |
| Eng Review | concerns_folded | opt-in modules, shadbala order, yoga per-chart API, pravesh bracketing, stdout capture, transit anchor |
| DX Review | concerns_folded | payload/atom budget, module opt-in ergonomics, absence-phrasing skill rule |

CEO DUAL VOICES — CONSENSUS: premises valid 2/3 (P-2, P-3 challenged by both models → USER CHALLENGES); right problem DISAGREE (CEO voice: trust hardening > breadth; folded as parity tasks); scope calibration CONFIRMED with reorder; alternatives CONFIRMED found (oracle, two-tier, join); 6-month trajectory CONFIRMED with P-3 fix.

ENG DUAL VOICES — CONSENSUS: architecture CONFIRMED (with opt-in modules); tests CONFIRMED expanded; performance CONFIRMED (measured, not assumed); security/trust CONFIRMED (prose exclusion); error paths CONFIRMED (status field); deployment N/A (local).
