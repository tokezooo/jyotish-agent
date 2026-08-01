# Muhurta specialist-review handoff

This package prepares the source-bound `classical_baseline_v1` Muhurta rule pack
for a qualified external reviewer. It covers exactly two admitted interval rules
and six safe activity profiles. It does not include source text, local paths, the
missing B. V. Raman overlay, or high-stakes activities.

Generate the deterministic tracked handoff:

```bash
uv run python scripts/run_muhurta_specialist_review.py handoff \
  --json-out docs/evidence/doctrine/muhurta-specialist-review-handoff.json
```

Generate the exact strict response schema distributed with it:

```bash
uv run python scripts/run_muhurta_specialist_review.py response-schema \
  --json-out docs/evidence/doctrine/muhurta-specialist-review-response.schema.json
```

Give the reviewer lawful access to the local source edition and the page locators
listed in the handoff. Keep their response under ignored `private_evidence/`.
Each response must identify a qualified human, attest independent source access,
bind every decision to the exact subject hash, and contain no copied source text.
The handoff binds the response schema by both repository path and SHA-256.

Evaluate a response:

```bash
uv run python scripts/run_muhurta_specialist_review.py evaluate \
  docs/evidence/doctrine/muhurta-specialist-review-handoff.json \
  private_evidence/muhurta-specialist-response.json \
  --json-out private_evidence/muhurta-specialist-report.json \
  --require-approved
```

Exit status `2` means decisions are incomplete or amendments still need to be
implemented and re-reviewed. Exit status `3` means at least one subject was
rejected. Only an exact complete set of approved decisions passes the specialist
review gate. The aggregate report omits the reviewer's name, qualification note,
and decision notes; it retains hashes and counts for release evidence.
