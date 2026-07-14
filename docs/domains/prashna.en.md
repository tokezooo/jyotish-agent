# Prashna work/project v1 — operational contract

Use the read-only `prashna` tool only for one low-risk work/project status or obstacle question.
Provide one explicit RFC3339 moment plus regional IANA place, or `capture_now` with place and a
16–128 character idempotency key. Capture happens once. Clarification reuses the opaque token;
a materially new question must create a new anchor.

## Confidence matrix

| Time | Behavior |
|---|---|
| exact / explicit | Offset, IANA zone, and fold must resolve to one instant. |
| approximate | Not a Prashna anchor mode; confirm one operational moment. |
| unknown / “now” | `capture_now` seals one server clock reading and returns a confirmation summary. |

Included: time-chart D1 facts, panchanga, lagna/Moon/lords, rasi/graha drishti, typed work
topic routing, readability traces, sealed replay, signed artifact, and checker. KP-249/108,
Nadi, applying/separating judgement, composite topics, and high-stakes prediction are omitted.

## Current state, limits, and errors

Facts and anchor lifecycle are available; doctrinal judgement is **unavailable** pending source
mapping, reviewer, and adjudication. At most 100 rules and a 512 KiB payload are returned.
`ANCHOR_MISMATCH` creates a new anchor; `ANCHOR_STALE` recaptures; unsupported/composite topics
need one primary question; high-stakes topics route to a qualified professional.

## Privacy and inspection

Tokens expose no question, coordinates, place, or birth data. No ResearchRun or durable record is
created. Inspection is opt-in with `include_trace=true`. Migration/backup impact: none; the small
capture/replay cache is process-local and is not an authoritative store.
