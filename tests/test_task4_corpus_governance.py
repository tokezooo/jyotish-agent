from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from jyotish_agent.api import app
from jyotish_agent.research_service import ResearchService
from jyotish_agent.research_store import ResearchStore, canonical_json


def _op() -> str:
    return f"op_{uuid.uuid4()}"


def _fragment(
    fragment_id: str = "sf_governed_1",
    *,
    ordinal: int = 1,
    locator: str = "chapter 10, verse 1",
    text: str = "career karma-sthāna governed quote",
) -> dict:
    return {
        "fragment_id": fragment_id,
        "ordinal": ordinal,
        "locator": locator,
        "text": text,
        "transliteration_aliases": ["career karma sthana"],
        "checksum": hashlib.sha256(text.encode()).hexdigest(),
    }


def _metadata(source_version_id: str = "sv_governed_v1") -> dict:
    return {
        "source_version_id": source_version_id,
        "work_id": "brhat-jataka",
        "title": "Governed authored fixture",
        "source_class": "original_text",
        "language": "sa-Latn",
        "edition": "Authored fixture version 1",
        "provenance_url": "https://example.invalid/governed-fixture",
        "rights_note": "Original fixture dedicated to the public domain.",
    }


def _manifest_checksum(metadata: dict, fragments: list[dict]) -> str:
    return hashlib.sha256(
        canonical_json({**metadata, "fragments": fragments}).encode()
    ).hexdigest()


def _source_body(
    metadata: dict,
    fragments: list[dict],
    *,
    operation_id: str | None = None,
    manifest_checksum: str | None = None,
) -> dict:
    return {
        "operation_id": operation_id or _op(),
        "expected_revision": 0,
        **metadata,
        "manifest_checksum": manifest_checksum or _manifest_checksum(metadata, fragments),
    }


def _client(tmp_path: Path) -> TestClient:
    app.state.research_service = ResearchService(ResearchStore(tmp_path / "data"))
    return TestClient(app)


def _create_and_ingest(
    client: TestClient,
    *,
    source_version_id: str = "sv_governed_v1",
    manifest_checksum: str | None = None,
) -> tuple[dict, dict, dict]:
    fragment = _fragment(fragment_id=f"sf_{source_version_id[3:]}_1")
    metadata = _metadata(source_version_id)
    source_body = _source_body(
        metadata, [fragment], manifest_checksum=manifest_checksum
    )
    created = client.post("/v2/corpus/source-versions", json=source_body)
    assert created.status_code == 201, created.text
    fragment_body = {
        "operation_id": _op(),
        "expected_revision": created.json()["revision"],
        "fragments": [fragment],
    }
    ingested = client.post(
        f"/v2/corpus/source-versions/{source_version_id}/fragments",
        json=fragment_body,
    )
    assert ingested.status_code == 201, ingested.text
    return created.json(), ingested.json(), fragment


def test_corpus_mutations_are_idempotent_and_revision_guarded(tmp_path: Path):
    client = _client(tmp_path)
    fragment = _fragment()
    metadata = _metadata()
    source_op = _op()
    source_body = _source_body(metadata, [fragment], operation_id=source_op)
    first = client.post("/v2/corpus/source-versions", json=source_body)
    replay = client.post("/v2/corpus/source-versions", json=source_body)
    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    assert first.json()["revision"] == 1

    changed = {**source_body, "title": "changed under reused operation"}
    assert client.post("/v2/corpus/source-versions", json=changed).status_code == 409

    fragment_op = _op()
    fragment_body = {
        "operation_id": fragment_op,
        "expected_revision": 1,
        "fragments": [fragment],
    }
    first_fragments = client.post(
        "/v2/corpus/source-versions/sv_governed_v1/fragments", json=fragment_body
    )
    replay_fragments = client.post(
        "/v2/corpus/source-versions/sv_governed_v1/fragments", json=fragment_body
    )
    assert first_fragments.status_code == replay_fragments.status_code == 201
    assert first_fragments.json() == replay_fragments.json()
    assert first_fragments.json()["revision"] == 2

    changed_fragments = {
        **fragment_body,
        "fragments": [{**fragment, "locator": "changed locator"}],
    }
    assert client.post(
        "/v2/corpus/source-versions/sv_governed_v1/fragments",
        json=changed_fragments,
    ).status_code == 409
    stale = {**fragment_body, "operation_id": _op()}
    assert client.post(
        "/v2/corpus/source-versions/sv_governed_v1/fragments", json=stale
    ).status_code == 409


def test_review_exact_replay_preserves_timestamp_and_changed_payload_conflicts(
    tmp_path: Path,
):
    client = _client(tmp_path)
    _created, ingested, _fragment_row = _create_and_ingest(client)
    review = {
        "operation_id": _op(),
        "expected_revision": ingested["revision"],
        "status": "approved",
        "reviewer": "human-reviewer",
        "note": "Manifest and rights checked",
    }
    first = client.post(
        "/v2/corpus/source-versions/sv_governed_v1/review", json=review
    )
    replay = client.post(
        "/v2/corpus/source-versions/sv_governed_v1/review", json=review
    )
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert first.json()["reviewed_at"] == replay.json()["reviewed_at"]
    assert client.post(
        "/v2/corpus/source-versions/sv_governed_v1/review",
        json={**review, "note": "changed"},
    ).status_code == 409


def test_manifest_mismatch_blocks_approval_and_post_approval_ingest(tmp_path: Path):
    client = _client(tmp_path)
    _created, ingested, _fragment_row = _create_and_ingest(
        client, source_version_id="sv_bad_manifest", manifest_checksum="0" * 64
    )
    rejected_approval = client.post(
        "/v2/corpus/source-versions/sv_bad_manifest/review",
        json={
            "operation_id": _op(),
            "expected_revision": ingested["revision"],
            "status": "approved",
            "reviewer": "human",
            "note": "should not pass",
        },
    )
    assert rejected_approval.status_code == 409

    _created, valid_ingested, _fragment_row = _create_and_ingest(
        client, source_version_id="sv_approved_locked"
    )
    approved = client.post(
        "/v2/corpus/source-versions/sv_approved_locked/review",
        json={
            "operation_id": _op(),
            "expected_revision": valid_ingested["revision"],
            "status": "approved",
            "reviewer": "human",
            "note": "checked",
        },
    )
    assert approved.status_code == 200, approved.text
    extra = _fragment(
        "sf_approved_locked_2", ordinal=2, locator="chapter 10, verse 2", text="late"
    )
    late = client.post(
        "/v2/corpus/source-versions/sv_approved_locked/fragments",
        json={
            "operation_id": _op(),
            "expected_revision": approved.json()["revision"],
            "fragments": [extra],
        },
    )
    assert late.status_code == 409


def test_review_history_is_append_only_and_terminal_states_cannot_reapprove(
    tmp_path: Path,
):
    client = _client(tmp_path)
    _created, ingested, fragment = _create_and_ingest(
        client, source_version_id="sv_terminal"
    )
    quarantined = client.post(
        "/v2/corpus/source-versions/sv_terminal/review",
        json={
            "operation_id": _op(),
            "expected_revision": ingested["revision"],
            "status": "quarantined",
            "reviewer": "human",
            "note": "provenance unresolved",
        },
    )
    assert quarantined.status_code == 200
    reapprove = client.post(
        "/v2/corpus/source-versions/sv_terminal/review",
        json={
            "operation_id": _op(),
            "expected_revision": quarantined.json()["revision"],
            "status": "approved",
            "reviewer": "human",
            "note": "cannot revise terminal record",
        },
    )
    assert reapprove.status_code == 409
    history = app.state.research_service.store.list_corpus_review_history(
        "source_version", "sv_terminal"
    )
    assert [(row["from_status"], row["to_status"]) for row in history] == [
        ("pending", "quarantined")
    ]

    # A fragment terminal transition is also immutable after its parent source is approved.
    _created, parent_ingested, child = _create_and_ingest(
        client, source_version_id="sv_fragment_terminal"
    )
    parent = client.post(
        "/v2/corpus/source-versions/sv_fragment_terminal/review",
        json={
            "operation_id": _op(), "expected_revision": parent_ingested["revision"],
            "status": "approved", "reviewer": "human", "note": "checked",
        },
    )
    assert parent.status_code == 200
    rejected = client.post(
        f"/v2/corpus/fragments/{child['fragment_id']}/review",
        json={
            "operation_id": _op(), "expected_revision": 1,
            "status": "rejected", "reviewer": "human", "note": "bad locator",
        },
    )
    assert rejected.status_code == 200
    assert client.post(
        f"/v2/corpus/fragments/{child['fragment_id']}/review",
        json={
            "operation_id": _op(), "expected_revision": rejected.json()["revision"],
            "status": "approved", "reviewer": "human", "note": "changed mind",
        },
    ).status_code == 409


def test_retrieval_evidence_binds_approval_provenance_and_seed_replays(tmp_path: Path):
    client = _client(tmp_path)
    _created, ingested, fragment = _create_and_ingest(
        client, source_version_id="sv_evidence"
    )
    source_review = client.post(
        "/v2/corpus/source-versions/sv_evidence/review",
        json={
            "operation_id": _op(), "expected_revision": ingested["revision"],
            "status": "approved", "reviewer": "source-reviewer", "note": "source checked",
        },
    ).json()
    fragment_review = client.post(
        f"/v2/corpus/fragments/{fragment['fragment_id']}/review",
        json={
            "operation_id": _op(), "expected_revision": 1,
            "status": "approved", "reviewer": "fragment-reviewer", "note": "quote checked",
        },
    ).json()

    # The retrieval projection carries the exact approval decision that authorized it.
    result = app.state.research_service.search_corpus("career karma sthana", limit=1)[0]
    payload = result.model_dump(mode="json")
    assert payload["source_approval_status"] == "approved"
    assert payload["source_reviewed_by"] == "source-reviewer"
    assert payload["source_reviewed_at"] == source_review["reviewed_at"]
    assert payload["fragment_approval_status"] == "approved"
    assert payload["fragment_reviewed_by"] == "fragment-reviewer"
    assert payload["fragment_reviewed_at"] == fragment_review["reviewed_at"]

    run = client.post(
        "/v2/research-runs",
        json={
            "operation_id": _op(), "expected_revision": 0,
            "question": "What career factors matter?",
            "birth_profile": {
                "name": "Evidence Fixture", "date": "1990-01-01", "time": "12:30:00",
                "place": {
                    "name": "Chennai", "latitude": 13.0827,
                    "longitude": 80.2707, "timezone": 5.5,
                },
            },
            "model_version": "test", "planner_version": "test",
            "corpus_version": "test", "contract_version": "2.0",
        },
    ).json()
    screened = client.post(
        f"/v2/research-runs/{run['run_id']}/screen",
        json={"operation_id": _op(), "expected_revision": run["revision"]},
    ).json()
    planned = client.post(
        f"/v2/research-runs/{run['run_id']}/plan",
        json={
            "operation_id": _op(), "expected_revision": screened["revision"],
            "intent": {"family": "career_factors_and_timing"},
            "classifier": {
                "classifier_model": "fixture", "classifier_version": "1",
                "prompt_hash": hashlib.sha256(b"fixture").hexdigest(),
            },
        },
    ).json()
    retrieved = client.post(
        f"/v2/research-runs/{run['run_id']}/retrieve",
        json={
            "operation_id": _op(), "expected_revision": planned["revision"],
            "query": "career karma sthana",
        },
    )
    assert retrieved.status_code == 200, retrieved.text
    persisted = app.state.research_service.store.list_evidence(run["run_id"])[0]["payload"]
    assert persisted["source_approval_status"] == "approved"
    assert persisted["source_reviewed_by"] == "source-reviewer"
    assert persisted["source_reviewed_at"] == source_review["reviewed_at"]
    assert persisted["fragment_approval_status"] == "approved"
    assert persisted["fragment_reviewed_by"] == "fragment-reviewer"
    assert persisted["fragment_reviewed_at"] == fragment_review["reviewed_at"]

    seed_store = ResearchStore(tmp_path / "seed")
    assert seed_store.seed_builtin_corpus() == 30
    before = seed_store.list_corpus_review_history()
    assert seed_store.seed_builtin_corpus() == 30
    assert seed_store.list_corpus_review_history() == before
