from __future__ import annotations

import hashlib
import sqlite3
import uuid
from pathlib import Path

from jyotish_agent.api import app
from jyotish_agent.corpus import (
    canonical_manifest_checksum,
    load_builtin_manifest,
    normalize_search_text,
)
from jyotish_agent.research_store import ResearchStore, canonical_json


def _op() -> str:
    return f"op_{uuid.uuid4()}"


def _v5_store(tmp_path: Path, monkeypatch) -> ResearchStore:
    import jyotish_agent.research_store as store_module

    store = ResearchStore(tmp_path / "data")
    with monkeypatch.context() as patcher:
        patcher.setattr(store_module, "SCHEMA_VERSION", 5)
        store.initialize()
    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
    return store


def _v4_store(tmp_path: Path, monkeypatch) -> ResearchStore:
    import jyotish_agent.research_store as store_module

    store = ResearchStore(tmp_path / "data")
    with monkeypatch.context() as patcher:
        patcher.setattr(store_module, "SCHEMA_VERSION", 4)
        store.initialize()
    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
    return store


def _insert_v5_source(
    store: ResearchStore,
    source: dict,
    fragments: list[dict],
    *,
    approval_status: str,
    reviewer: str | None,
    review_note: str | None,
    reviewed_at: str | None,
    fragment_approval_status: str | None = None,
    fragment_reviewer: str | None = None,
    fragment_review_note: str | None = None,
    fragment_reviewed_at: str | None = None,
) -> None:
    created_at = "2026-07-12T10:00:00Z"
    metadata = {
        key: source[key]
        for key in ("work_id", "language", "edition", "provenance_url")
    }
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            """INSERT INTO source_versions (
                source_version_id, title, source_class, rights_note, checksum,
                approval_status, metadata_json, created_at, work_id, language,
                edition, provenance_url, manifest_checksum, reviewed_by,
                review_note, reviewed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                source["source_version_id"], source["title"], source["source_class"],
                source["rights_note"], source["manifest_checksum"], approval_status,
                canonical_json(metadata), created_at, source["work_id"], source["language"],
                source["edition"], source["provenance_url"], source["manifest_checksum"],
                reviewer, review_note, reviewed_at,
            ),
        )
        fragment_status = fragment_approval_status or approval_status
        fragment_actor = fragment_reviewer if fragment_approval_status else reviewer
        fragment_note = fragment_review_note if fragment_approval_status else review_note
        fragment_timestamp = fragment_reviewed_at if fragment_approval_status else reviewed_at
        for fragment in fragments:
            aliases = " ".join(fragment["transliteration_aliases"])
            connection.execute(
                """INSERT INTO source_fragments (
                    fragment_id, source_version_id, ordinal, locator, text, checksum,
                    aliases_text, approval_status, reviewed_by, review_note, reviewed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    fragment["fragment_id"], source["source_version_id"],
                    fragment["ordinal"], fragment["locator"], fragment["text"],
                    fragment["checksum"], aliases, fragment_status, fragment_actor,
                    fragment_note, fragment_timestamp,
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
        connection.commit()


def test_v5_builtin_upgrade_backfills_replay_and_review_history(tmp_path: Path, monkeypatch):
    store = _v5_store(tmp_path, monkeypatch)
    manifest = load_builtin_manifest()
    for source in manifest["sources"]:
        _insert_v5_source(
            store,
            source,
            source["fragments"],
            approval_status=source["review"]["status"],
            reviewer=source["review"]["reviewer"],
            review_note=source["review"]["note"],
            reviewed_at="2026-07-12T11:00:00Z",
        )

    store.initialize()
    sources = {row["source_version_id"]: row for row in store.list_source_versions()}
    assert sources["sv_brhat_jataka_1905_en"]["revision"] == 3
    assert sources["sv_bphs_quarantine"]["revision"] == 2
    with sqlite3.connect(store.database_path) as connection:
        fragment_revisions = {
            row[0]
            for row in connection.execute("SELECT revision FROM source_fragments")
        }
        operation_count = connection.execute(
            "SELECT COUNT(*) FROM corpus_operations"
        ).fetchone()[0]
    assert fragment_revisions == {2}
    assert operation_count == 41
    before_history = store.list_corpus_review_history()
    assert len(before_history) == 34
    assert {row["from_status"] for row in before_history} == {"pending"}

    # Current deterministic seed IDs must exact-replay the migrated v5 actions.
    assert store.seed_builtin_corpus() == 30
    assert store.list_corpus_review_history() == before_history
    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM corpus_operations"
        ).fetchone()[0] == operation_count


def test_v4_upgrade_atomically_backfills_normalized_fragment_search(
    tmp_path: Path, monkeypatch
):
    store = _v4_store(tmp_path, monkeypatch)
    text = "Śani governs karma sthāna"
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            """INSERT INTO source_versions (
                source_version_id, title, source_class, rights_note, checksum,
                approval_status, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, 'pending', '{}', ?)""",
            (
                "sv_v4_search",
                "V4 transliteration fixture",
                "original_text",
                "Authored fixture dedicated to the public domain.",
                hashlib.sha256(b"legacy-placeholder").hexdigest(),
                "2026-07-12T10:00:00Z",
            ),
        )
        connection.execute(
            """INSERT INTO source_fragments (
                fragment_id, source_version_id, ordinal, locator, text, checksum
            ) VALUES (?, ?, 1, ?, ?, ?)""",
            (
                "sf_v4_search_1",
                "sv_v4_search",
                "chapter 1, verse 1",
                text,
                hashlib.sha256(text.encode()).hexdigest(),
            ),
        )
        connection.commit()

    store.initialize()
    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 9
        assert connection.execute(
            "SELECT COUNT(*) FROM source_fragments_fts WHERE fragment_id=?",
            ("sf_v4_search_1",),
        ).fetchone()[0] == 1

    review = {
        "status": "approved",
        "reviewer": "migration-reviewer",
        "note": "approved authored migration fixture",
    }
    store.review_source_version(
        "sv_v4_search", review, operation_id=_op(), expected_revision=2
    )
    store.review_source_fragment(
        "sf_v4_search_1", review, operation_id=_op(), expected_revision=1
    )

    found = store.search_approved_fragments("sani karma sthana", limit=5)
    assert [row["fragment_id"] for row in found] == ["sf_v4_search_1"]


def test_v5_builtin_source_pending_upgrade_can_finish_seed_idempotently(
    tmp_path: Path, monkeypatch
):
    store = _v5_store(tmp_path, monkeypatch)
    source = load_builtin_manifest()["sources"][0]
    _insert_v5_source(
        store,
        source,
        source["fragments"],
        approval_status="pending",
        reviewer=None,
        review_note=None,
        reviewed_at=None,
    )

    store.initialize()
    assert store.get_source_version(source["source_version_id"])["approval_status"] == "pending"
    assert store.seed_builtin_corpus() == 30
    history = store.list_corpus_review_history()
    assert len(history) == 34
    assert store.seed_builtin_corpus() == 30
    assert store.list_corpus_review_history() == history


def test_v5_builtin_fragments_pending_upgrade_can_finish_seed_idempotently(
    tmp_path: Path, monkeypatch
):
    store = _v5_store(tmp_path, monkeypatch)
    source = load_builtin_manifest()["sources"][0]
    review = source["review"]
    _insert_v5_source(
        store,
        source,
        source["fragments"],
        approval_status=review["status"],
        reviewer=review["reviewer"],
        review_note=review["note"],
        reviewed_at="2026-07-12T11:00:00Z",
        fragment_approval_status="pending",
    )

    store.initialize()
    with sqlite3.connect(store.database_path) as connection:
        fragment_statuses = {
            row[0]
            for row in connection.execute(
                "SELECT approval_status FROM source_fragments WHERE source_version_id=?",
                (source["source_version_id"],),
            )
        }
    assert fragment_statuses == {"pending"}
    assert store.seed_builtin_corpus() == 30
    history = store.list_corpus_review_history()
    assert len(history) == 34
    assert store.seed_builtin_corpus() == 30
    assert store.list_corpus_review_history() == history


def test_v5_terminal_review_with_null_metadata_uses_explicit_fallback(
    tmp_path: Path, monkeypatch
):
    store = _v5_store(tmp_path, monkeypatch)
    source = load_builtin_manifest()["sources"][0]
    _insert_v5_source(
        store,
        source,
        source["fragments"],
        approval_status="approved",
        reviewer=None,
        review_note=None,
        reviewed_at=None,
    )

    store.initialize()
    history = store.list_corpus_review_history()
    assert history
    assert {row["reviewer"] for row in history} == {"unknown-v5-reviewer"}
    assert {row["review_note"] for row in history} == {"Migrated v5 review decision."}
    migrated_source = store.get_source_version(source["source_version_id"])
    assert migrated_source["reviewed_by"] == "unknown-v5-reviewer"
    assert migrated_source["review_note"] == "Migrated v5 review decision."
    with sqlite3.connect(store.database_path) as connection:
        fragment_reviewers = {
            row[0]
            for row in connection.execute(
                "SELECT reviewed_by FROM source_fragments WHERE source_version_id=?",
                (source["source_version_id"],),
            )
        }
    assert fragment_reviewers == {"unknown-v5-reviewer"}


def test_v5_pending_aliases_are_preserved_and_manifest_reconciled(
    tmp_path: Path, monkeypatch
):
    store = _v5_store(tmp_path, monkeypatch)
    original_aliases = ["Śani", "shani", "karma sthāna"]
    flattened = " ".join(original_aliases)
    text = "pending governed fragment"
    fragment = {
        "fragment_id": "sf_pending_alias_1",
        "ordinal": 1,
        "locator": "chapter 1, verse 1",
        "text": text,
        "transliteration_aliases": original_aliases,
        "checksum": hashlib.sha256(text.encode()).hexdigest(),
    }
    source = {
        "source_version_id": "sv_pending_alias",
        "work_id": "brhat-jataka",
        "title": "Pending v5 alias fixture",
        "source_class": "original_text",
        "language": "sa-Latn",
        "edition": "Authored pending fixture",
        "provenance_url": "https://example.invalid/pending-v5",
        "rights_note": "Authored fixture dedicated to the public domain.",
    }
    original_checksum = canonical_manifest_checksum(source, [fragment])
    source["manifest_checksum"] = original_checksum
    _insert_v5_source(
        store,
        source,
        [fragment],
        approval_status="pending",
        reviewer=None,
        review_note=None,
        reviewed_at=None,
    )

    store.initialize()
    migrated = store.get_source_version("sv_pending_alias")
    assert migrated["revision"] == 2
    assert migrated["manifest_checksum_original"] == original_checksum
    assert migrated["manifest_reconciliation_note"]
    with sqlite3.connect(store.database_path) as connection:
        row = connection.execute(
            "SELECT aliases_text, aliases_json FROM source_fragments WHERE fragment_id=?",
            ("sf_pending_alias_1",),
        ).fetchone()
    assert row == (flattened, canonical_json([flattened]))
    reconstructed_fragment = {
        **fragment,
        "transliteration_aliases": [flattened],
    }
    assert migrated["manifest_checksum"] == canonical_manifest_checksum(
        source, [reconstructed_fragment]
    )

    approved = store.review_source_version(
        "sv_pending_alias",
        {"status": "approved", "reviewer": "human", "note": "reconciliation reviewed"},
        operation_id=_op(),
        expected_revision=2,
    )
    assert approved["approval_status"] == "approved"


def test_corpus_mutation_openapi_uses_strict_typed_responses():
    schema = app.openapi()
    expectations = {
        ("/v2/corpus/source-versions", "post"): "CorpusSourceResponse",
        ("/v2/corpus/source-versions/{source_version_id}/fragments", "post"):
            "CorpusFragmentsResponse",
        ("/v2/corpus/source-versions/{source_version_id}/review", "post"):
            "CorpusSourceResponse",
        ("/v2/corpus/fragments/{fragment_id}/review", "post"):
            "CorpusFragmentResponse",
    }
    for (path, method), model_name in expectations.items():
        response_schema = schema["paths"][path][method]["responses"]["200" if "review" in path else "201"]["content"]["application/json"]["schema"]
        assert response_schema["$ref"].endswith(f"/{model_name}")
        assert schema["components"]["schemas"][model_name]["additionalProperties"] is False
