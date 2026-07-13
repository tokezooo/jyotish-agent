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

## Review-fix follow-up

Implemented all Critical and Important review findings and the feasible timezone
Minor without adding geometry or a new public surface:

- Result validation now couples `status`, `interpretation_status`, and
  `provenance.source_review_status`. Only a `completed` result backed by approved
  source review may claim available interpretation. All other combinations fail
  closed during Pydantic validation.
- The committed package-data regression now builds a wheel into `tmp_path`, checks
  its members, creates an isolated venv, installs the wheel without dependencies,
  and reads all three JSON resources from the installed package via
  `importlib.resources`.
- The fixture loader recomputes the actual profile and source-map SHA-256 hashes.
  It rejects either tampered file, validates every fixture hash against the bytes,
  and also binds each fixture to the source map's profile ID.
- Approved review metadata now requires both reviewer identity and reviewer role.
  Approved rule mappings require an admitted `sf_...` fragment ID shape and a
  lowercase 64-hex SHA-256. An overall approved source map requires every rule to
  be approved and bound; available interpretation additionally requires that fully
  approved map.
- `JaiminiPlace.timezone` now resolves through the standard-library IANA tzdb
  (`zoneinfo.ZoneInfo`) and rejects invented/fixed-offset labels.

### Review-fix RED

Tests were added before the fixes:

```text
$ uv run pytest -q tests/test_task1_jaimini_contracts.py
......FFFF..FFF...FFF.. [100%]
10 failed, 13 passed in 0.39s
```

The failures were the expected missing guards: non-completed/unsourced available
interpretation did not raise, tampered profile/source bytes did not raise, approved
metadata accepted no reviewer role, and non-IANA timezone labels were accepted.
The newly committed wheel build/install test passed in this RED run, demonstrating
that packaging behavior already existed while its automated installed-artifact
regression did not.

### Review-fix GREEN

```text
$ uv run pytest -q tests/test_task1_jaimini_contracts.py
....................... [100%]
23 passed in 0.43s
```

Final suite (run once after all review fixes):

```text
$ git diff --check && uv run pytest -q
417 passed, 2 skipped in 88.74s
```

The two skips remain the environment's pre-existing Swiss-ephemeris-only golden
checks. No additional warning or regression appeared.
