# Debugging and structured errors

Problem responses include `error_code`, `run_id`, `stage`, `retryable`, `problem`,
`cause`, and `fix` in addition to RFC 7807 fields. Logs contain method, path, status,
duration, and non-secret IDs only—never birth profiles, questions, claims, retrieved
text, prompts, tokens, or rendered answers.

| Code | Meaning | Retry |
|---|---|---|
| `SQLITE_BUSY` | bounded ledger lock wait expired | yes, then inspect writers |
| `CORRUPT_LEDGER` | event/payload/index integrity failed | no; restore backup |
| `PINNED_VERSION_MISSING` | exact replay dependency absent | no; restore version |
| `RENDER_HASH_MISMATCH` | memo bytes differ from committed hash | no; reject artifact |
| `UNEXPECTED_INTERNAL` | privacy-safe unexpected failure | once |

Endpoint-specific codes such as `TIMEZONE_OFFSET_MISMATCH`,
`AMBIGUOUS_LOCAL_TIME`, `NONEXISTENT_LOCAL_TIME`, `PINNED_VERSION_MISMATCH`, and
`PROJECTION_HASH_MISMATCH` retain their stable names. Start with `jyotish run inspect
<rr_id> --json`, verify the event chain and pinned versions, then use offline replay.
Do not paste private inputs into bug reports.
