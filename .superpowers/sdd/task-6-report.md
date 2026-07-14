# Task 6 report — Muhurta boundary search

## Outcome

Implemented the bounded `general` plus `focused_work_session_v1` calculation wedge.
It collects daily astronomical transitions in one configured `ENGINE_LOCK` batch,
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

Focused GREEN:

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q \
  tests/test_muhurta_core.py tests/test_muhurta_mcp.py \
  tests/test_muhurta_package.py tests/test_mcp_server.py tests/test_mcp_stdio.py

22 passed in 16.96s
```

This covers half-open/DST/property behavior, transition boundaries, hard monotonicity,
stable ordering, source-gate states, optional natal omission/supply behavior, completed
empty results, near misses, range/candidate/payload limits, cancellation/deadline,
signatures/atoms/substitution/privacy, mixed-zone concurrency, wheel data, tool metadata,
and real RU/EN process-level stdio scenarios.

Full GREEN:

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q

537 passed, 2 skipped in 148.97s
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
{"candidate_intervals":35,"max_ms":947.746,"min_ms":931.546,"p50_ms":935.168,"p95_ms":947.728,"result_bytes":7391,"source_gate":"pending","warm_runs":10}
```

The benchmark is saved in `.superpowers/sdd/task-6-benchmark.json`. It supports the
31-day validation maximum as an input bound, not a promised 31-day latency SLO.

## Honest limitations

- No licensed/public-domain Muhurta doctrine pack, qualified reviewer, or five approved
  adjudications is admitted; all such metadata remains `pending`.
- Boundary facts include sunrise/sunset, tithi, nakshatra, yoga, karana, lagna,
  rahu-kala, yamaganda, gulika, durmuhurta, abhijit, varjyam, and amrita primitives,
  but none is treated as doctrinally favorable/unfavorable while the gate is pending.
- Optional natal material is hash-bound only; tara-bala/candra-bala are omitted rather
  than guessed while their governed semantics are unavailable.
- Requested planetary-change boundaries are not accepted because no independently
  verified public request primitive is exposed.
- The engine is local-only and PyJHora/AGPL distribution constraints remain unchanged.
