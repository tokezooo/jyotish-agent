# Task 1 report — Narayana crop-aware fragments

## Outcome

- Added `PageBoundsPyPdfExtractor` as a separate, explicitly identified pypdf adapter. The default `PyPdfExtractor` implementation and existing Upadesa commitments remain unchanged.
- Added deterministic visible-bounds filtering using the full affine text origin, CropBox/MediaBox intersection, and half-open upper boundaries.
- Added typed failure `PDF_TEXT_OUT_OF_BOUNDS` when a non-empty embedded stream has no visible text; corrupt, encrypted, blank/OCR fallback, and invalid-bounds behavior remain fail-closed.
- Added generated-temp synthetic two-up, affine rotation, boundary, deterministic, corrupt, encrypted, and blank-page tests. No PDF fixture is tracked.
- Hash-bound Narayana pages 46–48 to three text-free, quarantined SourceFragments through `doctrine-text-v1` normalization and the crop-aware adapter.
- Added one `chara_dasha.progression` and two `chara_dasha.antardasha` bindings, all `quarantined_conflict` with explicit discrepancies from the frozen simplified core.
- Removed only the Narayana crop-aware unresolved-source entry. K. N. Rao remains `ocr_review_pending`; overlay activation, baseline inventory, frozen core, and release availability remain unchanged.
- Replaced ambiguous page-number-only audit projection with source-qualified page coordinates.

## TDD evidence

### RED — page-bounds adapter

Command:

`python -m pytest -q tests/doctrine/test_page_bounds_pypdf_extractor.py`

Result before implementation: collection failed because `PageBoundsPyPdfExtractor` and its coordinate helpers did not exist.

### RED — Narayana ledger/audit

Command:

`python -m pytest -q tests/doctrine/test_jaimini_overlay_fragments_20260731.py`

Result before ledger changes: `6 failed, 16 passed`. Failures identified the absent Narayana source fragments, absent antardasha bindings, stale unresolved-source entry, and stale source-qualified audit projection.

### Focused GREEN

- Adapter plus adjacent ingestion: `17 passed`.
- Crop-aware fragments plus Jaimini overlay/release/project adjacency: `55 passed`.
- Final audit replay after verification-count synchronization: `23 passed`.
- Focused Ruff checks: passed.

## Full verification

- Python: `863 passed, 2 skipped in 188.45s`; both skips are the expected missing Swiss-ephemeris golden checks.
- Ruff: `UV_CACHE_DIR=/tmp/jyotish-uv-cache /tmp/jyotish-uv/uvx --from ruff==0.12.7 ruff check src tests` — passed.
- Bun: `58 pass, 0 fail`.
- TypeScript: `bun run typecheck` / `tsc --noEmit` — passed.
- Private-source tracking scan: `git ls-files private_sources '*.pdf'` returned no tracked files.
- Release/project audit replay: passed; canonical project audit SHA-256 is `700f65194d4e2c8c040a1390723077f45afab0eef85f8c05cc84e9295d88e843`.

## Commits

- `c3365d1 feat(doctrine): add crop-aware PDF extraction`
- `8d24966 feat(jaimini): bind Narayana crop-aware fragments`
- `aa7641e docs(doctrine): record Narayana verification`

## Remaining blockers

- No source-admitted compiled Jaimini profile exists.
- The licensed Nilakantha Subodhini English translation is still missing.
- Upadesa and Narayana fragments remain quarantined, unreviewed, and uncompiled; production specialist review and overlay rule compilation are still missing.
- K. N. Rao page-level OCR review remains unresolved.
- Hand-worked and deep conversational E2E gates remain missing.
- `full_jaimini_v1` remains `blocked_sources`, `available=false`; neither overlay activation nor product rule use is allowed.
