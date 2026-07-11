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

SCHEMA_VERSION = 1
DATABASE_NAME = "research.sqlite3"


class ResearchStoreError(RuntimeError):
    pass


class RunNotFound(ResearchStoreError):
    pass


class OptimisticConflict(ResearchStoreError):
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


def default_data_root() -> Path:
    configured = os.environ.get("JYOTISH_AGENT_DATA_ROOT")
    if configured:
        return Path(configured).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / "jyotish-agent"


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


class ResearchStore:
    def __init__(self, data_root: Path | str | None = None, *, busy_timeout_ms: int = 5_000):
        self.data_root = Path(data_root) if data_root is not None else default_data_root()
        self.database_path = self.data_root / DATABASE_NAME
        self.busy_timeout_ms = busy_timeout_ms

    def initialize(self) -> None:
        self.data_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.data_root, 0o700)
        existed = self.database_path.exists()
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
            if current < 1:
                connection.executescript(_MIGRATION_1)
                connection.execute("PRAGMA user_version = 1")
                connection.commit()
        finally:
            connection.close()
        if self.database_path.exists() or existed:
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

            connection.execute(
                """INSERT INTO research_runs (
                    run_id, revision, status, question, birth_profile_json,
                    calculation_config_json, reference_date, civil_datetime,
                    timezone_resolution_mode, resolved_offset_minutes, utc_instant,
                    engine_name, engine_version, model_version, planner_version,
                    corpus_version, contract_version, request_hash, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            run["resolved_offset_minutes"], run["utc_instant"], run["engine_name"],
            run["engine_version"], run["model_version"], run["planner_version"],
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
    ) -> tuple[dict[str, Any], int]:
        payload_json = canonical_json(payload)
        request_hash = sha256_text(
            canonical_json({"event_type": event_type, "payload": json.loads(payload_json)})
        )
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
                "SELECT revision, updated_at FROM research_runs WHERE run_id=?", (run_id,)
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
            next_revision = expected_revision + 1
            changed = connection.execute(
                """UPDATE research_runs SET revision=?, updated_at=?
                   WHERE run_id=? AND revision=?""",
                (next_revision, now, run_id, expected_revision),
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
        envelope = {
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
        }
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

    def rebuild_run(self, run_id: str) -> dict[str, Any]:
        events = self.list_events(run_id)
        if not events:
            raise RunNotFound(run_id)
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
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
