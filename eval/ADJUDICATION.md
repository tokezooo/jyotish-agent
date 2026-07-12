# Evaluation adjudication rubric

The frozen corpus contains 40 tuning cases and exactly 20 physically separate
held-out cases. Do not read held-out expected outcomes while changing prompts,
policies, or implementation. A human reviewer is the final judge; a model may
summarize artifacts but must never be the sole adjudicator.

Score each dimension from 0 to 3 and record evidence, reviewer identity, UTC time,
runtime versions, duration, and whether a material rewrite was required.
The persisted record schema requires `run_id`, `started_at`, `finished_at`,
`duration_ms`, exact `engine`/`planner`/`corpus`/`contract` versions, and SHA-256
`artifact_hashes`; incomplete metadata is rejected.

| Dimension | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| Relevance | misses task | mostly off-task | answers core task | precise and scoped |
| Depth | empty | superficial | adequate | explains material nuance |
| Clarity | unusable | confusing | understandable | concise and unambiguous |
| Traceability | no support | incomplete IDs | support resolvable | exact IDs, locators, hashes |
| Actionability | none | vague | usable next step | bounded concrete next step |
| Unsupported claims | major | several | minor | none |
| Timings | absent/false | unclear | named system/date | boundaries and uncertainty explicit |

`material_rewrite` is `true` when a reviewer must change a conclusion, add/remove
a major claim, repair evidence lineage, change safety handling, or correct a timing
window. Record `pass` only when every safety/integrity hard gate passes, unsupported
claims score 3, traceability scores at least 2, and no material rewrite is needed.

Oracle placeholders are intentionally unscored. Populate an oracle only from an
independent artifact with exact tool/version, input, timestamp, output checksum,
rights/provenance URL, and reviewer; never copy the system-under-test output.

## Fixed executable specifications

`fixtures/tuning-specs.json` and `fixtures/held-out-specs.json` map every case to
either an exact production-boundary probe or an explicit `manual_not_scored`
reason. There are 28 deterministic automated cases and 32 manual cases. A case is
never called automated merely because a related generic test passes. Run the
40-case tuning split with:

```bash
uv run python -m jyotish_agent.evaluation tuning
```

The 20-case held-out split is physically separate and requires the declared final
review gate `held-out --allow-held-out`. Split-specific
`fixtures/tuning-checksums.json` and `fixtures/held-out-checksums.json` freeze only
the files visible to that run; checksum drift fails before a probe executes.
