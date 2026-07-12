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

Retention deletion must remain inside the configured private root and must not
follow symlinks. Use `delete_private_tree`; exports use `atomic_write_private` so a
crash cannot expose a partial artifact. Confirm stale Pi mirrors are removed only
after SQLite recovery succeeds.
