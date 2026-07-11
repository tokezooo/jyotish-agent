from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from pathlib import Path

import pytest

from jyotish_agent.research_store import (
    OptimisticConflict,
    ResearchStore,
    ResearchStoreError,
    canonical_json,
)


def _id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4()}"


def _run() -> dict:
    return {
        "run_id": _id("rr_"),
        "revision": 1,
        "status": "created",
        "question": "Which career themes deserve careful study?",
        "birth_profile": {"date": "1990-01-01", "time": "12:30:00"},
        "calculation_config": {"ayanamsa": "LAHIRI"},
        "reference_date": "2026-07-12",
        "civil_datetime": "1990-01-01T12:30:00",
        "timezone_resolution_mode": "fixed_offset_legacy",
        "resolved_offset_minutes": 330,
        "utc_instant": "1990-01-01T07:00:00Z",
        "engine_name": "PyJHora",
        "engine_version": "4.8.6",
        "model_version": "test-model",
        "planner_version": "provisional-1",
        "corpus_version": "test-corpus-v1",
        "contract_version": "1.0",
        "request_hash": "a" * 64,
        "created_at": "2026-07-12T09:00:00Z",
        "updated_at": "2026-07-12T09:00:00Z",
    }


def test_restart_persists_run_and_schema(tmp_path: Path):
    store = ResearchStore(tmp_path / "data")
    run = _run()
    store.create_run(run, operation_id=_id("op_"), expected_revision=0)

    reopened = ResearchStore(tmp_path / "data")
    assert reopened.get_run(run["run_id"]) == run
    with sqlite3.connect(reopened.database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {
        "research_runs",
        "run_events",
        "operations",
        "evidence_items",
        "claims",
        "claim_supports",
        "answers",
        "source_versions",
        "source_fragments",
    } <= tables


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission contract")
def test_runtime_directory_and_database_are_private(tmp_path: Path):
    store = ResearchStore(tmp_path / "private")
    store.initialize()
    assert store.data_root.stat().st_mode & 0o777 == 0o700
    assert store.database_path.stat().st_mode & 0o777 == 0o600


def test_events_form_an_append_only_hash_chain(tmp_path: Path):
    store = ResearchStore(tmp_path / "data")
    run = _run()
    store.create_run(run, operation_id=_id("op_"), expected_revision=0)
    store.append_event(
        run["run_id"],
        operation_id=_id("op_"),
        expected_revision=1,
        event_type="research_run.noted",
        payload={"note_type": "fixture"},
        producer="pytest",
        producer_version="1",
    )

    events = store.list_events(run["run_id"])
    assert [event["seq"] for event in events] == [1, 2]
    assert events[0]["previous_event_hash"] is None
    assert events[1]["previous_event_hash"] == events[0]["event_hash"]
    for event in events:
        assert event["payload_hash"] == hashlib.sha256(
            event["payload_json"].encode()
        ).hexdigest()

    with sqlite3.connect(store.database_path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE run_events SET event_type = 'tampered' WHERE event_id = ?",
                (events[0]["event_id"],),
            )


def test_stale_revision_conflicts_without_appending(tmp_path: Path):
    store = ResearchStore(tmp_path / "data")
    run = _run()
    store.create_run(run, operation_id=_id("op_"), expected_revision=0)
    with pytest.raises(OptimisticConflict):
        store.append_event(
            run["run_id"],
            operation_id=_id("op_"),
            expected_revision=0,
            event_type="research_run.noted",
            payload={},
            producer="pytest",
            producer_version="1",
        )
    assert len(store.list_events(run["run_id"])) == 1


def test_operation_id_cannot_replay_an_event_from_another_run(tmp_path: Path):
    store = ResearchStore(tmp_path / "data")
    first_run = _run()
    second_run = _run()
    store.create_run(first_run, operation_id=_id("op_"), expected_revision=0)
    store.create_run(second_run, operation_id=_id("op_"), expected_revision=0)
    operation_id = _id("op_")
    store.append_event(
        first_run["run_id"],
        operation_id=operation_id,
        expected_revision=1,
        event_type="research_run.noted",
        payload={"note_type": "fixture"},
        producer="pytest",
        producer_version="1",
    )

    with pytest.raises(OptimisticConflict):
        store.append_event(
            second_run["run_id"],
            operation_id=operation_id,
            expected_revision=1,
            event_type="research_run.noted",
            payload={"note_type": "fixture"},
            producer="pytest",
            producer_version="1",
        )
    assert len(store.list_events(second_run["run_id"])) == 1


@pytest.mark.parametrize(
    ("changed"),
    [
        {"event_type": "research_run.changed"},
        {"payload": {"note_type": "changed"}},
        {"producer": "another-producer"},
        {"producer_version": "2"},
        {"expected_revision": 99},
    ],
)
def test_operation_id_conflicts_when_any_semantic_input_changes(
    tmp_path: Path, changed: dict
):
    store = ResearchStore(tmp_path / "data")
    run = _run()
    store.create_run(run, operation_id=_id("op_"), expected_revision=0)
    operation_id = _id("op_")
    arguments = {
        "operation_id": operation_id,
        "expected_revision": 1,
        "event_type": "research_run.noted",
        "payload": {"note_type": "fixture"},
        "producer": "pytest",
        "producer_version": "1",
    }
    store.append_event(run["run_id"], **arguments)
    with pytest.raises(OptimisticConflict):
        store.append_event(run["run_id"], **{**arguments, **changed})


def test_canonical_json_is_stable_and_rejects_non_finite_numbers():
    assert canonical_json({"b": 2, "a": [3, 1]}) == '{"a":[3,1],"b":2}'
    with pytest.raises(ValueError):
        canonical_json({"invalid": float("nan")})
    with pytest.raises(ValueError):
        canonical_json({"invalid": float("inf")})


def test_failed_initial_migration_rolls_back_every_statement(tmp_path: Path, monkeypatch):
    import jyotish_agent.research_store as store_module

    monkeypatch.setattr(store_module, "SCHEMA_VERSION", 1)
    monkeypatch.setattr(
        store_module,
        "_MIGRATIONS",
        {
            1: """
            CREATE TABLE must_rollback (value TEXT);
            INSERT INTO missing_table VALUES ('force failure');
            """
        },
        raising=False,
    )
    store = ResearchStore(tmp_path / "data")
    with pytest.raises(sqlite3.OperationalError):
        store.initialize()

    with sqlite3.connect(store.database_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        partial = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='must_rollback'"
        ).fetchone()
    assert version == 0
    assert partial is None


def test_failed_non_initial_migration_keeps_version_and_backup(tmp_path: Path, monkeypatch):
    import jyotish_agent.research_store as store_module

    store = ResearchStore(tmp_path / "data")
    store.initialize()
    monkeypatch.setattr(store_module, "SCHEMA_VERSION", 2)
    monkeypatch.setattr(
        store_module,
        "_MIGRATIONS",
        {
            1: store_module._MIGRATION_1,
            2: """
            CREATE TABLE must_rollback_upgrade (value TEXT);
            INSERT INTO missing_table VALUES ('force failure');
            """,
        },
    )
    with pytest.raises(sqlite3.OperationalError):
        store.initialize()

    with sqlite3.connect(store.database_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        partial = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='must_rollback_upgrade'"
        ).fetchone()
    backups = list(store.data_root.glob("research.sqlite3.v1.*.bak"))
    assert version == 1
    assert partial is None
    assert len(backups) == 1
    assert backups[0].stat().st_mode & 0o777 == 0o600


def test_rebuild_and_memo_are_equal_after_restart(tmp_path: Path):
    from jyotish_agent.research_memo import render_provisional_memo

    run = _run()
    store = ResearchStore(tmp_path / "data")
    store.create_run(run, operation_id=_id("op_"), expected_revision=0)
    first = render_provisional_memo(
        store.rebuild_run(run["run_id"]), store.list_events(run["run_id"])
    )

    reopened = ResearchStore(tmp_path / "data")
    rebuilt = reopened.rebuild_run(run["run_id"])
    second = render_provisional_memo(
        rebuilt, reopened.list_events(run["run_id"])
    )
    assert rebuilt == run
    assert second == first
    assert second.manifest_hash == hashlib.sha256(
        canonical_json(second.manifest).encode()
    ).hexdigest()


def test_rebuild_matches_projection_after_later_events(tmp_path: Path):
    store = ResearchStore(tmp_path / "data")
    run = _run()
    store.create_run(run, operation_id=_id("op_"), expected_revision=0)
    store.append_event(
        run["run_id"],
        operation_id=_id("op_"),
        expected_revision=1,
        event_type="research_run.noted",
        payload={"note_type": "fixture"},
        producer="pytest",
        producer_version="1",
    )
    assert store.rebuild_run(run["run_id"]) == store.get_run(run["run_id"])


def _store_with_two_events(tmp_path: Path) -> tuple[ResearchStore, dict]:
    store = ResearchStore(tmp_path / "data")
    run = _run()
    store.create_run(run, operation_id=_id("op_"), expected_revision=0)
    store.append_event(
        run["run_id"],
        operation_id=_id("op_"),
        expected_revision=1,
        event_type="research_run.noted",
        payload={"note_type": "fixture"},
        producer="pytest",
        producer_version="1",
    )
    return store, run


@pytest.mark.parametrize(
    ("sql", "parameters"),
    [
        ("UPDATE run_events SET seq=3 WHERE seq=2", ()),
        ("UPDATE run_events SET payload_json='{}' WHERE seq=2", ()),
        ("UPDATE run_events SET previous_event_hash='broken' WHERE seq=2", ()),
        ("UPDATE run_events SET producer='tampered' WHERE seq=2", ()),
        ("UPDATE run_events SET event_hash='broken' WHERE seq=2", ()),
    ],
    ids=["sequence", "payload-hash", "previous-link", "envelope", "event-hash"],
)
def test_rebuild_rejects_tampered_event_chain(
    tmp_path: Path, sql: str, parameters: tuple
):
    store, run = _store_with_two_events(tmp_path)
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("DROP TRIGGER run_events_no_update")
        connection.execute(sql, parameters)
        connection.commit()

    with pytest.raises(ResearchStoreError):
        store.rebuild_run(run["run_id"])


def test_test_corpus_seed_is_explicit_and_metadata_safe(tmp_path: Path):
    store = ResearchStore(tmp_path / "data")
    fragments = [
        {
            "fragment_id": f"sf_{index}",
            "locator": f"fixture:{index}",
            "text": f"Authored test principle {index}.",
        }
        for index in range(1, 13)
    ]
    store.seed_source_for_testing(
        source_version_id="sv_authored_test_v1",
        title="Authored research fixtures",
        rights_note="Tiny original fixture text authored for tests.",
        fragments=fragments,
    )
    with sqlite3.connect(store.database_path) as connection:
        source = connection.execute(
            "SELECT approval_status, rights_note FROM source_versions"
        ).fetchone()
        rows = connection.execute(
            "SELECT text FROM source_fragments ORDER BY ordinal"
        ).fetchall()
    assert source == ("approved", "Tiny original fixture text authored for tests.")
    assert len(rows) == 12
    assert all("Authored test principle" in row[0] for row in rows)
