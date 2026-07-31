# Narayana Dasa Crop-Aware Fragments — Implementation Plan

**Goal:** Resolve the duplicated two-up embedded-text blocker in the normalized Narayana Dasa source and bind a bounded set of page-level evidence without admitting doctrine or activating an overlay.

## Context

The normalized source visually contains one printed page per PDF page, but each pair retains the original spread text stream. Default `pypdf.extract_text()` therefore returns duplicate full-spread text. The page content transformation and half-page `MediaBox` are sufficient to filter text chunks deterministically by their transformed origins.

## Scope

- Add a separate page-bounds-aware pypdf adapter; do not change default extraction semantics or existing Upadesa hashes.
- Use affine text-origin coordinates and the page bounds to retain only visible-page chunks.
- Prove the adapter on a generated synthetic two-up PDF and on rotated affine coordinates.
- Replay the private normalized Narayana source when present and prove adjacent halves no longer duplicate.
- Add quarantined Narayana page commitments for PDF/printed pages 46–48.
- Bind progression/start-order and antardasha evidence as explicit conflicts where it exceeds or differs from the frozen simplified core.
- Remove only the Narayana crop-aware blocker; retain K.N. Rao OCR, Subodhini, specialist, hand-worked, deep-E2E, and compiled-profile blockers.

## Non-goals

- No production rule changes or rule compilation.
- No Nilakantha baseline changes.
- No source text, excerpts, PDF filenames, private paths, or source bytes in tracked evidence.
- No claim that crop-aware extraction is specialist review.
- No K.N. Rao fragment binding in this slice.

## Task 1 — Page-bounds text adapter

**Files:** `src/jyotish_agent/doctrine/ingestion.py`, ingestion tests.

1. Add a distinct extractor with explicit tool/provenance identity.
2. Transform each visitor text origin through the current transformation matrix.
3. Include chunks whose transformed origin lies inside the page media/crop bounds; exclude off-page sibling content.
4. Fail typed if a non-empty embedded stream produces no in-bounds text, rather than silently returning blank/triggering unrelated OCR.
5. Test deterministic output, normal and rotated affine transforms, boundary behavior, corrupt/encrypted handling, and a generated two-up PDF with no tracked PDF fixture.

## Task 2 — Narayana fragment commitments

**Files:** overlay ledger/audit JSON, Jaimini pack models/tests.

1. Extend the Sanjay Rath ledger to allow its declared Upadesa and Narayana sources without allowing arbitrary overlay sources.
2. Preserve full SourceFragment identity/hash validation and context checks.
3. Add page-level commitments for 46, 47, and 48 using the new adapter and `doctrine-text-v1` normalization.
4. Bind `chara_dasha.progression` and `chara_dasha.antardasha` as `quarantined_conflict`; no binding may be admitted.
5. Remove Narayana from unresolved sources; K.N. Rao remains `ocr_review_pending`.
6. Make multi-source page projections unambiguous by including source identity with page numbers.

## Task 3 — Release honesty and verification

1. Update fragment audit and Release B blockers to state that Narayana pages are hash-bound but still unreviewed/uncompiled.
2. Recompute release/project evidence hashes and canonical audit hash.
3. Prove default Upadesa commitments and core/baseline byte identities remain unchanged.
4. Run focused/adjacent tests, full Python, Ruff, Bun, TypeScript, private-source tracking scan, and independent review.

## Acceptance

- The synthetic split PDF returns left-only then right-only text deterministically.
- Narayana pages 46–48 replay to the tracked commitments through the page-bounds adapter.
- Adjacent normalized pages have distinct text/page hashes and no duplicated full-spread output.
- All new bindings are quarantined conflicts; overlay activation remains impossible.
- Tracked evidence remains text-free and path-free.
- Release B stays unavailable with every unrelated blocker preserved.
