# LEA-530 Task 1 report — held-out Jaimini geometry

## Status

DONE_WITH_CONCERNS

## Changed files

- `eval/jaimini/geometry-held-out-v1.json` — hand-authored, public-safe 26-case scalar/sign corpus.
- `eval/jaimini/geometry-held-out-v1-checksums.json` — SHA-256 manifest.
- `src/jyotish_agent/jaimini_evaluation.py` — explicit held-out opt-in, checksum/profile/school/privacy validation, family dispatch, exact result report.
- `tests/test_jaimini_geometry_heldout.py` — real-boundary corpus and independent mutation coverage.
- `src/jyotish_agent/data/doctrine/jaimini-release.json` and `docs/evidence/doctrine/jaimini-release.json` — only `held_out_cases` is passed.
- `docs/evidence/doctrine/project-release.json` — regenerated with `build_project_release_audit`.
- `tests/doctrine/test_lea_530_jaimini_release.py` and `TODOS.md` — release evidence contract and obsolete blocker removal.

## TDD evidence

RED command:

```text
PYTHONPATH=src /usr/local/bin/python3 -m pytest -q tests/test_jaimini_geometry_heldout.py
```

RED output: collection failed with `ModuleNotFoundError: No module named 'jyotish_agent.jaimini_evaluation'`.

GREEN commands/results:

```text
PYTHONPATH=.venv/lib/python3.12/site-packages:src:tests/doctrine /Users/vlad/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest -q tests/test_jaimini_geometry_heldout.py
11 passed

... -m pytest -q tests/test_jaimini_geometry_heldout.py tests/test_jaimini_core.py tests/doctrine/test_lea_530_jaimini_release.py tests/doctrine/test_project_release_audit.py
40 passed
```

Mutation coverage separately rejects checksum drift, expected-oracle drift, missing/wrong school identity, profile ID/SHA mismatch, duplicate IDs, tuning misuse, and private/non-synthetic payloads. It also proves dispatch is based on `rule_family`, not case ID.

## Full verification

- `bun run typecheck`: passed.
- `bun test`: 58 passed, 0 failed.
- `git diff --check`: passed.
- `git ls-files | rg '(^|/)private_sources(/|$)'`: no tracked private sources.
- Full Python suite with the supplied Codex runtime: 803 passed, 2 skipped, 2 failed. Both failures are pre-existing wheel-package tests (`tests/test_muhurta_package.py` and `tests/test_task1_jaimini_contracts.py`) because their subprocess invokes `uv`, which is absent from PATH (`FileNotFoundError: uv`). The focused and affected suites above passed.
- Ruff could not run in the supplied runtime because it has no `ruff` module; the repository venv also has a broken interpreter link to the removed Anaconda Python.

## Evidence decisions

The corpus asserts only deterministic geometry through production functions, declares `authorship=hand_authored_not_generated`, `used_for_tuning=false`, and `public_safe=true`, and is SHA-256/profile-hash/school-bound. It neither claims source admission nor evaluates interpretation. The release continues to block on compiled source-admitted profile, Nilakantha Subodhini translation, source/specialist review, hand-worked cases, and deep conversational E2E.

The plan's `(house,lord)=(5,8)->11` Arudha expectation was corrected by the task owner before green: the frozen same/seventh-to-tenth contract projects it to 11 and returns final pada 2. Production geometry and the existing core fixture were not changed.

## Self-review

Reviewed schema strictness, case-ID independence, exact canonical comparisons, opt-in enforcement, release blocker preservation, generated project-audit identity, and tracked-private-source exclusion. No PDF or `private_sources` content was touched. The pre-existing untracked `tmp/` and plan document were preserved.

## Commits

- `3ec818c` — `feat(jaimini): add LEA-530 held-out geometry gate`

## Concerns

Full suite and Ruff require a working `uv`/lint runtime; the only full-suite failures were the two wheel tests that cannot find `uv`.

## Fix round 1 — per-case identity and strict synthetic schema

Addressed the two blocking review findings in commit `3a712ec`.

- Every one of the 26 hand-authored cases now carries and must match its own
  `school`, `rule_profile_id`, and `rule_profile_sha256`. Validation occurs for
  the complete corpus before any observer is dispatched.
- Replaced the text blacklist with family-specific exact schemas. Case IDs,
  school/profile fields, field keys, scalar ranges, body/status enums, output
  shapes, booleans, and UTC timestamp forms are all whitelisted. Arbitrary
  prose, birth-profile-shaped objects, private/copyright strings, and extra
  keys are rejected before execution or reporting.
- Recomputed `geometry-held-out-v1.json` SHA-256 after adding the case-local
  identity fields: `476f25c3ec4c3df1d56fe5a99bbe7d7ed2a422b6f1ee2b47d46dd9f3353794c0`.

Fix-round RED command/result:

```text
PYTHONPATH=.venv/lib/python3.12/site-packages:src:tests/doctrine /Users/vlad/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest -q tests/test_jaimini_geometry_heldout.py
8 failed, 12 passed
```

The failures demonstrated that missing/wrong case identity was accepted or
reported only as a generic schema issue, and that prose-shaped expected values
could reach the observer.

Fix-round GREEN verification:

```text
tests/test_jaimini_geometry_heldout.py: 27 passed
tests/test_jaimini_geometry_heldout.py tests/test_jaimini_core.py tests/doctrine/test_lea_530_jaimini_release.py tests/doctrine/test_project_release_audit.py: 55 passed
git diff --check: passed
```

Release blockers remain unchanged; this round does not claim source admission,
human worked cases, specialist review, or deep E2E completion.

## Final whole-branch fix wave — semantic validity and fresh audit evidence

Addressed the final whole-branch findings in commit `9d6671b`.

- Co-lord duration values are now bounded to the frozen sign-distance range
  `[0, 12)`; degrees remain `[0, 30)`.
- Special-lagna elapsed minutes are bounded to a civil day `[0, 1440)`.
- Chara start/end strings must parse as real UTC datetimes, not merely match a
  timestamp-shaped regex. Chara sign and duration-list bounds remain validated.
- Validation converts unexpected schema/type/range errors to
  `HeldOutCorpusError` before any observer dispatches.
- Every failed oracle report now includes `case_id` as well as rule family,
  expected, and observed values.
- `docs/evidence/doctrine/project-release.json` no longer records stale
  verification claims. Its audit SHA was regenerated with
  `build_project_release_audit` after the fresh results below.
- Added the durable execution plan at
  `docs/superpowers/plans/2026-07-31-jaimini-heldout-geometry.md`.

Final RED command/result:

```text
PYTHONPATH=.venv/lib/python3.12/site-packages:src:tests/doctrine /Users/vlad/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest -q tests/test_jaimini_geometry_heldout.py
6 failed, 28 passed
```

The failures showed missing `case_id` in failure reports plus negative duration,
negative/out-of-day elapsed time, and impossible UTC calendar/time strings
reaching observers.

Final verification:

```text
PATH=/tmp/jyotish-uv:$PATH PYTHONPATH=.venv/lib/python3.12/site-packages:src:tests/doctrine /Users/vlad/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest -q
829 passed, 2 skipped

UV_CACHE_DIR=/tmp/jyotish-uv-cache /tmp/jyotish-uv/uvx --from ruff==0.12.7 ruff check src tests
All checks passed

bun run typecheck
passed

bun test
58 passed, 0 failed

... -m pytest -q tests/test_jaimini_geometry_heldout.py tests/test_jaimini_core.py tests/doctrine/test_lea_530_jaimini_release.py tests/doctrine/test_project_release_audit.py
62 passed

... -m pytest -q tests/doctrine/test_lea_526_jaimini_career.py tests/doctrine/test_lea_527_jaimini_relationships.py tests/doctrine/test_lea_536_prashna_renderer.py tests/doctrine/test_lea_530_jaimini_release.py tests/doctrine/test_lea_537_prashna_release.py tests/doctrine/test_lea_544_muhurta_release.py
40 passed

git diff --check
passed

git ls-files | rg '(^|/)private_sources(/|$)'
no tracked private sources
```

This supersedes the earlier toolchain concern: the temporary verifier supplied
for this final wave made the wheel tests executable. All remaining Jaimini
release blockers are source/admission, Subodhini, hand-worked, specialist-review,
and deep-E2E blockers; availability remains false.
