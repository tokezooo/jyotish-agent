# Task 1 report — Jaimini overlay source fragments

## Outcome

Implemented the bounded source-fragment slice for the Sanjay Rath practical
overlay. Ten born-digital Upadesa pages now have deterministic, text-free
`SourceFragment` identities and twelve rule-family bindings. All evidence stays
quarantined: nine bindings are `anchored_unreviewed`, and the co-lord, Chara
Dasha progression, and Chara Dasha duration bindings are explicit
`quarantined_conflict` entries.

No Nilakantha baseline rule, frozen production profile, source bytes, excerpt,
private path, or source filename was changed or tracked.

## Files changed

- `src/jyotish_agent/doctrine/jaimini_pack.py`
- `src/jyotish_agent/data/doctrine/jaimini-overlay-fragments.json`
- `docs/evidence/doctrine/jaimini-overlay-fragments.json`
- `tests/doctrine/test_jaimini_overlay_fragments_20260731.py`
- `src/jyotish_agent/data/doctrine/jaimini-release.json`
- `docs/evidence/doctrine/jaimini-release.json`
- `docs/evidence/doctrine/project-release.json`
- `TODOS.md`
- `.superpowers/sdd/2026-07-31-jaimini-source-fragments/task-1-report.md`

## Design

- Added immutable models for overlay fragment bindings, unresolved overlay
  sources, and the overlay fragment ledger.
- Reused the evidence layer's inspection-safe `SourceFragment` and `FragmentRef`
  identities instead of introducing a second fragment protocol.
- Bound the ledger to the active source-manifest hash and immutable baseline
  inventory hash.
- Recomputed and validated each fragment draft hash, stable fragment ID,
  revision hash, and binding ID at load time.
- Validated source-manifest membership, overlay role, named overlay membership,
  school coherence, known baseline rule IDs, unavailable overlay state, unique
  identities, and current fragment references.
- Made activation structurally unavailable with literal false product/admission
  flags and a typed `OVERLAY_FRAGMENT_LEDGER_QUARANTINED` failure.
- Used whole normalized page commitments from the repository
  `doctrine-text-v1` path. The tracked projection stores hashes and coordinates,
  but no source text or excerpts.
- Kept Narayana Dasa out of fragment evidence pending crop-aware extraction and
  kept the K. N. Rao source out pending page-level OCR review.

## RED evidence

Command:

```text
PYTHONPATH=.venv/lib/python3.12/site-packages:src:tests/doctrine /Users/vlad/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest -q tests/doctrine/test_jaimini_overlay_fragments_20260731.py
```

Initial result: collection failed because
`JaiminiOverlayFragmentLedger` did not exist. This established the expected RED
state before the schema and ledger were implemented.

## Focused GREEN evidence

Initial focused ledger suite after implementation:

```text
8 passed in 2.22s
```

Final focused plus adjacent release/inventory/overlay/project-audit suite:

```text
29 passed in 2.59s
```

Covered:

- manifest/inventory/overlay context validation;
- whole-page hash verification against private bytes when present;
- fragment and binding substitution rejection;
- explicit conflict states;
- unavailable activation;
- privacy-safe tracked projection;
- unresolved Narayana/K. N. Rao blockers;
- immutable baseline/core byte identities;
- honest release and generated project audits.

## Broader verification

Full Python suite, using the repository's proven bundled runtime and `uv` path:

```text
PATH=/tmp/jyotish-uv:$PATH PYTHONPATH=.venv/lib/python3.12/site-packages:src:tests/doctrine /Users/vlad/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest -q
839 passed, 2 skipped in 180.17s
```

The two skips are the expected Swiss ephemeris mode skips. A preliminary run
without `/tmp/jyotish-uv` in `PATH` reached 837 passing tests but failed two
wheel/build tests with `FileNotFoundError: uv`; the final command above corrected
the test environment and passed.

Additional checks:

```text
UV_CACHE_DIR=/tmp/jyotish-uv-cache /tmp/jyotish-uv/uvx --from ruff==0.12.7 ruff check src tests
All checks passed!

bun test
58 pass, 0 fail

bun run typecheck
tsc --noEmit (passed)

git ls-files private_sources | wc -l
0

git diff --check
passed
```

## Commits

- `c690d1c feat(jaimini): add quarantined source fragment ledger`
- `8696a30 fix(jaimini): harden fragment quarantine gates`

## Remaining concerns and blockers

- The licensed Nilakantha Subodhini translation is still missing.
- No source fragment or rule is specialist-reviewed or doctrinally admitted.
- Chara Dasha/co-lord evidence conflicts with the frozen simplified core and
  must not be compiled or activated without adjudication.
- Narayana Dasa still needs crop-aware text-layer extraction review.
- The K. N. Rao scan still needs page-level OCR review.
- Hand-worked and deep conversational release gates remain missing.
- The production compiled profile remains absent; Release B stays
  `blocked_sources` and unavailable.
- User-owned untracked `tmp/` was preserved unchanged.
