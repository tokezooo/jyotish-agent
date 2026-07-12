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

## Review remediation (2026-07-12)

The Task 6 review findings were closed in a follow-up commit based on `1605267`:

- The public registry now uses the runtime's exact `MISSING_PINNED_VERSION` and
  `MEMO_HASH_MISMATCH` names. API handlers map bounded SQLite busy/locked failures
  and `CorpusIntegrityError` to stable registry envelopes. Causes come only from
  controlled registry text; exception messages are never exposed.
- Schema v8 stores per-run availability records for all pinned engine, model,
  planner, corpus, and contract versions. Removing the pinned corpus availability
  reaches the real replay error. A separately coordinated memo-byte/hash mutation
  reaches the real memo mismatch. Both branches are exercised through service/API
  tests and the subprocess CLI replay path.
- Physically separate `tuning-specs.json` / `held-out-specs.json` and checksum
  manifests map all 60 IDs to reviewed specifications: 28 exact automated
  production setups and 32 honest `manual_not_scored` cases. Every automated probe
  consumes its exact profile, prompt, and expected outcome; a
  mutation regression proves the exact case fails. Tuning succeeds even when all
  held-out case/spec/manifest files are physically absent.
- The eval skill now invokes `python -m jyotish_agent.evaluation tuning`; held-out
  uses the separate `--allow-held-out` command. Both runner modes completed.
- Validated CLI memos are atomically written to the actual private artifact path
  `artifacts/<rr_id>/answer.md` with `0700` directories and `0600` files. A bounded
  seven-day default retention sweep runs after ask, with an explicit
  `jyotish artifacts prune --retention-seconds ...` operator entrypoint.
- The malicious-source regression now crosses create → screen → plan → corpus
  retrieval → structured `quoted_source_data` → fake-Pi rendering with
  tool/model/subprocess canaries and proves no source-derived side effect.
  A Bun harness also imports and registers the real TypeScript extension, invokes
  its registered retrieval tool on the adversarial typed envelope, and verifies the
  injected tool/model/process canaries remain untouched.
- Retention rejects a symlinked artifact root before `exists`/`iterdir`, anchors the
  resolved root under `data_root`, and unlinks nested symlinks without following
  them. The exact external-victim deletion reproduction is now a regression test.
- The configured SQLite/artifact root is also rejected when it is a symlink, every
  managed directory ancestor is forced to `0700`, and operator erasure requires an
  integrity-checked whole-store backup plus explicit confirmation. Append-only ledger
  retention is documented as intentionally indefinite.
- Offline dependency availability now recalculates checksums for engine, planner,
  contract, and approved-corpus manifest material; the non-executed model label is no
  longer treated as a replay dependency.
- The temporary-HOME smoke now uses exactly one data root and one server lifecycle
  in doctor → validated fake-Pi ask → inspect JSON → offline replay/hash → shutdown
  order. README now says six phases and documents artifact retention and the runner.

### Fresh remediation gates

- Focused Python (`test_task6_hardening`, AnswerContract v2, CLI, corpus migration):
  **75 passed**.
- Exact black-box plus both CLI replay registry branches: **3 passed in 8.62s**.
- Full Python after final external-review remediation: **363 passed, 2 skipped in
  95.35s** (only Swiss-ephemeris tests).
- Tuning runner: **17 automated passed, 23 manual_not_scored, 40 total**.
- Explicit held-out runner: **11 automated passed, 9 manual_not_scored, 20 total**.
- Bun: **45 passed, 0 failed, 144 assertions**.
- TypeScript `tsc --noEmit`: **passed**.
- `compileall`: **passed**.
- Both repository-local skills: **valid**.
- Split SHA-256 manifests: **all five unique files OK**; 60 cases across 13 groups.
- `git diff --check`: **passed**.

External limitations are unchanged: no live Pi/Gemini call without credentials and
no Swiss ephemeris files. The four independent-oracle placeholders remain explicitly
unscored; the implementation does not invent those external values.
