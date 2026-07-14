# Migration, backup, and recovery

Before opening an older non-empty schema, the store creates a timestamped SQLite
backup with mode `0600`, then applies each migration in one immediate transaction.
The schema version changes only after all DDL and backfills succeed. Keep the data
root at `0700`; database, backups, exports, and adjudication records are `0600`.

For an operator backup, stop writers, use SQLite's backup API (not a raw copy of a
live WAL database), checksum the backup, record schema/app versions, and test-restore
to a separate private data root. Never overwrite the only copy.

Recovery sequence: stop writes; preserve and checksum the failed database/WAL/SHM;
restore the last verified backup into a new `0700` root; start the exact compatible
version; run migrations; inspect affected run IDs; offline-replay them; compare
projection/claims/memo hashes; then switch the configured data root. Missing pinned
corpus or planner versions must be restored before replay.
Each run snapshots the exact approved corpus source-version IDs and manifest
checksums. Later unrelated approvals do not invalidate old runs; removal or checksum
drift of a source pinned by that run fails replay closed.

Validated exports are written by the CLI through `persist_private_artifact`, which
uses a same-directory fsync and atomic replace. Retention deletion must remain inside
the configured private root and must not follow symlinks. Run
`jyotish artifacts prune --retention-seconds <seconds>` (or configure
`JYOTISH_ARTIFACT_RETENTION_SECONDS` for the post-ask sweep); the default is seven
days. Confirm stale Pi mirrors are removed only after SQLite recovery succeeds.

The artifact window is not a ResearchRun deletion policy. The authoritative SQLite
ledger and append-only audit history are intentionally retained indefinitely;
partial run deletion would break replay semantics. To erase local research data,
stop all writers and use the whole-store operation:

```bash
jyotish store backup-and-purge --backup /private/path/research.sqlite3 \
  --confirm PURGE_ALL_RESEARCH_DATA
```

It uses SQLite's backup API, verifies `integrity_check`, writes the backup as `0600`,
and only then removes the database and WAL sidecars. It rejects symlinked configured
roots, existing backup targets, and missing confirmation.

The additive `jaimini`, `prashna`, and `muhurta` MCP tools create no ResearchRun,
schema migration, backup object, or authoritative persistent artifact. Their signing
and capture caches are process-local. Existing backup/recovery procedures are unchanged.
