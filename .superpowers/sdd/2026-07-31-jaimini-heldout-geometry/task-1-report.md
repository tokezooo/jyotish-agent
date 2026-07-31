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
