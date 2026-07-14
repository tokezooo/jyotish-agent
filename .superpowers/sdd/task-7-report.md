# Task 7 report — integration, docs, benchmarks, release verification

## Outcome

Integrated natural RU/EN routing for the three additive MCP tools, published strict
tool-schema drift snapshots and per-domain operational docs, added a pure privacy-safe
operation-metric projection, and produced reproducible benchmark, mixed
release-evidence matrix, and 90-requirement audit artifacts. Existing
natal/API/Pi/ResearchRun surfaces were not expanded. All new tools remain stateless,
read-only/idempotent, and fail closed.

The release is intentionally calculation-only. Jaimini governed doctrine, Prashna
doctrinal judgement, Muhurta doctrinal eligibility/ranking and natal personalization,
qualified source/reviewer admission, and real concierge validation are not claimed.

## TDD evidence

Initial RED:

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/test_task7_release.py
ModuleNotFoundError: No module named 'jyotish_agent.operation_metrics'
```

The first focused integration run found one additional privacy RED: the stdio summary
described forbidden field categories by their literal key names. The artifact now uses
only a generic privacy statement and the test passes.

Final focused GREEN:

```text
tests/test_task7_release.py
7 passed in 0.31s

tests/test_task7_release.py tests/test_mcp_server.py tests/test_jaimini_mcp.py
tests/test_prashna_mcp.py tests/test_muhurta_mcp.py
18 passed in 12.64s (one RED fixed, rerun release slice 7 passed)
```

Final full Python gate:

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
572 passed, 2 skipped in 151.45s
```

The two skips are the existing Swiss-ephemeris-only goldens. Moshier goldens,
concurrency, all domain tests, real stdio tests, privacy, package, and ResearchRun
regressions passed.

## Routing and documentation

- `.agents/skills/jyotish-consultant` routes natural Jaimini, Prashna, and Muhurta
  questions to their dedicated tools, preserves ordinary conversational answers, and
  hides hashes/paths/rules/tokens unless inspection is explicitly requested.
- Six concise RU/EN domain documents cover required inputs, exact/approximate/unknown,
  anchor/range lifecycle, included and omitted methods, source/reviewer state, rescue
  behavior, privacy, inspection, payload/search/sample limits, and no migration impact.
- README, error-code guide, migration/backup guide, and TODOS now state the exact
  operational state without claiming pending doctrine or review.

## Metrics and schema drift

`operation_metrics.project_operation_metric` accepts only mode, status, duration,
three cardinalities, truncation, and a stable uppercase error code. It buckets duration
and has no sink or persistence. Its API cannot accept questions, answers, coordinates,
place/profile labels, times, anchors, tokens, fingerprints, or traces.

`docs/domain-tool-snapshot-v1.json` pins live descriptions, annotations, and canonical
input/output-schema SHA-256 for `jaimini`, `prashna`, and `muhurta`. The drift test builds
the real server and compares discovery while preserving strict read-only/idempotent
metadata.

## Realistic local benchmark

Command:

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python scripts/benchmark_domains.py --runs 3
```

Warm local evidence on Python 3.12.2 / Moshier-configured local runtime:

| Case | p50 ms | p95 ms | bytes |
|---|---:|---:|---:|
| Jaimini exact | 672.750 | 674.430 | 42,478 |
| Jaimini approximate, 10 minutes / 3 samples | 2,009.663 | 2,027.020 | 42,993 |
| Prashna explicit | 673.556 | 679.383 | 9,942 |
| Prashna first capture | 678.843 | 679.115 | 9,942 |
| Prashna token replay | 684.299 | 688.766 | 9,947 |
| Muhurta one day | 478.620 | 481.827 | 9,820 |

These are environment-specific evidence, not universal SLOs. Every result was signed,
completed with source status pending, and below 512 KiB. The machine artifact is
`docs/release-benchmark-v1.json`; `.superpowers/sdd/task-7-benchmark.json` binds it by
checksum.

## Mixed release evidence and requirement audit

The mixed release-evidence matrix records 17 privacy-safe cases. Its `process_stdio`
subset is exactly 11 cases: Jaimini RU exact and EN approximate; Prashna RU explicit,
EN capture/clarification, material mismatch, and invalid-secret wire input; Muhurta RU
one-day, EN multi-day, successful empty, oversized range, and high-stakes activity.
Those cases run through real `ClientSession` stdio public transport. Four cases are
explicitly `facade` evidence (Jaimini tie and inspection, Prashna high-stakes, Muhurta
cancel/deadline), and two are `pure_core` evidence (Jaimini half-open boundary and
checker). Every case maps its own assertions to evidence; there is no blanket
process-level claim. Focused signing/checker tests assert artifact substitution and
unsupported prose fail closed. Data-root snapshots/counts prove no ResearchRun or
domain persistence where that assertion is attached.

The final requirement audit has 90 stable IDs: 62 `met`, 19
`intentionally_unavailable`, 9 `not_in_scope`, and zero `gap` rows. A separately named
doctrinal-quality held-out evaluation remains intentionally unavailable until governed
sources and qualified review exist. External source admission, qualified human
review, adjudicated real sessions, governed interpretation/ranking, and Muhurta natal
personalization are explicitly unavailable rather than silently marked complete.

## Other release gates

```text
uvx --from ruff==0.12.4 ruff check <Task 7 Python/test/script files>
All checks passed!

bun run typecheck
bun test ./ts-tests/jyotish.test.ts
52 passed, 0 failed

uv build --wheel --out-dir /tmp/jyotish-task7-wheel
Successfully built jyotish_agent-0.1.0-py3-none-any.whl
```

Wheel inspection found all nine immutable package-data files for Jaimini, Prashna,
and Muhurta. `git diff --check` is clean.

## Honest remaining gates

1. Admit licensed/public-domain mapped fragments and qualified reviewers separately
   for each domain; keep every current source file pending until then.
2. Replace synthetic/pending cases with independently adjudicated fixtures without
   regenerating expectations from production code.
3. Run 10–20 real/concierge sessions and record usefulness, follow-up/return behavior,
   reviewer material-error rate, latency versus manual work, and preference.
4. Run doctrinal-quality held-out evaluation only after sources/reviewers are admitted.

## Independent review-fix addendum

The first Task 7 review requested changes. The following fixes landed test-first:

1. The transport artifact no longer calls facade/core evidence stdio. Every one of its
   17 cases now declares `process_stdio`, `facade`, or `pure_core` and maps each claimed
   assertion to exact evidence. There are no blanket common assertions.
2. The audit expanded from 61 to 90 plan requirements and is checked for exact equality
   against `tests/fixtures/task7_requirement_manifest_v1.json`, grouped by authoritative
   plan sections. It explicitly includes held-out adversarial evals, independent versus
   adjudicated goldens, applying/separating geometry, soft ranking, requested planetary
   changes, optional surfaces, release criteria, and not-in-scope boundaries.
3. Operation metrics now accept only codes present in `ERROR_REGISTRY`, require a strict
   boolean truncation flag and strict numeric/count/mode/status types, and reject private
   uppercase strings and arbitrary objects.
4. Six real Codex CLI smokes passed: RU quick plus RU inspection Jaimini, RU quick plus
   EN inspection Muhurta, and RU quick plus EN inspection Prashna. All used the correct
   dedicated MCP tool, produced natural answers, kept source gates honest, and exposed no
   private material or internal ledgers. A pre-fix normal Prashna answer inferred a
   communication/ownership theme from literal factors while source review was pending.
   It is retained as an excluded failed attempt. Commit `75e16b0` added explicit skill
   and server guards; the original normal prompt then passed without practical inference.
   Each counted smoke and the excluded failure now has a canonical privacy-safe execution
   record under `docs/evidence/codex-smokes/`, including client/version, completion time,
   read-only sandbox, path-free MCP command identity, ordered thread/tool/final events,
   complete sanitized natural output, redaction policy, and raw untracked JSONL SHA-256.
   The index binds every record by a second SHA-256; tests recompute both layers.
5. A genuinely held-out static calculation/trust fixture now drives 15 adversarial cases:
   Jaimini tie/approximate/source-prose/substitution, Prashna anchor/retry/privacy/safety/
   source state, and Muhurta skipped-date/stale-window/cancel/deadline/payload/source state.
   Expected outcomes are independently authored package-external fixture data; production
   never reads them. The reproducible runner passed 15/15 and emitted a checksum-bound artifact.

Review-fix RED evidence:

```text
Task 7 focused tests:
- private uppercase error codes were accepted by the metric projector
- the matrix falsely declared mixed facade/core cases as stdio
- the pending-source practical-inference guard was absent from skill/server instructions
- no durable, independently hash-bound execution records existed for the six counted
  Codex smokes or the excluded pre-guard failure
```

Review-fix GREEN evidence:

```text
tests/test_task7_release.py: 13 passed
Held-out calculation/trust eval: 15 passed, 0 failed
Task 7 release + MCP focused suite: 24 passed in 17.35s
Full Python suite: 578 passed, 2 Swiss-only skipped in 156.70s
Codex smoke privacy scan: clean
Ruff: All checks passed
git diff --check: clean
Wheel: built successfully; all nine domain governance assets present
Bun: typecheck plus 52 tests passed
```
