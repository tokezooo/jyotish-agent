# Jaimini Core v1 — operational contract

Use the read-only `jaimini` MCP tool with the default private profile or a complete inline
profile, `jaimini_core_v1`, a reference date, and gender when Chara Dasha is requested.
Natural conversation hides hashes, fact paths, rule IDs, traces, and artifact tokens.

## Confidence matrix

| Birth time | Behavior |
|---|---|
| exact | One signed calculation. |
| approximate | An explicit range divisible by five minutes, at most 120 minutes/25 inclusive samples; unstable facts are marked. |
| unknown | Unsupported; provide a bounded range before analysis. |

Included: 7/8 chara-karakas, rasi drishti, A1–A12/AL/UL, argala geometry,
svamsa/karakamsa, BL/HL/GL, scheme-qualified relationship geometry, and one frozen
Chara Dasha maha/antardasha timeline. Other rasi dashas and prediction prose are omitted.

## Current state, limits, and errors

Computed facts, timing, signed artifact, atomizer, and checker are available. Governed
conversational doctrine is **unavailable**: source mappings, qualified human review, and
adjudicated cases remain pending. This proves deterministic calculation, not doctrinal
correctness or user value. Normal payload is below 512 KiB; at most 12 top-level and 144
nested periods are returned. Exact ties require adjudication; approximate ranges can return
`provide_birth_range`, and engine failures return a privacy-safe rescue.

## Privacy and inspection

No ResearchRun, API, Pi write, or persistence occurs. Do not put birth data in bug reports.
Inspection is explicit opt-in with `include_trace=true`; inspect hashes/source status only when
asked. Migration and backup impact: none, because this vertical is stateless and additive.
