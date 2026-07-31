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
- `tests/doctrine/test_lea_529_jaimini_overlays.py`
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
PYTHONPATH=.venv/lib/python3.12/site-packages:src:tests/doctrine "$CODEX_PYTHON" -m pytest -q tests/doctrine/test_jaimini_overlay_fragments_20260731.py
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
PATH=/tmp/jyotish-uv:$PATH PYTHONPATH=.venv/lib/python3.12/site-packages:src:tests/doctrine "$CODEX_PYTHON" -m pytest -q
839 passed, 2 skipped in 180.17s
```

The two skips are the expected Swiss ephemeris mode skips. A preliminary run
without `/tmp/jyotish-uv` in `PATH` reached 837 passing tests but failed two
wheel/build tests with `FileNotFoundError: uv`; the final command above corrected
the test environment and passed.

`CODEX_PYTHON` denotes the bundled workspace Python 3.12 runtime used for these
commands; the tracked report intentionally avoids a machine-specific home path.

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
- `7377450 fix(jaimini): close overlay activation bypass`
- `436762e fix(jaimini): seal overlay activation evidence`

## Important review fix round

Closed every Important review finding before merge:

- The real `compare_jaimini_overlays(..., activate=True)` path now requires a
  sealed `JaiminiOverlayActivationContract`. The contract is available only
  through a strict loader that validates the ledger against the active source
  manifest, baseline inventory, and overlay registry before returning.
- Missing or duck-typed activation context fails with
  `OVERLAY_ACTIVATION_CONTEXT_REQUIRED`. The currently unavailable Sanjay Rath
  and K. N. Rao overlays fail with `OVERLAY_UNAVAILABLE`; fragment presence
  cannot activate either overlay.
- Context validation independently enforces positive page coordinates and
  `printed_page == page_number + source.page_offset`.
- Context validation now repeats the release-state, fragment source/school, and
  binding rule/status checks so unchecked `model_copy` mutations cannot bypass
  the loader boundary.
- Adversarial coverage now mutates fragment source/school, binding rule/status,
  doctrine/product flags, activation state, manifest hash, baseline hash, and
  printed-page coordinates.
- The privacy-safe audit test now derives and checks all hashes, source IDs,
  page numbers, unresolved-source projections, binding counts/status counts,
  and false release/activation flags against the validated ledger.
- The project audit records the fresh full-suite evidence (`839 passed`, two
  expected skips) and its canonical audit hash was regenerated.
- Machine-specific home paths were removed from tracked report commands;
  `CODEX_PYTHON` is the stable bundled-runtime placeholder.

Review-fix RED evidence: the focused suites initially failed collection because
the required safe loader did not exist. Final review-fix verification:

```text
focused + adjacent doctrine suites: 41 passed in 2.62s
ruff check src tests: All checks passed!
git diff --check: passed
```

### Second Important fix wave

- Changed active-path validation from `isinstance` to exact type identity.
- Made `JaiminiOverlayActivationContract` non-subclassable and retained its
  immutable surface.
- Bound each validated contract to the loader-only token plus a deterministic
  ledger/registry state hash. Every readiness check recomputes the state and
  fails typed with `OVERLAY_ACTIVATION_CONTEXT_INVALID` for uninitialized,
  forged, or stale exact-type instances.
- Added adversarial coverage for rejected subclass definition,
  `object.__new__` construction, and post-load validation-state substitution.
- Bound the privacy-safe fragment audit to the tracked Jaimini release evidence
  SHA, release ID, and admission state.
- Replaced literal blocker assertions with the exact projection of missing gate
  names and blocker codes from the tracked release audit. Promotion now equals
  the tracked release `available` flag and remains false.

Second-wave verification:

```text
focused + adjacent doctrine suites: 42 passed in 2.57s
ruff check src tests: All checks passed!
git diff --check: passed
```

## Final HEAD verification

After both independent review fix waves, the complete Python suite was rerun
on the final implementation head:

```text
PATH=/tmp/jyotish-uv:$PATH PYTHONPATH=.venv/lib/python3.12/site-packages:src:tests/doctrine "$CODEX_PYTHON" -m pytest -q
852 passed, 2 skipped in 181.68s
```

The two skips are the expected Swiss ephemeris mode skips. The project release
audit was updated to this final count and its canonical hash regenerated.

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
