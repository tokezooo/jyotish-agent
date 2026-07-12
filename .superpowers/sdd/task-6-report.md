# Task 6 report

## Status and commit

- Implementation commit: `2f17702` (`feat: harden research evaluation and operations`)
- Base: `afe455e1456cce7f8a32932992987c4744e2579f`
- Branch: `codex/research-agent-v2`

## Frozen evaluation corpus

- Total fixed cases: **60**.
- Tuning: **40** in `eval/fixtures/tuning.jsonl`.
- Held-out: **exactly 20** in the physically separate
  `eval/fixtures/held-out.jsonl`; IDs are disjoint and validation fails on overlap.
- Profiles: **10** synthetic/public-safe profiles (`P01`–`P10`) in
  `eval/fixtures/profiles.json`; all case references are checked against that set.
- Covered categories: unsafe, missing input, claim/evidence failures, timezone
  boundaries, retrieval conflicts, race/restart, replay, and oracle comparison.
- The rubric scores relevance, depth, clarity, traceability, actionability,
  unsupported claims, and timings from 0–3 and records material rewrites, evidence,
  reviewer, UTC time, and pass/fail. A named `human:` reviewer is mandatory.

### Oracle provenance

There are **4** oracle-comparison fixtures: D1 (`T001`), D9 (`T013`), D10
(`T021`), and Vimshottari dasha (`T025`). No trusted independent oracle artifact was
provided, so all four use `status: placeholder`, `expected: null`, and the exact
provenance statement: “No trusted independent oracle artifact was supplied;
placeholder must not be scored.” No PyJHora/system-under-test output was copied into
an oracle field and no external value was invented. The rubric documents the
tool/version/input/checksum/URL-or-locator/timestamp/human-reviewer fields required
before a placeholder may become verified.

## Crash and privacy coverage

- Pi/backend commit windows, duplicate/idempotent operations, concurrent revision
  conflicts, and restart recovery: existing Python operation/restart tests plus all
  ResearchRuntime Bun commit/reconciliation cases.
- SQLite busy/partial state: `test_sqlite_busy_wait_is_bounded` proves the configured
  busy timeout produces a bounded lock failure; transaction/restart suites prove
  immutable retry behavior.
- Stale Pi mirrors: the temporary-HOME black-box test writes a false mirror and proves
  replay hashes still come from SQLite.
- Corrupt fragments/index: two parameterized drills corrupt fragment bytes or delete
  an FTS member; retrieval raises `CorpusIntegrityError` before returning evidence.
- Missing pinned versions and render mismatch: offline replay tests fail closed on
  version/planning/projection/event/render drift.
- Malicious source instructions: an approved authored fixture containing prompt
  injection is retrieved byte-for-byte as inert quoted data.
- Logging/redaction: request logs exclude question/profile sentinels; the hardening
  redactor returns a constant marker and structured errors omit private details.
- Path traversal and symlinks: private writes reject `..`, intermediate symlinks, and
  a symlink used as the private root.
- Permissions and atomic artifacts: runtime directories are `0700`, artifacts are
  `0600`, writes use same-directory fsync + atomic replace, and no temp remains.
- Retention/deletion: deletion removes the private tree without following an external
  symlink and preserves the external target.
- Structured errors expose `error_code`, `run_id`, `stage`, `retryable`, `problem`,
  `cause`, and `fix`; stable registry definitions cover busy, corruption, missing
  pinned versions, render mismatch, and unexpected internal errors.

## Documentation and operator skill

- README golden path: doctor → ask → inspect → replay.
- Focused docs: state/run model, AnswerContract v2, corpus governance,
  debugging/error codes, and migration/backup/recovery.
- `.pi/skills/jyotish-eval-reviewer` was created with the required `init_skill.py`,
  includes generated `agents/openai.yaml`, keeps held-out evaluation gated, records
  human adjudication, and explicitly forbids model-only judging and invented oracles.

## Commands and results

- `uv run pytest tests/test_task6_hardening.py -q` → **13 passed in 0.37s**.
- `uv run pytest -q` → **326 passed, 2 skipped in 90.20s**. Both skips are the
  Swiss-ephemeris-only golden/parity cases; the installed Moshier path passed.
- `bun test` → **44 passed, 0 failed, 137 assertions**.
- `bun run typecheck` → **passed** (`tsc --noEmit`).
- `uv run python -m compileall -q src scripts tests` → **passed**.
- `quick_validate.py .pi/skills/jyotish-eval-reviewer` → **Skill is valid**.
- `quick_validate.py .pi/skills/jyotish-corpus-curator` → **Skill is valid**.
- `git diff --check` → **passed**.
- Temporary-HOME black-box doctor → ask with validated fake Pi → inspect JSON →
  stale-mirror replay → memo SHA-256 comparison → shutdown → **passed** (the focused
  black-box invocation passed in 2.88s together with Task 6 tests; it is also in the
  full Python suite).

## External/live limitations and concerns

- `pi` is installed, but `GEMINI_API_KEY` was absent. Per the brief, no live
  Pi/Gemini call was attempted and external authentication did not block completion.
- Swiss ephemeris files are not installed; two explicitly Swiss-only tests remain
  skipped while the default Moshier suite passes.
- The 60 fixtures are frozen evaluation specifications. This implementation validates
  their shape/separation and automates deterministic crash/privacy mechanisms, but it
  does not fabricate human adjudication records. A declared human review run remains
  necessary to score tuning or held-out answer quality.
