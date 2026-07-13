# Task 1 report — Phase 0 Jaimini contracts

Status: DONE_WITH_CONCERNS

## Implementation

- Added strict additive Pydantic contracts for exact and approximate Jaimini birth
  inputs. The union is discriminated by `confidence`; `unknown` is not a valid
  branch. Approximate ranges must be ordered, no longer than 120 minutes, and
  declare a five-minute sweep capped at 25 samples.
- Added the closed `jaimini_core_v1` profile ID, closed analysis scopes, four
  status-discriminated result branches, compact bounded sections/facts,
  limitations, provenance, interpretation status, and consistent truncation
  counts.
- Added an immutable validated `jaimini_core_v1` package-data profile with explicit
  choices for 7/8 karakas, PiK, Rahu reversal, one-arcsecond precision, exact and
  near ties, arudha exception, Scorpio/Aquarius co-lords, Chara Dasha
  progression/duration/antardasha, gender semantics, 365.2425-day years,
  microsecond half-even rounding, and half-open bounds.
- Added source/rule mapping metadata. The profile file checksum is verified by the
  focused test. Review status is honestly `pending`, reviewer identity/role and
  fragment IDs/checksums are `null`, calculations are marked available at the
  contract layer, and interpretation is unavailable.
- Added five synthetic/public-safe fixtures for the required adjudication cases.
  Inputs, hashes, provenance, and review state validate now; expected calculation
  fields are explicitly pending the independent implementation.
- Added seven uppercase domain errors and optional `request_id`, `mode`,
  `next_action`, `invalid_fields`, and `supported_values`. Existing registry calls
  retain their exact seven-field output.
- Documented the Phase 0 contract, examples, limitations, source gate, fixtures,
  and error recovery behavior. No Jaimini geometry or existing API/MCP/ResearchRun
  contract change was introduced.

## TDD evidence

RED, before production implementation:

```text
$ uv run pytest -q tests/test_task1_jaimini_contracts.py
E   ModuleNotFoundError: No module named 'jyotish_agent.jaimini_models'
1 error in 0.08s
```

The failure was expected: the new contract module did not exist.

Focused GREEN:

```text
$ uv run pytest -q tests/test_task1_jaimini_contracts.py
............ [100%]
12 passed in 0.16s
```

Adjacent legacy error-envelope regression:

```text
$ uv run pytest -q tests/test_task6_hardening.py -k 'error_registry or problem_responses'
10 passed, 39 deselected in 0.22s
```

Wheel/package data:

```text
$ uv build --wheel --out-dir /tmp/jyotish-task1-dist
Successfully built jyotish_agent-0.1.0-py3-none-any.whl
wheel package-data OK: 3 Jaimini files
```

Full Python suite:

```text
$ uv run pytest -q
406 passed, 2 skipped in 88.28s
```

Both skips are the pre-existing Swiss-ephemeris-only golden checks; Moshier is the
available fallback in this environment.

## Files

- `src/jyotish_agent/jaimini_models.py`
- `src/jyotish_agent/rule_profiles.py`
- `src/jyotish_agent/data/jaimini/jaimini_core_v1.json`
- `src/jyotish_agent/data/jaimini/jaimini_core_v1_sources.json`
- `src/jyotish_agent/data/jaimini/adjudication_fixtures_v1.json`
- `src/jyotish_agent/error_registry.py`
- `tests/test_task1_jaimini_contracts.py`
- `docs/jaimini-phase-0.md`
- `docs/debugging-error-codes.md`

## Self-review

- Verified strict extra-field rejection, closed literals, discriminators, invalid
  uncertainty ranges, frozen profile values, profile checksum, fail-closed source
  state, fixture privacy/review state, legacy error shape, and documentation status.
- Built the wheel outside the worktree and inspected its ZIP members to prove the
  three JSON resources are installed package data.
- Ran `git diff --check`; no whitespace errors were found.
- No natal calculation modules, MCP models/facades/server, API routes,
  ResearchRun models/services, PyJHora code, or geometry were modified.

## Concerns / explicit gates

- No qualified reviewer is assigned and no Jaimini source fragments are admitted.
  This is not represented as approval. Interpretation must remain unavailable.
- Fixture expected calculations remain pending and must be independently produced
  and human-adjudicated; they must not be regenerated from the implementation under
  test.
- The frozen doctrinal/time choices are executable project choices, not a claim of
  source correctness. Changing them after adjudication requires a new profile
  version and migration note rather than mutating v1.
