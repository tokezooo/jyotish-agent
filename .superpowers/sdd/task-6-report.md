# Task 6 report — Muhurta boundary search

## Outcome

Implemented the bounded `general` plus `focused_work_session_v1` calculation wedge.
It collects each civil day's astronomical transitions in its own configured
`ENGINE_LOCK` checkpoint,
partitions pure half-open intervals, applies only explicit non-doctrinal hard constraints,
and returns calendar-ready windows and near misses. The governed source/reviewer gate is
still pending, so doctrinal eligibility, soft ranking, tara/candra bala, and interpretation
remain typed `unavailable`; no approval was fabricated.

The additive `muhurta` MCP tool is read-only/idempotent and performs no ResearchRun,
persistence, REST/Pi/API, calendar write, or external side effect. Existing tools were not
changed except for the expected additive discovery snapshot.

## TDD evidence

Observed RED 1:

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q \
  tests/test_muhurta_core.py tests/test_muhurta_mcp.py

ModuleNotFoundError: No module named 'jyotish_agent.intervals'
ImportError: cannot import name 'MuhurtaMcpInput'
```

Observed RED 2 after the core landed:

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q \
  tests/test_muhurta_core.py -k signed_answer

ImportError: cannot import name 'iter_muhurta_fact_atoms'
```

Observed review-fix RED:

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/test_muhurta_core.py

ImportError: cannot import name '_run_muhurta_boundary_day'
```

The review-fix cycle then added UTC-instant interval algebra, endpoint-specific DST
fold binding, daily cooperative checkpoints, complete panchanga transition probes,
strict future source admission, exact rule-trace coverage, runtime-material replay
checks, and actual config/ephemeris provenance.

Observed second review-fix RED:

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/test_muhurta_core.py

ImportError: cannot import name '_MuhurtaBoundaryEstimate'
```

The second review-fix cycle replaced the single daily numeric offset with actual IANA
offsets at each astronomical probe, evaluates daily primitives for every offset segment
on transition days, and canonicalizes repeated estimates by semantic transition identity
and physical UTC proximity. The governed profile freezes this behavior as version `1.0.0`
with a 900-second tolerance. It also made the default end executable as seven local civil
days and added explicit trace-cap metadata.

Focused GREEN:

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q \
  tests/test_muhurta_core.py tests/test_muhurta_mcp.py \
  tests/test_muhurta_package.py tests/test_muhurta_benchmark.py \
  tests/test_mcp_server.py tests/test_mcp_stdio.py

37 passed in 18.20s
```

This covers half-open/DST/property behavior, transition boundaries, hard monotonicity,
stable ordering, source-gate states, optional natal omission/supply behavior, completed
empty results, near misses, range/candidate/payload limits, cancellation/deadline,
signatures/atoms/substitution/privacy, mixed-zone concurrency, wheel data, tool metadata,
and real RU/EN process-level stdio scenarios.

Full GREEN:

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q

552 passed, 2 skipped in 151.85s
```

The two skips are the existing Swiss-ephemeris-only goldens; Moshier completed.

Additional gates:

```text
uvx ruff check <Task 6 affected Python files>
All checks passed!

git diff --check
# clean

uv build --wheel --out-dir <temporary directory>
# exercised by tests/test_muhurta_package.py; all three governance files present
```

## One-day warm benchmark

Ten warm one-day Moscow focused-work searches, 90-minute duration:

```json
{"candidate_intervals":36,"case":"one_day_moscow_focused_work_90m","config_sha256":"821df6ee9b5cd8bc89f5fba821edbd4b438021912a40a765c986563f5b856f84","ephemeris_mode":"moshier","max_ms":478.144,"min_ms":467.698,"p50_ms":469.564,"p95_ms":478.144,"python":"3.12.2","result_bytes":9820,"rule_profile_sha256":"aaa494c6f0bb6f6ffe7d244c51024ed4f5a69e4da700eb347639c3e007afddab","runner":"scripts/benchmark_muhurta.py","source_gate":"pending","source_map_sha256":"1943f1617abb4c8bcf8aef2bff9c93257b73a27c275df5433d711a780c70a947","transition_canonicalization_version":"1.0.0","transition_cluster_tolerance_seconds":900,"warm_runs":10}
```

The reproducible runner is `scripts/benchmark_muhurta.py`; its captured artifact is
saved in `.superpowers/sdd/task-6-benchmark.json`. It supports the
31-day validation maximum as an input bound, not a promised 31-day latency SLO.

## Honest limitations

- No licensed/public-domain Muhurta doctrine pack, qualified reviewer, or five approved
  adjudications is admitted; all such metadata remains `pending`.
- Boundary facts include sunrise/sunset, tithi, nakshatra, yoga, karana, lagna,
  rahu-kala, yamaganda, gulika, durmuhurta, abhijit, varjyam, and amrita primitives,
  but none is treated as doctrinally favorable/unfavorable while the gate is pending.
- Optional natal material is explicitly labelled supplied-but-not-evaluated and
  hash-bound only; tara-bala/candra-bala are omitted rather than guessed while their
  governed semantics are unavailable.
- Requested planetary-change boundaries are not accepted because no independently
  verified public request primitive is exposed.
- The engine is local-only and PyJHora/AGPL distribution constraints remain unchanged.
