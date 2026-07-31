# Jaimini Overlay Source Fragments — Implementation Plan

**Goal:** Bind the acquired Sanjay Rath source to privacy-safe, exact page-level evidence without admitting doctrine, activating an overlay, changing the frozen production profile, or tracking copyrighted text.

## Scope

- Add a typed overlay-fragment ledger separate from the immutable `nilakantha_baseline` inventory.
- Record only source identity, page/printed-page coordinates, source/page/fragment hashes, non-quoting paraphrases, rule-family bindings, review state, and discrepancy state.
- Initial source: `jaimini_sanjay_rath_upadesa_sutras_1997` only.
- Initial rule families: rasi drishti, argala, chara karakas, arudha, svamsa/karakamsa, co-lords, and Chara Dasha progression/duration.
- Mark every fragment as quarantined in the evidence layer.
- Mark rules that materially diverge from `jaimini_core_v1` as `quarantined_conflict`; other bindings remain `anchored_unreviewed`.
- Keep `doctrine_admitted=false`, `product_rule_use_allowed=false`, and overlay activation unavailable.

## Explicit non-goals

- No Nilakantha baseline admission.
- No specialist-review claim.
- No production rule compilation or change to `jaimini_core_v1`.
- No full text, excerpts, PDF filenames, private paths, or source bytes in tracked files.
- No Narayana Dasa fragment admission: the normalized one-page PDF retains duplicated two-up embedded text and needs a crop-aware extraction fix.
- No K.N. Rao fragment admission: OCR review remains pending.

## Task 1 — Typed ledger and integrity validation

**Files:** `src/jyotish_agent/doctrine/jaimini_pack.py`, focused tests.

1. Add immutable models for overlay fragment bindings and a ledger.
2. Reuse inspection-safe `SourceFragment` identities from the evidence layer.
3. Bind the ledger to the active source manifest hash and baseline inventory hash.
4. Validate unique fragment and binding identities, overlay/source/school coherence, known baseline rule IDs, source-manifest membership, and unavailable overlay state.
5. Make activation impossible while any entry is unreviewed/conflicted or product use is false.

## Task 2 — Private extraction and tracked evidence projection

**Files:** `src/jyotish_agent/data/doctrine/jaimini-overlay-fragments.json`, `docs/evidence/doctrine/jaimini-overlay-fragments.json`, focused tests.

1. Extract exact born-digital pages through the deterministic `doctrine-text-v1` normalization path.
2. Build quarantined `SourceFragment` identities with `excerpt_permission=none` and no text.
3. Add concise English paraphrases that do not reproduce source wording.
4. Record Chara Dasha/co-lord divergence from the frozen simplified profile as conflicts.
5. Add a privacy-safe audit projection with counts, hashes, unresolved sources, and release effect.

## Task 3 — Gates, audits, and documentation

**Files:** overlay tests, release audits, `TODOS.md` as appropriate.

1. Prove no tracked source text/private path/PDF filename is present.
2. Prove the baseline inventory and frozen production profile are unchanged.
3. Prove conflict bindings cannot activate or compile an overlay.
4. Optionally verify page hashes against private files when present; skip honestly when absent.
5. Keep Jaimini release unavailable and preserve the Subodhini/specialist/deep-E2E/hand-worked blockers.
6. Run focused tests, full Python suite, Ruff, Bun tests, TypeScript, and tracked-private-source checks.

## Acceptance

- The source-fragment ledger is deterministic and hash-bound.
- Tracked files contain no copyrighted source text or private source paths.
- Sanjay Rath evidence is isolated from `nilakantha_baseline` and from `project-canonical-jaimini-v1`.
- No entry is admitted and no overlay becomes available.
- Chara Dasha differences are explicit conflicts.
- Narayana Dasa and K.N. Rao remain explicitly unresolved, not silently treated as reviewed.
- Fresh verification evidence is recorded without changing overall Release B availability.
