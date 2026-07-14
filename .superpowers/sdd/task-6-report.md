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

Focused GREEN:

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q \
  tests/test_muhurta_core.py tests/test_muhurta_mcp.py \
  tests/test_muhurta_package.py tests/test_muhurta_benchmark.py \
  tests/test_mcp_server.py tests/test_mcp_stdio.py

32 passed in 14.11s
```

This covers half-open/DST/property behavior, transition boundaries, hard monotonicity,
stable ordering, source-gate states, optional natal omission/supply behavior, completed
empty results, near misses, range/candidate/payload limits, cancellation/deadline,
signatures/atoms/substitution/privacy, mixed-zone concurrency, wheel data, tool metadata,
and real RU/EN process-level stdio scenarios.

Full GREEN:

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q

547 passed, 2 skipped in 148.08s
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
{"candidate_intervals":47,"config_sha256":"821df6ee9b5cd8bc89f5fba821edbd4b438021912a40a765c986563f5b856f84","ephemeris_mode":"moshier","max_ms":476.812,"min_ms":466.57,"p50_ms":469.397,"p95_ms":476.812,"python":"3.12.2","result_bytes":9583,"rule_profile_sha256":"f44c67aa29134f0dc99caa12fe2507bae053e405fda9cafc0529344d4cd6a21c","runner":"scripts/benchmark_muhurta.py","source_gate":"pending","source_map_sha256":"6b0babb5a5b004cb49ac97aadd716e8e17c3d2ae69bfb5f946add900aa30eae4","warm_runs":10}
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
