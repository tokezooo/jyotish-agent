# Jaimini Core v1 Phase 0 contract status

Phase 0 freezes executable contracts and package data. It does not admit an
interpretive Jaimini product.

- rule profile: `jaimini_core_v1` version `1.0.0`
- calculation_status: available (contract status only; geometry is a later task)
- interpretation_status: unavailable
- source review status: pending
- qualified reviewer: not assigned
- independent expected fixture calculations: pending

No Jaimini geometry, PyJHora prediction text, MCP tool, REST endpoint, Pi schema,
ResearchRun projection, or answer-checking claim is introduced in this phase.
Existing natal, MCP, API, and ResearchRun contracts remain unchanged.

## Frozen choices

The package profile explicitly records the 7- and 8-kāraka schemes, PiK addition,
Rahu reversal, one-arcsecond ranking precision, exact and near-tie behavior, the
arūḍha same/seventh exception, Scorpio/Aquarius co-lords and their resolution,
Chara Daśā progression/duration/antardaśā variants, required binary gender values,
365.2425-day years, half-even microsecond rounding, and `[start,end)` intervals.
These are project contract choices, not assertions that a source reviewer approved
them.

## Source and reviewer limitation

`jaimini_core_v1_sources.json` maps every frozen rule to a deliberately pending
source entry. Fragment IDs and fragment checksums are `null`; reviewer identity and
role are also `null`. The metadata describes the admission criteria and procedure
without fabricating sign-off. Calculated facts may be added later, but doctrinal
interpretation must return `interpretation_status: unavailable` and
`next_action=inspect_source_status` until each mapping and the fixture set are
approved by a qualified human reviewer.

## Contract examples

Exact input:

```json
{"profile":"example","birth":{"confidence":"exact","date":"1990-01-15","time":"10:30:00","place":{"name":"Example","latitude":12.5,"longitude":77.25,"timezone":"Asia/Kolkata"}},"rule_profile":"jaimini_core_v1","analysis_scope":"core_with_chara_dasha"}
```

Approximate input uses `earliest_time` and `latest_time`, rejects unknown
confidence, requires an ordered range of at most 120 minutes, and declares a
five-minute sweep (at most 25 samples). It never analyzes only the midpoint.

Results are a `status`-discriminated union: `completed`, `needs_input`,
`unavailable`, or `incomplete`. Completed results use bounded compact sections,
explicit limitations/provenance, and `truncated`, `total_count`, and
`returned_count`. Rescue results carry a closed machine-readable `next_action`.

## Fixtures

The five bundled inputs are synthetic and public-safe. They cover an exact kāraka
tie, arūḍha exception, Scorpio co-lord resolution, an exact half-open Daśā boundary,
and a 120-minute approximate-time sensitivity sweep. Their input/provenance/review
metadata is executable now; expected geometry remains
`pending_independent_implementation` and may not be generated from the future
implementation under test.
