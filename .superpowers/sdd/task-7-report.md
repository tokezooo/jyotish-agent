# Task 7 report — integration, docs, benchmarks, release verification

## Outcome

Integrated natural RU/EN routing for the three additive MCP tools, published strict
tool-schema drift snapshots and per-domain operational docs, added a pure privacy-safe
operation-metric projection, and produced reproducible benchmark, stdio-matrix, and
61-requirement audit artifacts. Existing natal/API/Pi/ResearchRun surfaces were not
expanded. All new tools remain stateless, read-only/idempotent, and fail closed.

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

## Stdio and requirement audit

The process-level matrix records 17 privacy-safe cases across RU/EN Jaimini exact/
approximate/inspection/tie/boundary, Prashna explicit/capture/retry/clarification/
mismatch/unsafe/invalid-secret, and Muhurta one-day/multi-day/empty/oversized/
cancellation/deadline/high-stakes. Existing real `ClientSession` stdio tests execute
the public transport. Focused signing/checker tests assert artifact substitution and
unsupported prose fail closed. Data-root snapshots/counts prove no ResearchRun or
domain persistence.

The requirement audit has 61 stable IDs: 44 `met`, 11
`intentionally_unavailable`, 5 `not_in_scope`, and 1 `gap`. The remaining gap is a
real Codex conversational quick/inspection smoke (the local MCP stdio transport is
covered). External source admission, qualified human review, adjudicated real sessions,
governed interpretation/ranking, and Muhurta natal personalization are explicitly
unavailable rather than silently marked complete.

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
4. Run real Codex conversational RU/EN quick and inspection smokes. Do not infer that
   passing stdio transport tests proves the final conversational rendering quality.
