# Jyotish Doctrine Platform — Full Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Linear project `Jyotish Doctrine Platform — Full Analysis` (`LEA-516` through `LEA-544`) as a private, source-bound, fully testable doctrine platform with Full Jaimini, Full Prashna, and Expanded Muhurta releases.

**Architecture:** Add a hexagonal `jyotish_agent.doctrine` bounded context whose immutable domain core consumes existing signed fact artifacts. Filesystem/PDF/OCR, persistence, MCP/API, and conversational rendering are adapters; source manifests, compiled rules, analysis graphs, claims, and admission reports are canonically serialized and hash-addressed.

**Tech Stack:** Python 3.12, Pydantic 2, SQLite/JSON filesystem adapters, PyPDF, optional Tesseract CLI, PyJHora fact facades, FastAPI, MCP, pytest, Bun/TypeScript.

## Global Constraints

- Baseline doctrine is immutable per version; overlays are named, opt-in, and never blended implicitly.
- Copyrighted books remain under gitignored `private_sources/`; no copyrighted PDF or full text enters Git/package fixtures.
- Visible conclusions require signed facts, compiled rules, admitted source fragments, school identity, confidence, and time scope.
- Maximum two render repairs; invalid claims are removed after the second attempt.
- Missing specialist review is disclosed but does not block private `experimental_full`; missing automated evidence does block it.
- High-stakes, medical, longevity/death, remedy, guaranteed-event, dangerous, categorical legal, and categorical financial claims fail closed.
- Existing calculate, REST, MCP, and TypeScript contracts remain backward compatible; new surfaces are additive.

---

## File map

- Create `src/jyotish_agent/doctrine/models.py`: shared frozen value objects, enums, canonical identity helpers, and typed errors.
- Create `src/jyotish_agent/doctrine/sources.py`: A1 manifest loading and verification.
- Create `src/jyotish_agent/doctrine/ingestion.py`: A2 extraction/OCR ports and deterministic normalization.
- Create `src/jyotish_agent/doctrine/evidence.py`: A3 immutable fragment repository and projections.
- Create `src/jyotish_agent/doctrine/dsl.py`: A4 rule DSL and compiler.
- Create `src/jyotish_agent/doctrine/graph.py`: A5 immutable graph evaluator.
- Create `src/jyotish_agent/doctrine/renderer.py`: A6 claims, firewall, repair loop, and report projection.
- Create `src/jyotish_agent/doctrine/evaluation.py`: A7 gates, admission transitions, reports, and dashboard.
- Create `src/jyotish_agent/doctrine/jaimini_pack.py`: B1-B8 profile, topic, timing, overlay, and release orchestration.
- Create `src/jyotish_agent/doctrine/prashna_pack.py`: C1-C7 profile, radicality, taxonomy, geometry, outcome, rendering, and release orchestration.
- Create `src/jyotish_agent/doctrine/muhurta_pack.py`: D1-D7 activity, eligibility, personalization, ranking, overlay, rendering, and release orchestration.
- Create `src/jyotish_agent/data/doctrine/`: tracked manifests, rule packs, schemas, and permitted fixtures.
- Create `tests/doctrine/`: focused red-green tests aligned one-to-one with Linear issues.
- Create `docs/doctrine/` and `docs/evidence/doctrine/`: private-source handoff, operator docs, and release audits.
- Modify `.gitignore`, `pyproject.toml`, `uv.lock`, `src/jyotish_agent/mcp_models.py`, `src/jyotish_agent/mcp_facade.py`, `src/jyotish_agent/mcp_server.py`, and `.pi/extensions/jyotish.ts` only at the tasks that require their additive surfaces.

## Execution protocol for every task

1. Add the smallest focused test named for the Linear issue.
2. Run that exact test and confirm the expected behavior failure.
3. Add the minimum implementation that satisfies the issue acceptance criteria.
4. Run the focused test, then the affected subsystem tests.
5. Run `git diff --check`; inspect the diff against the issue acceptance criteria.
6. Record fresh commands/results in the Linear issue and change status only when evidence supports it.
7. Commit the independently testable deliverable with the Linear ID in the message.

## Release A — Shared Doctrine Platform

### Task 1: LEA-516 private source manifest

**Files:** `.gitignore`, `src/jyotish_agent/doctrine/models.py`, `src/jyotish_agent/doctrine/sources.py`, `src/jyotish_agent/data/doctrine/source-manifest.schema.json`, `src/jyotish_agent/data/doctrine/example-sources.json`, `tests/doctrine/test_lea_516_sources.py`, `docs/doctrine/private-source-handoff.md`.

**Produces:** `SourceManifest`, `SourceRecord`, `SourceVerifier.verify(manifest, root) -> SourceVerificationReport`.

- [ ] Write tests for incomplete records, path escape, unsafe tracked copyright, duplicate edition, missing file, hash drift, deterministic redacted report, and four-domain examples.
- [ ] Run `uv run pytest tests/doctrine/test_lea_516_sources.py -q`; expect collection/import failure for the absent doctrine package.
- [ ] Implement strict frozen models, canonical JSON identities, safe relative paths, SHA-256 verification, duplicate checks, and privacy-safe findings.
- [ ] Add `private_sources/` to `.gitignore`, the four-domain example manifest, JSON Schema, and exact operator handoff.
- [ ] Run `uv run pytest tests/doctrine/test_lea_516_sources.py -q`; expect all tests to pass.

### Task 2: LEA-517 deterministic PDF/OCR ingestion

**Files:** `pyproject.toml`, `uv.lock`, `src/jyotish_agent/doctrine/ingestion.py`, `tests/doctrine/test_lea_517_ingestion.py`, `tests/fixtures/doctrine/mixed-page-extraction.json`.

**Consumes:** verified `SourceRecord`. **Produces:** `IngestionConfig`, `NormalizedPage`, `IngestionArtifact`, `DocumentIngestor.ingest()`.

- [ ] Test byte stability, page/anchor round-trip, OCR quarantine, idempotent re-ingestion identity, tool provenance, and typed encrypted/corrupt/unsupported failures.
- [ ] Verify RED with `uv run pytest tests/doctrine/test_lea_517_ingestion.py -q`.
- [ ] Add a PyPDF text adapter, optional Tesseract port, deterministic Unicode/line normalization, anchor extraction, confidence gate, and canonical artifact hash.
- [ ] Verify GREEN and run `uv run pytest tests/doctrine/test_lea_516_sources.py tests/doctrine/test_lea_517_ingestion.py -q`.

### Task 3: LEA-518 immutable evidence store

**Files:** `src/jyotish_agent/doctrine/evidence.py`, `tests/doctrine/test_lea_518_evidence.py`.

**Consumes:** `IngestionArtifact`, manifest hash. **Produces:** `SourceFragment`, `FragmentRelation`, `EvidenceStore`, bounded public/inspection projections.

- [ ] Test append-only revisions, manifest-hash binding, explicit contradictory commentaries, stale/substituted fragments, lookup limits, and permitted-only export.
- [ ] Verify RED; implement immutable tuple-backed core plus deterministic JSON persistence adapter and source-role relations.
- [ ] Verify GREEN with `uv run pytest tests/doctrine/test_lea_518_evidence.py -q` and the A1/A2 tests.

### Task 4: LEA-519 Doctrine DSL compiler

**Files:** `src/jyotish_agent/doctrine/dsl.py`, `tests/doctrine/test_lea_519_dsl.py`.

**Consumes:** admitted fragment catalog and fact-path catalog. **Produces:** `RuleDefinition`, `CompiledRule`, `CompiledProfile`, `DoctrineCompiler.compile()`.

- [ ] Test activation/non-activation, conflicts, supersession, missing facts/sources, dependency cycles, unreachable rules, illegal confidence, prohibited safety, deterministic hashes, and overlay isolation.
- [ ] Verify RED; implement typed DSL and topological compiler with canonical ordering.
- [ ] Verify GREEN with `uv run pytest tests/doctrine/test_lea_519_dsl.py -q` and A1-A3 tests.

### Task 5: LEA-520 immutable analysis graph

**Files:** `src/jyotish_agent/doctrine/graph.py`, `tests/doctrine/test_lea_520_graph.py`.

**Consumes:** signed fact projection, `CompiledProfile`. **Produces:** frozen `AnalysisGraph`, `DoctrineEvaluator.evaluate()`.

- [ ] Test stable graph identity, absent/stale facts, explicit conflicts/schools, append-free values, ordering/duplication/substitution metamorphics, bounded payload, and concurrent reads.
- [ ] Verify RED; implement pure premise evaluation and provenance-complete nodes/edges.
- [ ] Verify GREEN with `uv run pytest tests/doctrine/test_lea_520_graph.py -q` and A1-A4 tests.

### Task 6: LEA-521 constrained renderer and claim firewall

**Files:** `src/jyotish_agent/doctrine/renderer.py`, `tests/doctrine/test_lea_521_renderer.py`.

**Consumes:** `AnalysisGraph`. **Produces:** `StructuredClaim`, `ClaimFirewall`, `render_report()`, `render_with_repairs()`.

- [ ] Test unsupported prose, school mixing, confidence inflation, forged refs, prohibited topics, injection fragments, source substitution, private paths/tokens, two-repair limit, RU/EN parity, and evidence appendix opt-in.
- [ ] Verify RED; implement structured validation, deterministic baseline renderer, bounded repair protocol, and privacy projection.
- [ ] Verify GREEN with `uv run pytest tests/doctrine/test_lea_521_renderer.py -q` and A1-A5 tests.

### Task 7: LEA-522 admission/evaluation dashboard

**Files:** `src/jyotish_agent/doctrine/evaluation.py`, `tests/doctrine/test_lea_522_evaluation.py`, `scripts/run_doctrine_eval.py`, `docs/evidence/doctrine/shared-platform.json`.

**Consumes:** immutable profile/source/graph/report identities and gate observations. **Produces:** `AdmissionReport`, JSON audit, Markdown dashboard.

- [ ] Test automated promotion, missing-evidence failure, reviewer rejection for new graphs, partial review, historical identity retention, honest metrics, and deterministic JSON/Markdown.
- [ ] Verify RED; implement state transitions, required gate catalog, metric aggregation, CLI writer, and privacy-safe dashboard.
- [ ] Verify GREEN and run all `tests/doctrine/test_lea_51*.py tests/doctrine/test_lea_52*.py`.

## Release B — Full Jaimini

### Task 8: LEA-523 Jaimini corpus verification

**Files:** `src/jyotish_agent/data/doctrine/jaimini-sources.json`, `src/jyotish_agent/doctrine/jaimini_pack.py`, `tests/doctrine/test_lea_523_jaimini_sources.py`, `docs/evidence/doctrine/jaimini-corpus-coverage.json`.

- [ ] Test required baseline/overlay/worked-case roles, verified hashes when files exist, page offsets, missing/low-quality inventory, copyright locality, and topic coverage.
- [ ] Verify RED; implement coverage calculation over A1 reports without fabricating missing books.
- [ ] Verify GREEN; acquisition remains incomplete until every required real file verifies.

### Task 9: LEA-524 Jaimini rule inventory

**Files:** `src/jyotish_agent/data/doctrine/jaimini-rules.json`, `tests/doctrine/test_lea_524_jaimini_inventory.py`, `docs/evidence/doctrine/jaimini-rule-discrepancies.json`.

- [ ] Test page/sutra/hash anchors, baseline purity, explicit ambiguity, coverage of every existing Jaimini fact family, and spot-check discrepancy reporting.
- [ ] Verify RED; add only source-admitted atomic candidates and keep unsupported candidates quarantined.
- [ ] Verify GREEN against the DSL compiler and evidence store.

### Task 10: LEA-525 Jaimini self/dharma/education/capability

**Files:** `src/jyotish_agent/doctrine/jaimini_pack.py`, `tests/doctrine/test_lea_525_jaimini_self.py`.

- [ ] Test AK/karakamsa/svamsa, arudha/special-lagna, topic signal classes, conflicts, approximate-time suppression, safety exclusions, and metamorphic substitutions.
- [ ] Verify RED; implement graph orchestration using compiled rules only; verify GREEN.

### Task 11: LEA-526 Jaimini career/status/activity

**Files:** `src/jyotish_agent/doctrine/jaimini_pack.py`, `tests/doctrine/test_lea_526_jaimini_career.py`, `tests/fixtures/doctrine/jaimini-career-ru.json`, `tests/fixtures/doctrine/jaimini-career-en.json`.

- [ ] Test AmK/arudha/argala/drishti graph, structural-versus-timing separation, explicit Jaimini/Parashari provenance, conflict summary, substitution failure, and RU/EN firewall goldens.
- [ ] Verify RED; implement the safe career pack; verify GREEN.

### Task 12: LEA-527 Jaimini relationships/family/legacy

**Files:** `src/jyotish_agent/doctrine/jaimini_pack.py`, `tests/doctrine/test_lea_527_jaimini_relationships.py`.

- [ ] Test DK/UL/pada/argala/drishti factors, symbolic bounded wording, fertility/marriage/longevity blocks, overlay separation, approximate-time instability, and supporting/conflicting/unavailable fixtures.
- [ ] Verify RED; implement compiled topic pack and firewall rules; verify GREEN.

### Task 13: LEA-528 source-bound Chara Dasha timing

**Files:** `src/jyotish_agent/doctrine/jaimini_pack.py`, `tests/doctrine/test_lea_528_chara_dasha_timing.py`.

- [ ] Test natal-topic gate, fact/rule/source lineage, bounded windows, no guaranteed dates, boundary stability labels, past/held-out periods, and payload ceilings.
- [ ] Verify RED; implement period-to-topic graph linkage over existing calculated periods; verify GREEN.

### Task 14: LEA-529 named Jaimini overlays

**Files:** `src/jyotish_agent/data/doctrine/jaimini-overlays.json`, `src/jyotish_agent/doctrine/jaimini_pack.py`, `tests/doctrine/test_lea_529_jaimini_overlays.py`.

- [ ] Test explicit activation, baseline immutability, deterministic side-by-side reports, source/school conflicts, and hidden-blending adversarial detection.
- [ ] Verify RED; implement overlay compilation and comparison; verify GREEN.

### Task 15: LEA-530 Full Jaimini release

**Files:** `src/jyotish_agent/mcp_models.py`, `src/jyotish_agent/mcp_facade.py`, `src/jyotish_agent/mcp_server.py`, `.pi/extensions/jyotish.ts`, `tests/doctrine/test_lea_530_jaimini_release.py`, `docs/evidence/doctrine/jaimini-release.json`.

- [ ] Test quick/full/deep/inspection RU/EN E2E, claim firewall, adversarial/metamorphic/held-out suites, privacy, payload, performance, missing-review disclosure, and audit honesty.
- [ ] Verify RED; add the smallest additive `experimental_full` Jaimini surface and release audit wiring.
- [ ] Verify GREEN; run the whole Python/TS suite and only promote if every automated gate is present and passing.

## Release C — Full Prashna

### Task 16: LEA-531 Prashna corpus verification

**Files:** `src/jyotish_agent/data/doctrine/prashna-sources.json`, `src/jyotish_agent/doctrine/prashna_pack.py`, `tests/doctrine/test_lea_531_prashna_sources.py`, `docs/evidence/doctrine/prashna-corpus-coverage.json`.

- [ ] Test required work/overlay/case roles, verified hashes, question/case metadata, copyright locality, unsupported classes, and missing doctrine report.
- [ ] Verify RED; implement A1 coverage adapter; verify GREEN without fabricating missing sources.

### Task 17: LEA-532 radicality/readability

**Files:** `src/jyotish_agent/data/doctrine/prashna-rules.json`, `src/jyotish_agent/doctrine/prashna_pack.py`, `tests/doctrine/test_lea_532_prashna_radicality.py`.

- [ ] Test source linkage, readable/conflicting/unavailable outcomes, repeated/composite/stale questions, anchor integrity, confidence ceilings, baseline/overlay identity, and redacted errors.
- [ ] Verify RED; implement compiled radicality gate before any outcome path; verify GREEN.

### Task 18: LEA-533 taxonomy/significators

**Files:** `src/jyotish_agent/doctrine/prashna_pack.py`, `tests/doctrine/test_lea_533_prashna_taxonomy.py`.

- [ ] Test deterministic RU/EN variants for four safe profiles, primary/secondary significators, fact requirements, ambiguity, composite/high-stakes rejection, and substitution firewall.
- [ ] Verify RED; implement strict source-bound classifier and selectors; verify GREEN.

### Task 19: LEA-534 aspect/perfection geometry

**Files:** `src/jyotish_agent/prashna.py`, `src/jyotish_agent/prashna_models.py`, `src/jyotish_agent/doctrine/prashna_pack.py`, `tests/doctrine/test_lea_534_prashna_geometry.py`.

- [ ] Test applying/exact/separating/prohibited/unavailable, retrograde/station/boundary, replay/DST invariance, explicit baseline/Tajika profiles, hand-check fixtures, and property cases.
- [ ] Verify RED; extend the deterministic geometry surface and bind it into doctrine facts; verify GREEN.

### Task 20: LEA-535 outcome/timing graph

**Files:** `src/jyotish_agent/doctrine/prashna_pack.py`, `tests/doctrine/test_lea_535_prashna_outcome.py`.

- [ ] Test radicality/significator/geometry gates, obstacle/assistance/perfection conflicts, bounded timing, no-answer, high-stakes blocks, and declared-school published case classes.
- [ ] Verify RED; implement compiled outcome graph; verify GREEN.

### Task 21: LEA-536 anchor-safe renderer

**Files:** `src/jyotish_agent/doctrine/prashna_pack.py`, `src/jyotish_agent/mcp_facade.py`, `tests/doctrine/test_lea_536_prashna_renderer.py`.

- [ ] Test retry/clarification anchor stability, validated-graph-only claims, secret malformed inputs, evidence appendix privacy, RU/EN modes, new-question anchor, and high-stakes/composite fail-close.
- [ ] Verify RED; implement renderer/clarification adapter; verify GREEN.

### Task 22: LEA-537 Full Prashna release

**Files:** `src/jyotish_agent/mcp_models.py`, `src/jyotish_agent/mcp_server.py`, `.pi/extensions/jyotish.ts`, `tests/doctrine/test_lea_537_prashna_release.py`, `docs/evidence/doctrine/prashna-release.json`.

- [ ] Test held-outs, outcome cases, replay/privacy, school/geometry substitutions, real-shape RU/EN E2E, no-answer/material-error reporting, missing-review disclosure, and future-outcome distinction.
- [ ] Verify RED; add additive experimental-full surface and audit; verify GREEN with full suites.

## Release D — Expanded Muhurta

### Task 23: LEA-538 Muhurta corpus verification

**Files:** `src/jyotish_agent/data/doctrine/muhurta-sources.json`, `src/jyotish_agent/doctrine/muhurta_pack.py`, `tests/doctrine/test_lea_538_muhurta_sources.py`, `docs/evidence/doctrine/muhurta-corpus-coverage.json`.

- [ ] Test required baseline/commentary/overlay/worked-election roles, verified hashes, activity coverage, copyright locality, and unsupported high-stakes blocks.
- [ ] Verify RED; implement A1 coverage adapter; verify GREEN without fabricating missing sources.

### Task 24: LEA-539 activity profiles

**Files:** `src/jyotish_agent/data/doctrine/muhurta-profiles.json`, `src/jyotish_agent/doctrine/muhurta_pack.py`, `tests/doctrine/test_lea_539_muhurta_profiles.py`.

- [ ] Test deterministic RU/EN classification for six profiles, duration/input bounds, complete-or-unavailable inventory, focused-work compatibility, composite narrowing, and all listed high-stakes blocks.
- [ ] Verify RED; implement versioned profiles and router; verify GREEN.

### Task 25: LEA-540 hard/soft rule packs

**Files:** `src/jyotish_agent/data/doctrine/muhurta-rules.json`, `src/jyotish_agent/doctrine/muhurta_pack.py`, `tests/doctrine/test_lea_540_muhurta_rules.py`.

- [ ] Test hard eligibility versus soft preference, applicability, exceptions/conflicts, source/fact traces, half-open DST-safe intervals, worked candidate, and no-window cases.
- [ ] Verify RED; compile rules over existing boundary facts; verify GREEN.

### Task 26: LEA-541 natal personalization

**Files:** `src/jyotish_agent/doctrine/muhurta_pack.py`, `tests/doctrine/test_lea_541_muhurta_personalization.py`.

- [ ] Test generic search, tara/candra bala hand checks, no natal logging/projection, approximate instability, explicit personalization status, and inability to override hard prohibitions.
- [ ] Verify RED; implement optional signed-profile personalization; verify GREEN.

### Task 27: LEA-542 explainable ranking

**Files:** `src/jyotish_agent/doctrine/muhurta_pack.py`, `tests/doctrine/test_lea_542_muhurta_ranking.py`.

- [ ] Test ineligible exclusion, source/rule/fact score components, deterministic equal-score order, separate preference/personalization, Pareto trade-offs, near misses, constraints, and non-certain prose.
- [ ] Verify RED; implement versioned scoring and stable ranking; verify GREEN.

### Task 28: LEA-543 overlays/calendar-ready reports

**Files:** `src/jyotish_agent/data/doctrine/muhurta-overlays.json`, `src/jyotish_agent/doctrine/muhurta_pack.py`, `src/jyotish_agent/mcp_facade.py`, `tests/doctrine/test_lea_543_muhurta_reports.py`.

- [ ] Test explicit overlay identity, baseline immutability, comparisons, top/alternate/near-miss output, fold/UTC inspection, DST calendar round-trip, hidden IDs/place labels, RU/EN firewall, and zero side effects.
- [ ] Verify RED; implement comparison and report adapter; verify GREEN.

### Task 29: LEA-544 Expanded Muhurta/project release

**Files:** `src/jyotish_agent/mcp_models.py`, `src/jyotish_agent/mcp_server.py`, `.pi/extensions/jyotish.ts`, `tests/doctrine/test_lea_544_project_release.py`, `docs/evidence/doctrine/muhurta-release.json`, `docs/evidence/doctrine/project-release.json`.

- [ ] Test worked elections, DST/skipped-date/constraints/ranking/personalization held-outs, school/score adversarial cases, RU/EN E2E, privacy/payload/performance, high-stakes blocks, domain metrics, and honest external-review/concierge status.
- [ ] Verify RED; add final additive surface and aggregate audit; verify GREEN.
- [ ] Run `uv run pytest -q`, `bun run typecheck`, `bun test`, `git diff --check`, doctrine release CLI, adversarial eval, and a clean-worktree package scan proving no private/copyrighted source entered Git.
- [ ] Perform independent code/requirements review, fix every critical/important finding, rerun the full gate, then update all Linear issues and project status strictly from recorded evidence.

## Plan self-review

- Spec coverage: every Linear issue `LEA-516` through `LEA-544` maps to one task and each acceptance family has a named test/gate.
- Placeholder scan: no deferred code placeholders or fabricated evidence are permitted; real source/reviewer/concierge inputs remain explicit evidence gates.
- Type consistency: the dependency chain is `SourceRecord -> IngestionArtifact -> SourceFragment -> CompiledProfile -> AnalysisGraph -> StructuredClaim -> AdmissionReport`; all domain packs consume this chain and existing signed fact projections.
