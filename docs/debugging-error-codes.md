# Debugging and structured errors

Problem responses include `error_code`, `run_id`, `stage`, `retryable`, `problem`,
`cause`, and `fix` in addition to RFC 7807 fields. Logs contain method, path, status,
duration, and non-secret IDs only—never birth profiles, questions, claims, retrieved
text, prompts, tokens, or rendered answers.

| Code | Meaning | Retry |
|---|---|---|
| `SQLITE_BUSY` | bounded ledger lock wait expired | yes, then inspect writers |
| `CORPUS_INTEGRITY_ERROR` | governed fragment bytes/index integrity failed | no; restore backup |
| `MISSING_PINNED_VERSION` | a checksummed engine/planner/corpus/contract dependency is absent or changed | no; restore artifact |
| `MEMO_HASH_MISMATCH` | replayed memo bytes differ from the committed artifact | no; reject artifact |
| `UNEXPECTED_INTERNAL` | privacy-safe unexpected failure | once |
| `INPUT_INVALID` | malformed run-stage operation payload | no; correct payload |

Endpoint-specific codes such as `TIMEZONE_OFFSET_MISMATCH`,
`AMBIGUOUS_LOCAL_TIME`, `NONEXISTENT_LOCAL_TIME`, `PINNED_VERSION_MISMATCH`, and
`PROJECTION_HASH_MISMATCH` retain their stable names. Start with `jyotish run inspect
<rr_id> --json`, verify the event chain and pinned versions, then use offline replay.
Do not paste private inputs into bug reports.

Registry causes are controlled static text. SQLite `busy`/`locked` failures map to
`SQLITE_BUSY`; `CorpusIntegrityError` maps to `CORPUS_INTEGRITY_ERROR`; exception
messages are never copied into public envelopes. Replay returns the real run ID for
the exact `MISSING_PINNED_VERSION` and `MEMO_HASH_MISMATCH` branches.
Run-scoped handlers preserve a known run ID and the requested `screen`, `plan`,
`calculate`, `retrieve`, `answer`, or `replay` stage.
`RUN_NOT_FOUND`, `OPERATION_CONFLICT`, and `UNSUPPORTED_TIMEZONE` use the same
controlled registry envelope; route-local problem builders do not invent codes.
