# Evaluation adjudication rubric

The frozen corpus contains 40 tuning cases and exactly 20 physically separate
held-out cases. Do not read held-out expected outcomes while changing prompts,
policies, or implementation. A human reviewer is the final judge; a model may
summarize artifacts but must never be the sole adjudicator.

Score each dimension from 0 to 3 and record evidence, reviewer identity, UTC time,
runtime versions, duration, and whether a material rewrite was required.

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

`fixtures/specs.json` maps every one of the 60 case IDs to an explicit setup,
deterministic repository command, and exact exit-code assertion. The four missing
independent-oracle cases are instead marked `manual_not_scored` with a reason. Run
the 40-case tuning split with:

```bash
uv run python -m jyotish_agent.evaluation tuning
```

The 20-case held-out split is physically separate and requires the declared final
review gate `held-out --allow-held-out`. `fixtures/checksums.json` freezes SHA-256
digests for profiles, both case files, and executable specs; checksum drift fails
before a runner command executes.
