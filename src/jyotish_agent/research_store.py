"""Authoritative SQLite persistence for versioned research runs.

The store owns durability and transaction boundaries only.  Domain normalization
belongs in ``research_service`` and rendering belongs in ``research_memo``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sqlite3
import uuid
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 7
DATABASE_NAME = "research.sqlite3"


class ResearchStoreError(RuntimeError):
    pass


class RunNotFound(ResearchStoreError):
    pass


class OptimisticConflict(ResearchStoreError):
    pass


class EventChainError(ResearchStoreError):
    pass


class SourceConflict(ResearchStoreError):
    pass


class CorpusIntegrityError(ResearchStoreError):
    pass


def canonical_json(value: Any) -> str:
    """Return UTF-8-safe canonical JSON and reject NaN/Infinity."""
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4()}"


def stable_operation_id(seed: str) -> str:
    """Return a deterministic UUID4-shaped ID for idempotent built-in seed actions."""
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]
    return f"op_{uuid.UUID(hex=digest, version=4)}"


def default_data_root() -> Path:
    configured = os.environ.get("JYOTISH_AGENT_DATA_ROOT")
    if configured:
        return Path(configured).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / "jyotish-agent"


def _migration_statements(script: str) -> Iterable[str]:
    """Yield complete SQLite statements so DDL and Python backfill share one txn."""
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                yield statement
            buffer = ""
    if buffer.strip():
        raise ResearchStoreError("migration contains an incomplete SQL statement")


_MIGRATION_1 = """
CREATE TABLE research_runs (
    run_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    status TEXT NOT NULL,
    question TEXT NOT NULL,
    birth_profile_json TEXT NOT NULL,
    calculation_config_json TEXT NOT NULL,
    reference_date TEXT NOT NULL,
    civil_datetime TEXT NOT NULL,
    timezone_resolution_mode TEXT NOT NULL,
    resolved_offset_minutes INTEGER NOT NULL,
    utc_instant TEXT NOT NULL,
    engine_name TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    model_version TEXT NOT NULL,
    planner_version TEXT NOT NULL,
    corpus_version TEXT NOT NULL,
    contract_version TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE operations (
    operation_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    operation_type TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE run_events (
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    seq INTEGER NOT NULL CHECK (seq >= 1),
    event_id TEXT NOT NULL UNIQUE,
    operation_id TEXT REFERENCES operations(operation_id),
    event_type TEXT NOT NULL,
    event_version INTEGER NOT NULL,
    schema_version INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    previous_event_hash TEXT,
    event_hash TEXT NOT NULL,
    producer TEXT NOT NULL,
    producer_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);

CREATE TRIGGER run_events_no_update
BEFORE UPDATE ON run_events BEGIN SELECT RAISE(ABORT, 'run_events are append-only'); END;
CREATE TRIGGER run_events_no_delete
BEFORE DELETE ON run_events BEGIN SELECT RAISE(ABORT, 'run_events are append-only'); END;

CREATE TABLE evidence_items (
    evidence_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    evidence_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE claims (
    claim_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    claim_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE claim_supports (
    claim_id TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL REFERENCES evidence_items(evidence_id) ON DELETE RESTRICT,
    support_type TEXT NOT NULL,
    PRIMARY KEY (claim_id, evidence_id)
);

CREATE TABLE answers (
    answer_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    schema_version TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE source_versions (
    source_version_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source_class TEXT NOT NULL,
    rights_note TEXT NOT NULL,
    checksum TEXT NOT NULL,
    approval_status TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE source_fragments (
    fragment_id TEXT PRIMARY KEY,
    source_version_id TEXT NOT NULL REFERENCES source_versions(source_version_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    locator TEXT NOT NULL,
    text TEXT NOT NULL,
    checksum TEXT NOT NULL,
    UNIQUE (source_version_id, ordinal),
    UNIQUE (source_version_id, locator)
);
"""

_MIGRATION_2 = """
CREATE TRIGGER evidence_items_no_update
BEFORE UPDATE ON evidence_items BEGIN SELECT RAISE(ABORT, 'evidence_items are append-only'); END;
CREATE TRIGGER evidence_items_no_delete
BEFORE DELETE ON evidence_items BEGIN SELECT RAISE(ABORT, 'evidence_items are append-only'); END;
"""

_MIGRATION_3 = """
CREATE TABLE answer_attempts (
    attempt_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL UNIQUE REFERENCES operations(operation_id),
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    attempt_no INTEGER NOT NULL CHECK (attempt_no IN (1, 2)),
    contract_hash TEXT NOT NULL,
    valid INTEGER NOT NULL CHECK (valid IN (0, 1)),
    violations_json TEXT NOT NULL,
    answer_id TEXT REFERENCES answers(answer_id),
    created_at TEXT NOT NULL,
    UNIQUE (run_id, attempt_no)
);

CREATE TRIGGER answers_no_update
BEFORE UPDATE ON answers BEGIN SELECT RAISE(ABORT, 'answers are append-only'); END;
CREATE TRIGGER answers_no_delete
BEFORE DELETE ON answers BEGIN SELECT RAISE(ABORT, 'answers are append-only'); END;
CREATE TRIGGER answer_attempts_no_update
BEFORE UPDATE ON answer_attempts BEGIN SELECT RAISE(ABORT, 'answer_attempts are append-only'); END;
CREATE TRIGGER answer_attempts_no_delete
BEFORE DELETE ON answer_attempts BEGIN SELECT RAISE(ABORT, 'answer_attempts are append-only'); END;
CREATE TRIGGER claims_no_update
BEFORE UPDATE ON claims BEGIN SELECT RAISE(ABORT, 'claims are append-only'); END;
CREATE TRIGGER claims_no_delete
BEFORE DELETE ON claims BEGIN SELECT RAISE(ABORT, 'claims are append-only'); END;
"""

_MIGRATION_4 = """
CREATE TRIGGER claim_supports_no_update
BEFORE UPDATE ON claim_supports BEGIN SELECT RAISE(ABORT, 'claim_supports are append-only'); END;
CREATE TRIGGER claim_supports_no_delete
BEFORE DELETE ON claim_supports BEGIN SELECT RAISE(ABORT, 'claim_supports are append-only'); END;
"""

_MIGRATION_5 = """
ALTER TABLE source_versions ADD COLUMN work_id TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE source_versions ADD COLUMN language TEXT NOT NULL DEFAULT 'und';
ALTER TABLE source_versions ADD COLUMN edition TEXT NOT NULL DEFAULT 'legacy fixture';
ALTER TABLE source_versions ADD COLUMN provenance_url TEXT NOT NULL DEFAULT 'local:test-fixture';
ALTER TABLE source_versions ADD COLUMN manifest_checksum TEXT NOT NULL DEFAULT '';
ALTER TABLE source_versions ADD COLUMN reviewed_by TEXT;
ALTER TABLE source_versions ADD COLUMN review_note TEXT;
ALTER TABLE source_versions ADD COLUMN reviewed_at TEXT;

ALTER TABLE source_fragments ADD COLUMN aliases_text TEXT NOT NULL DEFAULT '';
ALTER TABLE source_fragments ADD COLUMN approval_status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE source_fragments ADD COLUMN reviewed_by TEXT;
ALTER TABLE source_fragments ADD COLUMN review_note TEXT;
ALTER TABLE source_fragments ADD COLUMN reviewed_at TEXT;

CREATE VIRTUAL TABLE source_fragments_fts USING fts5(
    fragment_id UNINDEXED,
    normalized_text,
    aliases_text,
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TABLE question_intents (
    run_id TEXT PRIMARY KEY REFERENCES research_runs(run_id) ON DELETE CASCADE,
    intent_json TEXT NOT NULL,
    intent_hash TEXT NOT NULL,
    classifier_model TEXT NOT NULL,
    classifier_version TEXT NOT NULL,
    classifier_prompt_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE question_plans (
    run_id TEXT PRIMARY KEY REFERENCES research_runs(run_id) ON DELETE CASCADE,
    plan_json TEXT NOT NULL,
    plan_hash TEXT NOT NULL,
    planner_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

_MIGRATION_6 = """
ALTER TABLE source_versions ADD COLUMN revision INTEGER NOT NULL DEFAULT 1;
ALTER TABLE source_versions ADD COLUMN updated_at TEXT;
ALTER TABLE source_versions ADD COLUMN manifest_checksum_original TEXT;
ALTER TABLE source_versions ADD COLUMN manifest_reconciliation_note TEXT;
UPDATE source_versions SET updated_at=created_at WHERE updated_at IS NULL;

ALTER TABLE source_fragments ADD COLUMN revision INTEGER NOT NULL DEFAULT 1;
ALTER TABLE source_fragments ADD COLUMN aliases_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE source_fragments ADD COLUMN created_at TEXT;
ALTER TABLE source_fragments ADD COLUMN updated_at TEXT;
UPDATE source_fragments
SET aliases_json=CASE
    WHEN aliases_text='' THEN '[]'
    ELSE json_array(aliases_text)
END;
UPDATE source_fragments
SET created_at=(SELECT created_at FROM source_versions s
                WHERE s.source_version_id=source_fragments.source_version_id),
    updated_at=(SELECT created_at FROM source_versions s
                WHERE s.source_version_id=source_fragments.source_version_id)
WHERE created_at IS NULL OR updated_at IS NULL;

CREATE TABLE corpus_operations (
    operation_id TEXT PRIMARY KEY,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    operation_type TEXT NOT NULL,
    expected_revision INTEGER NOT NULL CHECK (expected_revision >= 0),
    request_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE corpus_review_history (
    review_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL UNIQUE REFERENCES corpus_operations(operation_id),
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    review_note TEXT NOT NULL,
    reviewed_at TEXT NOT NULL
);

CREATE INDEX corpus_review_history_resource
ON corpus_review_history(resource_type, resource_id, reviewed_at, review_id);

CREATE TRIGGER corpus_operations_no_update
BEFORE UPDATE ON corpus_operations
WHEN OLD.status='completed'
BEGIN SELECT RAISE(ABORT, 'completed corpus_operations are immutable'); END;
CREATE TRIGGER corpus_operations_no_delete
BEFORE DELETE ON corpus_operations
BEGIN SELECT RAISE(ABORT, 'corpus_operations are append-only'); END;
CREATE TRIGGER corpus_review_history_no_update
BEFORE UPDATE ON corpus_review_history
BEGIN SELECT RAISE(ABORT, 'corpus_review_history is append-only'); END;
CREATE TRIGGER corpus_review_history_no_delete
BEFORE DELETE ON corpus_review_history
BEGIN SELECT RAISE(ABORT, 'corpus_review_history is append-only'); END;
"""

_MIGRATION_7 = """
ALTER TABLE research_runs ADD COLUMN timezone_zone_id TEXT;
ALTER TABLE research_runs ADD COLUMN timezone_fingerprint TEXT NOT NULL DEFAULT 'fixed-offset:v1';
ALTER TABLE research_runs ADD COLUMN timezone_fold INTEGER NOT NULL DEFAULT 0 CHECK(timezone_fold IN (0, 1));
ALTER TABLE research_runs ADD COLUMN timezone_warnings_json TEXT NOT NULL DEFAULT 'null';
"""

_MIGRATIONS: dict[int, str] = {
    1: _MIGRATION_1,
    2: _MIGRATION_2,
    3: _MIGRATION_3,
    4: _MIGRATION_4,
    5: _MIGRATION_5,
    6: _MIGRATION_6,
    7: _MIGRATION_7,
}


def _event_envelope(event: Mapping[str, Any]) -> dict[str, Any]:
    """Select exactly the immutable event fields covered by ``event_hash``."""
    return {
        "created_at": event["created_at"],
        "event_id": event["event_id"],
        "event_type": event["event_type"],
        "event_version": event["event_version"],
        "operation_id": event["operation_id"],
        "payload_hash": event["payload_hash"],
        "previous_event_hash": event["previous_event_hash"],
        "producer": event["producer"],
        "producer_version": event["producer_version"],
        "run_id": event["run_id"],
        "schema_version": event["schema_version"],
        "seq": event["seq"],
    }


def _verify_event_chain(events: list[dict[str, Any]]) -> None:
    if not events:
        return
    run_id = events[0]["run_id"]
    previous_hash: str | None = None
    for expected_seq, event in enumerate(events, start=1):
        if event["run_id"] != run_id:
            raise EventChainError("event chain contains another run_id")
        if event["seq"] != expected_seq:
            raise EventChainError("event chain sequence is not contiguous")
        try:
            decoded_payload = json.loads(event["payload_json"])
            canonical_payload = canonical_json(decoded_payload)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise EventChainError("event payload is not canonical JSON") from exc
        if canonical_payload != event["payload_json"]:
            raise EventChainError("event payload JSON is not canonical")
        if sha256_text(event["payload_json"]) != event["payload_hash"]:
            raise EventChainError("event payload hash does not match payload")
        if event["previous_event_hash"] != previous_hash:
            raise EventChainError("event previous hash link is broken")
        expected_hash = sha256_text(canonical_json(_event_envelope(event)))
        if event["event_hash"] != expected_hash:
            raise EventChainError("event hash does not match immutable envelope")
        previous_hash = event["event_hash"]


class ResearchStore:
    def __init__(self, data_root: Path | str | None = None, *, busy_timeout_ms: int = 5_000):
        self.data_root = Path(data_root) if data_root is not None else default_data_root()
        self.database_path = self.data_root / DATABASE_NAME
        self.busy_timeout_ms = busy_timeout_ms

    def initialize(self) -> None:
        self.data_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.data_root, 0o700)
        connection = self._connect()
        try:
            current = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current > SCHEMA_VERSION:
                raise ResearchStoreError(
                    f"database schema {current} is newer than supported {SCHEMA_VERSION}"
                )
            if 0 < current < SCHEMA_VERSION:
                connection.close()
                self._backup_for_migration(current)
                connection = self._connect()
            for target_version in range(current + 1, SCHEMA_VERSION + 1):
                script = _MIGRATIONS.get(target_version)
                if script is None:
                    raise ResearchStoreError(
                        f"missing migration for schema version {target_version}"
                    )
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    for statement in _migration_statements(script):
                        connection.execute(statement)
                    if target_version == 5:
                        self._backfill_v5_fts(connection)
                    if target_version == 6:
                        self._backfill_v6(connection)
                    connection.execute(f"PRAGMA user_version = {target_version}")
                    connection.commit()
                except Exception:
                    if connection.in_transaction:
                        connection.rollback()
                    raise
        finally:
            connection.close()
            if self.database_path.exists():
                os.chmod(self.database_path, 0o600)

    def _backup_for_migration(self, version: int) -> Path:
        stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup = self.database_path.with_name(
            f"{self.database_path.name}.v{version}.{stamp}.bak"
        )
        source = sqlite3.connect(self.database_path)
        destination = sqlite3.connect(backup)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        os.chmod(backup, 0o600)
        return backup

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=self.busy_timeout_ms / 1000)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        return connection

    def _ready_connection(self) -> sqlite3.Connection:
        self.initialize()
        return self._connect()

    def _backfill_v5_fts(self, connection: sqlite3.Connection) -> None:
        """Index every pre-v5 fragment before committing schema version 5."""
        from .corpus import normalize_search_text

        rows = connection.execute(
            "SELECT fragment_id, text, aliases_text FROM source_fragments"
        ).fetchall()
        for row in rows:
            connection.execute(
                """INSERT INTO source_fragments_fts (
                    fragment_id, normalized_text, aliases_text
                ) VALUES (?, ?, ?)""",
                (
                    row["fragment_id"],
                    normalize_search_text(row["text"]),
                    normalize_search_text(row["aliases_text"]),
                ),
            )

    def _backfill_v6(self, connection: sqlite3.Connection) -> None:
        """Reconstruct v5 corpus actions before committing schema version 6."""
        from .corpus import canonical_manifest_checksum, load_builtin_manifest

        builtin = {
            item["source_version_id"]: item
            for item in load_builtin_manifest()["sources"]
        }

        def record_operation(
            *,
            operation_id: str,
            resource_type: str,
            resource_id: str,
            operation_type: str,
            expected_revision: int,
            payload: Mapping[str, Any],
            result: Mapping[str, Any],
            timestamp: str,
        ) -> None:
            request_hash = self._corpus_operation_hash(
                resource_type=resource_type,
                resource_id=resource_id,
                operation_type=operation_type,
                expected_revision=expected_revision,
                payload=payload,
            )
            connection.execute(
                """INSERT INTO corpus_operations (
                    operation_id, resource_type, resource_id, operation_type,
                    expected_revision, request_hash, status, result_json,
                    created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'completed', ?, ?, ?)""",
                (
                    operation_id, resource_type, resource_id, operation_type,
                    expected_revision, request_hash, canonical_json(result),
                    timestamp, timestamp,
                ),
            )

        def review_id(seed: str) -> str:
            return "cr_" + stable_operation_id(seed)[3:]

        source_rows = connection.execute(
            "SELECT * FROM source_versions ORDER BY source_version_id"
        ).fetchall()
        for initial_source in source_rows:
            source_id = initial_source["source_version_id"]
            old_checksum = initial_source["manifest_checksum"]
            initial_fragments = connection.execute(
                """SELECT * FROM source_fragments WHERE source_version_id=?
                   ORDER BY ordinal, fragment_id""",
                (source_id,),
            ).fetchall()
            manifest_entry = builtin.get(source_id)
            is_builtin = bool(
                manifest_entry
                and old_checksum == manifest_entry["manifest_checksum"]
                and [row["fragment_id"] for row in initial_fragments]
                == [item["fragment_id"] for item in manifest_entry["fragments"]]
            )
            if is_builtin and manifest_entry is not None:
                aliases_by_id = {
                    item["fragment_id"]: item["transliteration_aliases"]
                    for item in manifest_entry["fragments"]
                }
                for fragment_id, aliases in aliases_by_id.items():
                    connection.execute(
                        "UPDATE source_fragments SET aliases_json=? WHERE fragment_id=?",
                        (canonical_json(aliases), fragment_id),
                    )

            source_status = initial_source["approval_status"]
            source_revision = 1 + int(bool(initial_fragments)) + int(
                source_status != "pending"
            )
            source_updated_at = initial_source["reviewed_at"] or initial_source["created_at"]
            source_reviewer = initial_source["reviewed_by"]
            source_review_note = initial_source["review_note"]
            if source_status != "pending":
                source_reviewer = source_reviewer or "unknown-v5-reviewer"
                source_review_note = source_review_note or "Migrated v5 review decision."
            for fragment in initial_fragments:
                fragment_revision = 1 + int(fragment["approval_status"] != "pending")
                fragment_reviewer = fragment["reviewed_by"]
                fragment_review_note = fragment["review_note"]
                if fragment["approval_status"] != "pending":
                    fragment_reviewer = fragment_reviewer or "unknown-v5-reviewer"
                    fragment_review_note = (
                        fragment_review_note or "Migrated v5 review decision."
                    )
                connection.execute(
                    """UPDATE source_fragments
                       SET revision=?, created_at=?, updated_at=?,
                           reviewed_by=?, review_note=?
                       WHERE fragment_id=?""",
                    (
                        fragment_revision,
                        initial_source["created_at"],
                        fragment["reviewed_at"] or initial_source["created_at"],
                        fragment_reviewer,
                        fragment_review_note,
                        fragment["fragment_id"],
                    ),
                )

            migrated_fragments = [
                self._fragment_projection(row)
                for row in connection.execute(
                    """SELECT * FROM source_fragments WHERE source_version_id=?
                       ORDER BY ordinal, fragment_id""",
                    (source_id,),
                ).fetchall()
            ]
            actual_checksum = canonical_manifest_checksum(
                dict(initial_source), migrated_fragments
            )
            is_builtin = bool(
                is_builtin
                and manifest_entry is not None
                and actual_checksum == manifest_entry["manifest_checksum"]
            )
            reconciliation_note = None
            if actual_checksum != old_checksum:
                reconciliation_note = (
                    "Migrated from v5: aliases_text is preserved as one alias because "
                    "the original alias-list boundaries are unrecoverable; the canonical "
                    "manifest checksum was recomputed for explicit review."
                )
            connection.execute(
                """UPDATE source_versions
                   SET revision=?, updated_at=?, manifest_checksum_original=?,
                       manifest_checksum=?, checksum=?, manifest_reconciliation_note=?,
                       reviewed_by=?, review_note=?
                   WHERE source_version_id=?""",
                (
                    source_revision, source_updated_at, old_checksum, actual_checksum,
                    actual_checksum, reconciliation_note, source_reviewer,
                    source_review_note, source_id,
                ),
            )
            source = connection.execute(
                "SELECT * FROM source_versions WHERE source_version_id=?", (source_id,)
            ).fetchone()
            fragments = [
                self._fragment_projection(row)
                for row in connection.execute(
                    """SELECT * FROM source_fragments WHERE source_version_id=?
                       ORDER BY ordinal, fragment_id""",
                    (source_id,),
                ).fetchall()
            ]

            if is_builtin and manifest_entry is not None:
                source_payload = {
                    key: value
                    for key, value in manifest_entry.items()
                    if key not in {"fragments", "review"}
                }
                create_op = stable_operation_id(f"builtin:{source_id}:source")
                pending_source = self._source_projection(source)
                pending_source.update(
                    {
                        "approval_status": "pending",
                        "revision": 1,
                        "reviewed_by": None,
                        "review_note": None,
                        "reviewed_at": None,
                        "updated_at": source["created_at"],
                        "manifest_checksum_original": None,
                        "manifest_reconciliation_note": None,
                    }
                )
                record_operation(
                    operation_id=create_op,
                    resource_type="source_version",
                    resource_id=source_id,
                    operation_type="corpus.source_version.ingest",
                    expected_revision=0,
                    payload=source_payload,
                    result={"operation_id": create_op, **pending_source},
                    timestamp=source["created_at"],
                )
                if manifest_entry["fragments"]:
                    fragment_op = stable_operation_id(f"builtin:{source_id}:fragments")
                    pending_fragments = []
                    for fragment in fragments:
                        pending = dict(fragment)
                        pending.update(
                            {
                                "approval_status": "pending",
                                "revision": 1,
                                "reviewed_by": None,
                                "review_note": None,
                                "reviewed_at": None,
                                "updated_at": fragment["created_at"],
                            }
                        )
                        pending_fragments.append(pending)
                    record_operation(
                        operation_id=fragment_op,
                        resource_type="source_version",
                        resource_id=source_id,
                        operation_type="corpus.source_fragments.ingest",
                        expected_revision=1,
                        payload={"fragments": manifest_entry["fragments"]},
                        result={
                            "operation_id": fragment_op,
                            "source_version_id": source_id,
                            "revision": 2,
                            "fragments": pending_fragments,
                        },
                        timestamp=source["created_at"],
                    )
                review = manifest_entry["review"]
                if source_status != "pending":
                    reviewer = source["reviewed_by"] or "unknown-v5-reviewer"
                    note = source["review_note"] or "Migrated v5 review decision."
                    is_seed_review = (
                        source_status == review["status"]
                        and reviewer == review["reviewer"]
                        and note == review["note"]
                    )
                    source_review_seed = (
                        f"builtin:{source_id}:source-review"
                        if is_seed_review
                        else f"migrated-v5:{source_id}:source-review"
                    )
                    source_review_op = stable_operation_id(source_review_seed)
                    source_review_payload = {
                        "status": source_status,
                        "reviewer": reviewer,
                        "note": note,
                    }
                    record_operation(
                        operation_id=source_review_op,
                        resource_type="source_version",
                        resource_id=source_id,
                        operation_type=(
                            "corpus.review"
                            if is_seed_review
                            else "corpus.migrated_v5.review"
                        ),
                        expected_revision=source_revision - 1,
                        payload=source_review_payload,
                        result={
                            "operation_id": source_review_op,
                            **self._source_projection(source),
                        },
                        timestamp=source["reviewed_at"] or source["created_at"],
                    )
                    connection.execute(
                        """INSERT INTO corpus_review_history (
                            review_id, operation_id, resource_type, resource_id,
                            from_status, to_status, reviewer, review_note, reviewed_at
                        ) VALUES (?, ?, 'source_version', ?, 'pending', ?, ?, ?, ?)""",
                        (
                            review_id(source_review_seed), source_review_op, source_id,
                            source_status, reviewer, note,
                            source["reviewed_at"] or source["created_at"],
                        ),
                    )
                for fragment in fragments:
                    fragment_status = fragment["approval_status"]
                    if fragment_status == "pending":
                        continue
                    reviewer = fragment["reviewed_by"] or "unknown-v5-reviewer"
                    note = fragment["review_note"] or "Migrated v5 review decision."
                    is_seed_review = (
                        fragment_status == review["status"]
                        and reviewer == review["reviewer"]
                        and note == review["note"]
                    )
                    fragment_review_seed = (
                        f"builtin:{fragment['fragment_id']}:fragment-review"
                        if is_seed_review
                        else f"migrated-v5:{fragment['fragment_id']}:fragment-review"
                    )
                    fragment_op = stable_operation_id(fragment_review_seed)
                    record_operation(
                        operation_id=fragment_op,
                        resource_type="source_fragment",
                        resource_id=fragment["fragment_id"],
                        operation_type=(
                            "corpus.review"
                            if is_seed_review
                            else "corpus.migrated_v5.review"
                        ),
                        expected_revision=1,
                        payload={
                            "status": fragment_status,
                            "reviewer": reviewer,
                            "note": note,
                        },
                        result={"operation_id": fragment_op, **fragment},
                        timestamp=fragment["reviewed_at"] or fragment["created_at"],
                    )
                    connection.execute(
                        """INSERT INTO corpus_review_history (
                            review_id, operation_id, resource_type, resource_id,
                            from_status, to_status, reviewer, review_note, reviewed_at
                        ) VALUES (?, ?, 'source_fragment', ?, 'pending', ?, ?, ?, ?)""",
                        (
                            review_id(fragment_review_seed),
                            fragment_op, fragment["fragment_id"],
                            fragment_status, reviewer, note,
                            fragment["reviewed_at"] or fragment["created_at"],
                        ),
                    )
                continue

            # Legacy non-builtin calls had no operation IDs. Preserve each inferred
            # action as an explicit migrated snapshot rather than pretending it can replay.
            create_op = stable_operation_id(f"migrated-v5:{source_id}:source")
            record_operation(
                operation_id=create_op,
                resource_type="source_version",
                resource_id=source_id,
                operation_type="corpus.migrated_v5.source",
                expected_revision=0,
                payload={"legacy_schema": 5},
                result={"operation_id": create_op, **self._source_projection(source)},
                timestamp=source["created_at"],
            )
            if fragments:
                fragment_op = stable_operation_id(f"migrated-v5:{source_id}:fragments")
                record_operation(
                    operation_id=fragment_op,
                    resource_type="source_version",
                    resource_id=source_id,
                    operation_type="corpus.migrated_v5.fragments",
                    expected_revision=1,
                    payload={"legacy_schema": 5, "fragment_count": len(fragments)},
                    result={
                        "operation_id": fragment_op,
                        "source_version_id": source_id,
                        "revision": 2,
                        "fragments": fragments,
                    },
                    timestamp=source["created_at"],
                )
            if source_status != "pending":
                source_review_op = stable_operation_id(
                    f"migrated-v5:{source_id}:source-review"
                )
                record_operation(
                    operation_id=source_review_op,
                    resource_type="source_version",
                    resource_id=source_id,
                    operation_type="corpus.migrated_v5.review",
                    expected_revision=source_revision - 1,
                    payload={"legacy_schema": 5, "status": source_status},
                    result={
                        "operation_id": source_review_op,
                        **self._source_projection(source),
                    },
                    timestamp=source["reviewed_at"] or source["created_at"],
                )
                connection.execute(
                    """INSERT INTO corpus_review_history (
                        review_id, operation_id, resource_type, resource_id,
                        from_status, to_status, reviewer, review_note, reviewed_at
                    ) VALUES (?, ?, 'source_version', ?, 'pending', ?, ?, ?, ?)""",
                    (
                        review_id(f"migrated-v5:{source_id}:source-review"),
                        source_review_op, source_id, source_status,
                        source["reviewed_by"] or "unknown-v5-reviewer",
                        source["review_note"] or "Migrated v5 review decision.",
                        source["reviewed_at"] or source["created_at"],
                    ),
                )
            for fragment in fragments:
                if fragment["approval_status"] == "pending":
                    continue
                fragment_op = stable_operation_id(
                    f"migrated-v5:{fragment['fragment_id']}:fragment-review"
                )
                record_operation(
                    operation_id=fragment_op,
                    resource_type="source_fragment",
                    resource_id=fragment["fragment_id"],
                    operation_type="corpus.migrated_v5.review",
                    expected_revision=1,
                    payload={
                        "legacy_schema": 5,
                        "status": fragment["approval_status"],
                    },
                    result={"operation_id": fragment_op, **fragment},
                    timestamp=fragment["reviewed_at"] or fragment["created_at"],
                )
                connection.execute(
                    """INSERT INTO corpus_review_history (
                        review_id, operation_id, resource_type, resource_id,
                        from_status, to_status, reviewer, review_note, reviewed_at
                    ) VALUES (?, ?, 'source_fragment', ?, 'pending', ?, ?, ?, ?)""",
                    (
                        review_id(
                            f"migrated-v5:{fragment['fragment_id']}:fragment-review"
                        ),
                        fragment_op, fragment["fragment_id"],
                        fragment["approval_status"],
                        fragment["reviewed_by"] or "unknown-v5-reviewer",
                        fragment["review_note"] or "Migrated v5 review decision.",
                        fragment["reviewed_at"] or fragment["created_at"],
                    ),
                )

    def create_run(
        self,
        run: Mapping[str, Any],
        *,
        operation_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        if expected_revision != 0:
            raise OptimisticConflict("new research runs require expected_revision=0")
        run_data = dict(run)
        request_hash = str(run_data["request_hash"])
        connection = self._ready_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing_operation = connection.execute(
                "SELECT request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing_operation is not None:
                if existing_operation["request_hash"] != request_hash:
                    raise OptimisticConflict("operation_id was already used with another request")
                connection.commit()
                return json.loads(existing_operation["result_json"])

            existing_run = connection.execute(
                "SELECT 1 FROM research_runs WHERE run_id = ?",
                (run_data["run_id"],),
            ).fetchone()
            if existing_run is not None:
                raise OptimisticConflict("run_id was already created by another operation")

            connection.execute(
                """INSERT INTO research_runs (
                    run_id, revision, status, question, birth_profile_json,
                    calculation_config_json, reference_date, civil_datetime,
                    timezone_resolution_mode, resolved_offset_minutes, utc_instant,
                    timezone_zone_id, timezone_fingerprint, timezone_fold, timezone_warnings_json,
                    engine_name, engine_version, model_version, planner_version,
                    corpus_version, contract_version, request_hash, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                self._run_values(run_data),
            )
            connection.execute(
                """INSERT INTO operations (
                    operation_id, run_id, operation_type, request_hash, status, created_at
                ) VALUES (?, ?, 'research_run.create', ?, 'pending', ?)""",
                (operation_id, run_data["run_id"], request_hash, run_data["created_at"]),
            )
            self._insert_event(
                connection,
                run_id=run_data["run_id"],
                seq=1,
                operation_id=operation_id,
                event_type="research_run.created",
                payload={"run": run_data},
                producer="jyotish-agent",
                producer_version=run_data["engine_version"],
                created_at=run_data["created_at"],
                previous_event_hash=None,
            )
            result_json = canonical_json(run_data)
            connection.execute(
                """UPDATE operations SET status='completed', result_json=?, completed_at=?
                   WHERE operation_id=?""",
                (result_json, run_data["updated_at"], operation_id),
            )
            connection.commit()
            return run_data
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _run_values(run: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            run["run_id"], run["revision"], run["status"], run["question"],
            canonical_json(run["birth_profile"]),
            canonical_json(run["calculation_config"]), run["reference_date"],
            run["civil_datetime"], run["timezone_resolution_mode"],
            run["resolved_offset_minutes"], run["utc_instant"],
            run.get("timezone_zone_id"), run.get("timezone_fingerprint", "fixed-offset:v1"),
            run.get("timezone_fold", 0), canonical_json(run.get("timezone_warnings")),
            run["engine_name"], run["engine_version"], run["model_version"], run["planner_version"],
            run["corpus_version"], run["contract_version"], run["request_hash"],
            run["created_at"], run["updated_at"],
        )

    def append_event(
        self,
        run_id: str,
        *,
        operation_id: str,
        expected_revision: int,
        event_type: str,
        payload: Mapping[str, Any],
        producer: str,
        producer_version: str,
        request_payload: Mapping[str, Any] | None = None,
        next_status: str | None = None,
        evidence_items: Iterable[Mapping[str, Any]] = (),
        answer_attempt: Mapping[str, Any] | None = None,
        answer_record: Mapping[str, Any] | None = None,
        claim_records: Iterable[Mapping[str, Any]] = (),
        claim_supports: Iterable[Mapping[str, str]] = (),
        planning_record: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], int]:
        payload_json = canonical_json(payload)
        semantic_payload = (
            json.loads(payload_json)
            if request_payload is None
            else json.loads(canonical_json(request_payload))
        )
        request_hash = self._operation_request_hash(
            run_id=run_id,
            expected_revision=expected_revision,
            event_type=event_type,
            payload=semantic_payload,
            producer=producer,
            producer_version=producer_version,
        )
        evidence_rows = [dict(item) for item in evidence_items]
        claims = [dict(item) for item in claim_records]
        supports = [dict(item) for item in claim_supports]
        connection = self._ready_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT request_hash, result_json FROM operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise OptimisticConflict("operation_id was already used with another request")
                result = json.loads(existing["result_json"])
                connection.commit()
                return result["event"], result["revision"]

            row = connection.execute(
                "SELECT revision, status, updated_at FROM research_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if row is None:
                raise RunNotFound(run_id)
            if row["revision"] != expected_revision:
                raise OptimisticConflict(
                    f"expected revision {expected_revision} does not match current revision"
                )
            previous = connection.execute(
                "SELECT seq, event_hash FROM run_events WHERE run_id=? ORDER BY seq DESC LIMIT 1",
                (run_id,),
            ).fetchone()
            now = dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")
            connection.execute(
                """INSERT INTO operations
                   (operation_id, run_id, operation_type, request_hash, status, created_at)
                   VALUES (?, ?, ?, ?, 'pending', ?)""",
                (operation_id, run_id, event_type, request_hash, now),
            )
            event = self._insert_event(
                connection,
                run_id=run_id,
                seq=previous["seq"] + 1,
                operation_id=operation_id,
                event_type=event_type,
                payload=json.loads(payload_json),
                producer=producer,
                producer_version=producer_version,
                created_at=now,
                previous_event_hash=previous["event_hash"],
            )
            for item in evidence_rows:
                evidence_payload = canonical_json(item["payload"])
                connection.execute(
                    """INSERT INTO evidence_items (
                        evidence_id, run_id, evidence_type, payload_json,
                        payload_hash, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        item["evidence_id"],
                        run_id,
                        item["evidence_type"],
                        evidence_payload,
                        sha256_text(evidence_payload),
                        now,
                    ),
                )
            if answer_record is not None:
                answer_payload = canonical_json(answer_record["payload"])
                connection.execute(
                    """INSERT INTO answers (
                        answer_id, run_id, schema_version, payload_json,
                        payload_hash, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        answer_record["answer_id"],
                        run_id,
                        answer_record["schema_version"],
                        answer_payload,
                        sha256_text(answer_payload),
                        now,
                    ),
                )
                for claim in claims:
                    claim_payload = canonical_json(claim["payload"])
                    connection.execute(
                        """INSERT INTO claims (
                            claim_id, run_id, claim_type, payload_json,
                            payload_hash, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            claim["claim_id"],
                            run_id,
                            claim["claim_type"],
                            claim_payload,
                            sha256_text(claim_payload),
                            now,
                        ),
                    )
                for support in supports:
                    connection.execute(
                        """INSERT INTO claim_supports (
                            claim_id, evidence_id, support_type
                        ) VALUES (?, ?, ?)""",
                        (
                            support["claim_id"],
                            support["evidence_id"],
                            support["support_type"],
                        ),
                    )
            if answer_attempt is not None:
                connection.execute(
                    """INSERT INTO answer_attempts (
                        attempt_id, operation_id, run_id, attempt_no,
                        contract_hash, valid, violations_json, answer_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        answer_attempt["attempt_id"],
                        operation_id,
                        run_id,
                        answer_attempt["attempt_no"],
                        answer_attempt["contract_hash"],
                        int(answer_attempt["valid"]),
                        canonical_json(answer_attempt["violations"]),
                        answer_attempt.get("answer_id"),
                        now,
                    ),
                )
            if planning_record is not None:
                intent_json = canonical_json(planning_record["intent"])
                plan_json = canonical_json(planning_record["plan"])
                connection.execute(
                    """INSERT INTO question_intents (
                        run_id, intent_json, intent_hash, classifier_model,
                        classifier_version, classifier_prompt_hash, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_id,
                        intent_json,
                        sha256_text(intent_json),
                        planning_record["classifier_model"],
                        planning_record["classifier_version"],
                        planning_record["classifier_prompt_hash"],
                        now,
                    ),
                )
                connection.execute(
                    """INSERT INTO question_plans (
                        run_id, plan_json, plan_hash, planner_version, created_at
                    ) VALUES (?, ?, ?, ?, ?)""",
                    (
                        run_id,
                        plan_json,
                        planning_record["plan_hash"],
                        planning_record["planner_version"],
                        now,
                    ),
                )
            next_revision = expected_revision + 1
            changed = connection.execute(
                """UPDATE research_runs SET revision=?, status=?, updated_at=?
                   WHERE run_id=? AND revision=?""",
                (next_revision, next_status or row["status"], now, run_id, expected_revision),
            ).rowcount
            if changed != 1:
                raise OptimisticConflict("research run changed concurrently")
            result = {"event": event, "revision": next_revision}
            connection.execute(
                """UPDATE operations SET status='completed', result_json=?, completed_at=?
                   WHERE operation_id=?""",
                (canonical_json(result), now, operation_id),
            )
            connection.commit()
            return event, next_revision
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _operation_request_hash(
        *,
        run_id: str,
        expected_revision: int,
        event_type: str,
        payload: Mapping[str, Any],
        producer: str,
        producer_version: str,
    ) -> str:
        return sha256_text(
            canonical_json(
                {
                    "run_id": run_id,
                    "expected_revision": expected_revision,
                    "event_type": event_type,
                    "payload": payload,
                    "producer": producer,
                    "producer_version": producer_version,
                }
            )
        )

    def get_operation_result(
        self,
        *,
        operation_id: str,
        run_id: str,
        expected_revision: int,
        event_type: str,
        request_payload: Mapping[str, Any],
        producer: str,
        producer_version: str,
    ) -> tuple[dict[str, Any], int] | None:
        """Return an exact prior result, or reject reuse with changed semantics."""
        request_hash = self._operation_request_hash(
            run_id=run_id,
            expected_revision=expected_revision,
            event_type=event_type,
            payload=json.loads(canonical_json(request_payload)),
            producer=producer,
            producer_version=producer_version,
        )
        connection = self._ready_connection()
        try:
            row = connection.execute(
                "SELECT request_hash, status, result_json FROM operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if row is None:
                return None
            if row["request_hash"] != request_hash:
                raise OptimisticConflict("operation_id was already used with another request")
            if row["status"] != "completed" or row["result_json"] is None:
                raise OptimisticConflict("operation is not complete and requires reconciliation")
            result = json.loads(row["result_json"])
            return result["event"], result["revision"]
        finally:
            connection.close()

    def _insert_event(
        self,
        connection: sqlite3.Connection,
        *,
        run_id: str,
        seq: int,
        operation_id: str | None,
        event_type: str,
        payload: Mapping[str, Any],
        producer: str,
        producer_version: str,
        created_at: str,
        previous_event_hash: str | None,
    ) -> dict[str, Any]:
        event_id = new_id("ev_")
        payload_json = canonical_json(payload)
        payload_hash = sha256_text(payload_json)
        envelope = _event_envelope({
            "created_at": created_at,
            "event_id": event_id,
            "event_type": event_type,
            "event_version": 1,
            "operation_id": operation_id,
            "payload_hash": payload_hash,
            "previous_event_hash": previous_event_hash,
            "producer": producer,
            "producer_version": producer_version,
            "run_id": run_id,
            "schema_version": 1,
            "seq": seq,
        })
        event_hash = sha256_text(canonical_json(envelope))
        connection.execute(
            """INSERT INTO run_events (
                run_id, seq, event_id, operation_id, event_type, event_version,
                schema_version, payload_json, payload_hash, previous_event_hash,
                event_hash, producer, producer_version, created_at
            ) VALUES (?, ?, ?, ?, ?, 1, 1, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id, seq, event_id, operation_id, event_type, payload_json,
                payload_hash, previous_event_hash, event_hash, producer,
                producer_version, created_at,
            ),
        )
        return {**envelope, "payload_json": payload_json, "event_hash": event_hash}

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        connection = self._ready_connection()
        try:
            row = connection.execute(
                "SELECT * FROM research_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            return self._decode_run(row) if row is not None else None
        finally:
            connection.close()

    @staticmethod
    def _decode_run(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["birth_profile"] = json.loads(data.pop("birth_profile_json"))
        data["calculation_config"] = json.loads(data.pop("calculation_config_json"))
        warnings = json.loads(data.pop("timezone_warnings_json"))
        if warnings is None:
            data.pop("timezone_zone_id", None)
            data.pop("timezone_fingerprint", None)
            data.pop("timezone_fold", None)
        else:
            data["timezone_warnings"] = warnings
        return data

    def list_events(self, run_id: str) -> list[dict[str, Any]]:
        connection = self._ready_connection()
        try:
            rows = connection.execute(
                "SELECT * FROM run_events WHERE run_id=? ORDER BY seq", (run_id,)
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def list_evidence(self, run_id: str) -> list[dict[str, Any]]:
        connection = self._ready_connection()
        try:
            rows = connection.execute(
                "SELECT * FROM evidence_items WHERE run_id=? ORDER BY created_at, evidence_id",
                (run_id,),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["payload"] = json.loads(item.pop("payload_json"))
                result.append(item)
            return result
        finally:
            connection.close()

    def list_answers(self, run_id: str) -> list[dict[str, Any]]:
        connection = self._ready_connection()
        try:
            rows = connection.execute(
                "SELECT * FROM answers WHERE run_id=? ORDER BY created_at, answer_id",
                (run_id,),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["payload"] = json.loads(item.pop("payload_json"))
                result.append(item)
            return result
        finally:
            connection.close()

    def list_claims(self, run_id: str) -> list[dict[str, Any]]:
        connection = self._ready_connection()
        try:
            rows = connection.execute(
                "SELECT * FROM claims WHERE run_id=? ORDER BY created_at, claim_id",
                (run_id,),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["payload"] = json.loads(item.pop("payload_json"))
                result.append(item)
            return result
        finally:
            connection.close()

    def list_claim_supports(self, run_id: str) -> list[dict[str, Any]]:
        connection = self._ready_connection()
        try:
            rows = connection.execute(
                """SELECT s.claim_id, s.evidence_id, s.support_type
                   FROM claim_supports s JOIN claims c ON c.claim_id=s.claim_id
                   WHERE c.run_id=? ORDER BY s.claim_id, s.evidence_id""",
                (run_id,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def list_answer_attempts(self, run_id: str) -> list[dict[str, Any]]:
        connection = self._ready_connection()
        try:
            rows = connection.execute(
                """SELECT * FROM answer_attempts
                   WHERE run_id=? ORDER BY attempt_no""",
                (run_id,),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["valid"] = bool(item["valid"])
                item["violations"] = json.loads(item.pop("violations_json"))
                result.append(item)
            return result
        finally:
            connection.close()

    def get_question_intent(self, run_id: str) -> dict[str, Any] | None:
        connection = self._ready_connection()
        try:
            row = connection.execute(
                "SELECT * FROM question_intents WHERE run_id=?", (run_id,)
            ).fetchone()
            if row is None:
                return None
            item = dict(row)
            item["intent"] = json.loads(item.pop("intent_json"))
            return item
        finally:
            connection.close()

    def get_question_plan(self, run_id: str) -> dict[str, Any] | None:
        connection = self._ready_connection()
        try:
            row = connection.execute(
                "SELECT * FROM question_plans WHERE run_id=?", (run_id,)
            ).fetchone()
            if row is None:
                return None
            item = dict(row)
            item["plan"] = json.loads(item.pop("plan_json"))
            return item
        finally:
            connection.close()

    @staticmethod
    def _corpus_operation_hash(
        *,
        resource_type: str,
        resource_id: str,
        operation_type: str,
        expected_revision: int,
        payload: Mapping[str, Any],
    ) -> str:
        return sha256_text(
            canonical_json(
                {
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "operation_type": operation_type,
                    "expected_revision": expected_revision,
                    "payload": payload,
                }
            )
        )

    @staticmethod
    def _replay_corpus_operation(
        connection: sqlite3.Connection, operation_id: str, request_hash: str
    ) -> dict[str, Any] | None:
        row = connection.execute(
            "SELECT request_hash, status, result_json FROM corpus_operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        if row is None:
            return None
        if row["request_hash"] != request_hash:
            raise OptimisticConflict("operation_id was already used with another corpus request")
        if row["status"] != "completed" or row["result_json"] is None:
            raise OptimisticConflict("corpus operation is incomplete and requires reconciliation")
        return json.loads(row["result_json"])

    @staticmethod
    def _begin_corpus_operation(
        connection: sqlite3.Connection,
        *,
        operation_id: str,
        resource_type: str,
        resource_id: str,
        operation_type: str,
        expected_revision: int,
        request_hash: str,
        now: str,
    ) -> None:
        connection.execute(
            """INSERT INTO corpus_operations (
                operation_id, resource_type, resource_id, operation_type,
                expected_revision, request_hash, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (
                operation_id, resource_type, resource_id, operation_type,
                expected_revision, request_hash, now,
            ),
        )

    @staticmethod
    def _complete_corpus_operation(
        connection: sqlite3.Connection,
        operation_id: str,
        result: Mapping[str, Any],
        now: str,
    ) -> None:
        connection.execute(
            """UPDATE corpus_operations
               SET status='completed', result_json=?, completed_at=?
               WHERE operation_id=? AND status='pending'""",
            (canonical_json(result), now, operation_id),
        )

    @staticmethod
    def _source_projection(row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: row[key]
            for key in (
                "source_version_id", "work_id", "title", "source_class", "language",
                "edition", "provenance_url", "rights_note", "manifest_checksum",
                "manifest_checksum_original", "manifest_reconciliation_note",
                "approval_status", "revision", "reviewed_by", "review_note",
                "reviewed_at", "created_at", "updated_at",
            )
        }

    @staticmethod
    def _fragment_projection(row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "fragment_id": row["fragment_id"],
            "source_version_id": row["source_version_id"],
            "ordinal": row["ordinal"],
            "locator": row["locator"],
            "text": row["text"],
            "transliteration_aliases": json.loads(row["aliases_json"]),
            "checksum": row["checksum"],
            "approval_status": row["approval_status"],
            "revision": row["revision"],
            "reviewed_by": row["reviewed_by"],
            "review_note": row["review_note"],
            "reviewed_at": row["reviewed_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def ingest_source_version(
        self,
        source: Mapping[str, Any],
        *,
        operation_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        """Create a pending immutable source aggregate at revision one."""
        source_data = dict(source)
        resource_id = source_data["source_version_id"]
        request_hash = self._corpus_operation_hash(
            resource_type="source_version",
            resource_id=resource_id,
            operation_type="corpus.source_version.ingest",
            expected_revision=expected_revision,
            payload=source_data,
        )
        now = dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")
        metadata = {
            key: source_data[key]
            for key in ("work_id", "language", "edition", "provenance_url")
        }
        connection = self._ready_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._replay_corpus_operation(connection, operation_id, request_hash)
            if replay is not None:
                connection.commit()
                return replay
            if expected_revision != 0:
                raise OptimisticConflict("new source versions require expected_revision=0")
            if connection.execute(
                "SELECT 1 FROM source_versions WHERE source_version_id=?", (resource_id,)
            ).fetchone() is not None:
                raise OptimisticConflict("source version already exists")
            self._begin_corpus_operation(
                connection,
                operation_id=operation_id,
                resource_type="source_version",
                resource_id=resource_id,
                operation_type="corpus.source_version.ingest",
                expected_revision=expected_revision,
                request_hash=request_hash,
                now=now,
            )
            connection.execute(
                """INSERT INTO source_versions (
                    source_version_id, title, source_class, rights_note, checksum,
                    approval_status, metadata_json, created_at, work_id, language,
                    edition, provenance_url, manifest_checksum, revision, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                (
                    resource_id, source_data["title"], source_data["source_class"],
                    source_data["rights_note"], source_data["manifest_checksum"],
                    canonical_json(metadata), now, source_data["work_id"],
                    source_data["language"], source_data["edition"],
                    source_data["provenance_url"], source_data["manifest_checksum"], now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM source_versions WHERE source_version_id=?", (resource_id,)
            ).fetchone()
            result = {"operation_id": operation_id, **self._source_projection(row)}
            self._complete_corpus_operation(connection, operation_id, result, now)
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def ingest_source_fragments(
        self,
        source_version_id: str,
        fragments: Iterable[Mapping[str, Any]],
        *,
        operation_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        from .corpus import normalize_search_text

        rows = [dict(fragment) for fragment in fragments]
        request_payload = {"fragments": rows}
        request_hash = self._corpus_operation_hash(
            resource_type="source_version",
            resource_id=source_version_id,
            operation_type="corpus.source_fragments.ingest",
            expected_revision=expected_revision,
            payload=request_payload,
        )
        now = dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")
        connection = self._ready_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._replay_corpus_operation(connection, operation_id, request_hash)
            if replay is not None:
                connection.commit()
                return replay
            source = connection.execute(
                "SELECT * FROM source_versions WHERE source_version_id=?",
                (source_version_id,),
            ).fetchone()
            if source is None:
                raise SourceConflict("source version does not exist")
            if source["revision"] != expected_revision:
                raise OptimisticConflict("source version revision is stale")
            if source["approval_status"] != "pending":
                raise SourceConflict("reviewed source versions are immutable; create a new version")
            self._begin_corpus_operation(
                connection,
                operation_id=operation_id,
                resource_type="source_version",
                resource_id=source_version_id,
                operation_type="corpus.source_fragments.ingest",
                expected_revision=expected_revision,
                request_hash=request_hash,
                now=now,
            )
            for fragment in rows:
                if sha256_text(fragment["text"]) != fragment["checksum"]:
                    raise SourceConflict("fragment checksum does not match exact text")
                aliases_list = fragment.get("transliteration_aliases", [])
                aliases = " ".join(aliases_list)
                connection.execute(
                    """INSERT INTO source_fragments (
                        fragment_id, source_version_id, ordinal, locator, text,
                        checksum, aliases_text, aliases_json, approval_status,
                        revision, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 1, ?, ?)""",
                    (
                        fragment["fragment_id"], source_version_id, fragment["ordinal"],
                        fragment["locator"], fragment["text"], fragment["checksum"],
                        aliases, canonical_json(aliases_list), now, now,
                    ),
                )
                connection.execute(
                    """INSERT INTO source_fragments_fts (
                        fragment_id, normalized_text, aliases_text
                    ) VALUES (?, ?, ?)""",
                    (
                        fragment["fragment_id"], normalize_search_text(fragment["text"]),
                        normalize_search_text(aliases),
                    ),
                )
            next_revision = expected_revision + 1
            connection.execute(
                """UPDATE source_versions SET revision=?, updated_at=?
                   WHERE source_version_id=? AND revision=?""",
                (next_revision, now, source_version_id, expected_revision),
            )
            stored = connection.execute(
                """SELECT * FROM source_fragments WHERE source_version_id=?
                   AND fragment_id IN ({}) ORDER BY ordinal, fragment_id""".format(
                    ",".join("?" for _ in rows)
                ),
                (source_version_id, *(item["fragment_id"] for item in rows)),
            ).fetchall()
            result = {
                "operation_id": operation_id,
                "source_version_id": source_version_id,
                "revision": next_revision,
                "fragments": [self._fragment_projection(row) for row in stored],
            }
            self._complete_corpus_operation(connection, operation_id, result, now)
            connection.commit()
            return result
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise SourceConflict(
                "fragment ID, ordinal, or locator conflicts with immutable corpus data"
            ) from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _persisted_manifest_checksum(
        self, connection: sqlite3.Connection, source: Mapping[str, Any]
    ) -> str:
        from .corpus import canonical_manifest_checksum

        fragment_rows = connection.execute(
            """SELECT * FROM source_fragments WHERE source_version_id=?
               ORDER BY ordinal, fragment_id""",
            (source["source_version_id"],),
        ).fetchall()
        fragments = [self._fragment_projection(row) for row in fragment_rows]
        return canonical_manifest_checksum(dict(source), fragments)

    def review_source_version(
        self,
        source_version_id: str,
        review: Mapping[str, str],
        *,
        operation_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        return self._review_record(
            "source_version", source_version_id, review,
            operation_id=operation_id, expected_revision=expected_revision,
        )

    def review_source_fragment(
        self,
        fragment_id: str,
        review: Mapping[str, str],
        *,
        operation_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        return self._review_record(
            "source_fragment", fragment_id, review,
            operation_id=operation_id, expected_revision=expected_revision,
        )

    def _review_record(
        self,
        resource_type: str,
        resource_id: str,
        review: Mapping[str, str],
        *,
        operation_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        table, key_name = {
            "source_version": ("source_versions", "source_version_id"),
            "source_fragment": ("source_fragments", "fragment_id"),
        }[resource_type]
        review_payload = dict(review)
        request_hash = self._corpus_operation_hash(
            resource_type=resource_type,
            resource_id=resource_id,
            operation_type="corpus.review",
            expected_revision=expected_revision,
            payload=review_payload,
        )
        now = dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")
        connection = self._ready_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._replay_corpus_operation(connection, operation_id, request_hash)
            if replay is not None:
                connection.commit()
                return replay
            row = connection.execute(
                f"SELECT * FROM {table} WHERE {key_name}=?", (resource_id,)
            ).fetchone()
            if row is None:
                raise SourceConflict("review target does not exist")
            if row["revision"] != expected_revision:
                raise OptimisticConflict("review target revision is stale")
            if row["approval_status"] != "pending":
                raise SourceConflict("reviewed resources are terminal; create a new version")
            if resource_type == "source_version" and review["status"] == "approved":
                actual_checksum = self._persisted_manifest_checksum(connection, row)
                if actual_checksum != row["manifest_checksum"]:
                    raise SourceConflict("source manifest checksum does not match persisted fragments")
            if resource_type == "source_fragment" and review["status"] == "approved":
                parent = connection.execute(
                    "SELECT approval_status FROM source_versions WHERE source_version_id=?",
                    (row["source_version_id"],),
                ).fetchone()
                if parent is None or parent["approval_status"] != "approved":
                    raise SourceConflict("fragment approval requires an approved source version")
            self._begin_corpus_operation(
                connection,
                operation_id=operation_id,
                resource_type=resource_type,
                resource_id=resource_id,
                operation_type="corpus.review",
                expected_revision=expected_revision,
                request_hash=request_hash,
                now=now,
            )
            next_revision = expected_revision + 1
            connection.execute(
                f"""UPDATE {table} SET approval_status=?, revision=?, reviewed_by=?,
                    review_note=?, reviewed_at=?, updated_at=?
                    WHERE {key_name}=? AND revision=?""",
                (
                    review["status"], next_revision, review["reviewer"], review["note"],
                    now, now, resource_id, expected_revision,
                ),
            )
            connection.execute(
                """INSERT INTO corpus_review_history (
                    review_id, operation_id, resource_type, resource_id,
                    from_status, to_status, reviewer, review_note, reviewed_at
                ) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)""",
                (
                    new_id("cr_"), operation_id, resource_type, resource_id,
                    review["status"], review["reviewer"], review["note"], now,
                ),
            )
            updated = connection.execute(
                f"SELECT * FROM {table} WHERE {key_name}=?", (resource_id,)
            ).fetchone()
            projection = (
                self._source_projection(updated)
                if resource_type == "source_version"
                else self._fragment_projection(updated)
            )
            result = {"operation_id": operation_id, **projection}
            self._complete_corpus_operation(connection, operation_id, result, now)
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list_corpus_review_history(
        self, resource_type: str | None = None, resource_id: str | None = None
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        parameters: list[str] = []
        if resource_type is not None:
            clauses.append("resource_type=?")
            parameters.append(resource_type)
        if resource_id is not None:
            clauses.append("resource_id=?")
            parameters.append(resource_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        connection = self._ready_connection()
        try:
            rows = connection.execute(
                "SELECT * FROM corpus_review_history"
                + where
                + " ORDER BY reviewed_at, review_id",
                parameters,
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def search_approved_fragments(self, query: str, *, limit: int) -> list[dict[str, Any]]:
        from .corpus import normalize_search_text

        terms = [term for term in normalize_search_text(query).split() if term]
        if not terms:
            return []
        match = " AND ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)
        connection = self._ready_connection()
        try:
            self._verify_corpus_integrity(connection)
            rows = connection.execute(
                """SELECT f.fragment_id, f.source_version_id, s.work_id, s.title,
                          s.source_class, f.locator, f.text AS quote, f.checksum,
                          s.rights_note, s.provenance_url,
                          s.approval_status AS source_approval_status,
                          s.reviewed_by AS source_reviewed_by,
                          s.review_note AS source_review_note,
                          s.reviewed_at AS source_reviewed_at,
                          f.approval_status AS fragment_approval_status,
                          f.reviewed_by AS fragment_reviewed_by,
                          f.review_note AS fragment_review_note,
                          f.reviewed_at AS fragment_reviewed_at
                   FROM source_fragments_fts x
                   JOIN source_fragments f ON f.fragment_id=x.fragment_id
                   JOIN source_versions s ON s.source_version_id=f.source_version_id
                   WHERE source_fragments_fts MATCH ?
                     AND s.approval_status='approved'
                     AND f.approval_status='approved'
                   ORDER BY bm25(source_fragments_fts), s.source_version_id, f.ordinal
                   LIMIT ?""",
                (match, limit),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    @staticmethod
    def _verify_corpus_integrity(connection: sqlite3.Connection) -> None:
        """Fail closed when fragment bytes or the exact FTS membership drift."""
        try:
            fragments = connection.execute(
                "SELECT fragment_id, text, checksum FROM source_fragments"
            ).fetchall()
            expected_ids = {row["fragment_id"] for row in fragments}
            indexed_rows = connection.execute(
                "SELECT fragment_id FROM source_fragments_fts"
            ).fetchall()
            indexed_ids = [row["fragment_id"] for row in indexed_rows]
        except sqlite3.DatabaseError as exc:
            raise CorpusIntegrityError("corpus or index cannot be read") from exc
        if any(sha256_text(row["text"]) != row["checksum"] for row in fragments):
            raise CorpusIntegrityError("source fragment checksum mismatch")
        if len(indexed_ids) != len(set(indexed_ids)) or set(indexed_ids) != expected_ids:
            raise CorpusIntegrityError("source fragment index membership mismatch")

    def get_source_version(self, source_version_id: str) -> dict[str, Any] | None:
        connection = self._ready_connection()
        try:
            row = connection.execute(
                "SELECT * FROM source_versions WHERE source_version_id=?",
                (source_version_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            connection.close()

    def list_source_versions(self) -> list[dict[str, Any]]:
        connection = self._ready_connection()
        try:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM source_versions ORDER BY source_version_id"
                ).fetchall()
            ]
        finally:
            connection.close()

    def seed_builtin_corpus(self) -> int:
        """Load the checked-in, human-reviewed manifest explicitly and idempotently."""
        from .corpus import load_builtin_manifest

        manifest = load_builtin_manifest()
        inserted = 0
        for entry in manifest["sources"]:
            fragments = entry["fragments"]
            source_result = self.ingest_source_version(
                {
                    key: value
                    for key, value in entry.items()
                    if key not in {"fragments", "review"}
                },
                operation_id=stable_operation_id(
                    f"builtin:{entry['source_version_id']}:source"
                ),
                expected_revision=0,
            )
            source_revision = source_result["revision"]
            if fragments:
                fragment_result = self.ingest_source_fragments(
                    entry["source_version_id"],
                    fragments,
                    operation_id=stable_operation_id(
                        f"builtin:{entry['source_version_id']}:fragments"
                    ),
                    expected_revision=source_revision,
                )
                source_revision = fragment_result["revision"]
            source_review = {
                "status": entry["review"]["status"],
                "reviewer": entry["review"]["reviewer"],
                "note": entry["review"]["note"],
            }
            self.review_source_version(
                entry["source_version_id"],
                source_review,
                operation_id=stable_operation_id(
                    f"builtin:{entry['source_version_id']}:source-review"
                ),
                expected_revision=source_revision,
            )
            for fragment in fragments:
                self.review_source_fragment(
                    fragment["fragment_id"],
                    source_review,
                    operation_id=stable_operation_id(
                        f"builtin:{fragment['fragment_id']}:fragment-review"
                    ),
                    expected_revision=1,
                )
                inserted += 1
        return inserted

    def rebuild_run(self, run_id: str) -> dict[str, Any]:
        events = self.list_events(run_id)
        if not events:
            raise RunNotFound(run_id)
        _verify_event_chain(events)
        first = events[0]
        if first["event_type"] != "research_run.created":
            raise ResearchStoreError("run ledger does not start with research_run.created")
        payload = json.loads(first["payload_json"])
        rebuilt = payload["run"]
        for event in events[1:]:
            # Every Task 1 mutation appends one event and advances the common
            # projection metadata. Typed reducers can extend this in later tasks.
            rebuilt["revision"] += 1
            rebuilt["updated_at"] = event["created_at"]
            event_payload = json.loads(event["payload_json"])
            if isinstance(event_payload.get("status"), str):
                rebuilt["status"] = event_payload["status"]
        return rebuilt

    def seed_source_for_testing(
        self,
        *,
        source_version_id: str,
        title: str,
        rights_note: str,
        fragments: Iterable[Mapping[str, str]],
    ) -> None:
        """Explicit test helper; production startup never seeds corpus text."""
        rows = list(fragments)
        now = dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")
        source_checksum = sha256_text(canonical_json(rows))
        connection = self._ready_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO source_versions (
                    source_version_id, title, source_class, rights_note, checksum,
                    approval_status, metadata_json, created_at
                ) VALUES (?, ?, 'modern_secondary', ?, ?, 'approved', '{}', ?)""",
                (source_version_id, title, rights_note, source_checksum, now),
            )
            for ordinal, fragment in enumerate(rows, start=1):
                text = fragment["text"]
                connection.execute(
                    """INSERT INTO source_fragments (
                        fragment_id, source_version_id, ordinal, locator, text, checksum
                    ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        fragment["fragment_id"], source_version_id, ordinal,
                        fragment["locator"], text, sha256_text(text),
                    ),
                )
                connection.execute(
                    """UPDATE source_fragments SET approval_status='approved',
                       aliases_text='' WHERE fragment_id=?""",
                    (fragment["fragment_id"],),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
