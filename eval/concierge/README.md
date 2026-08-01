# Cross-domain concierge evidence

This gate requires 10–20 real, explicitly opt-in sessions across Jaimini,
Prashna, and Muhurta. Raw questions, names, birth data, places, timestamps,
free-form notes, and source text do not belong in the evaluation dataset.

Keep the input under the ignored `private_evidence/` directory. The strict
schema accepts only an opaque session ID and bounded product metrics:

- consent to aggregate;
- domain and enumerated low-risk use case;
- answered/no-answer/blocked status;
- decision change or clarification;
- follow-up and observed 30-day return;
- 1–5 value score;
- assistant and optional manual-alternative latency;
- preference against the compared alternative;
- optional reviewer material-error decision;
- Prashna eventual-outcome status where feasible.

The evaluator rejects unknown fields, so raw question text or user metadata
cannot silently enter the aggregate. A release-ready snapshot needs at least
10 sessions, evidence from all three domains, and at least one reviewer error
decision and one alternative comparison per domain. The dataset is capped at
20 sessions for this v1 gate.

Run:

```bash
uv run python scripts/run_concierge_eval.py \
  private_evidence/concierge-v1.json \
  --json-out private_evidence/concierge-report-v1.json \
  --require-ready
```

Exit status `2` means the input is valid but the evidence gate is incomplete.
The generated report contains aggregate metrics and content hashes only. Review
it before copying it into tracked doctrine evidence; never commit the private
input dataset.
