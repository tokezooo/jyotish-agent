from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from jyotish_agent.jaimini_evaluation import (
    HeldOutCorpusError,
    evaluate_held_out_geometry,
)


ROOT = Path(__file__).parents[1]
CORPUS = ROOT / "eval/jaimini/geometry-held-out-v1.json"
MANIFEST = ROOT / "eval/jaimini/geometry-held-out-v1-checksums.json"


def _write_manifest(path: Path, corpus: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "algorithm": "sha256",
                "files": {corpus.name: hashlib.sha256(corpus.read_bytes()).hexdigest()},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _mutated_paths(tmp_path: Path, mutate) -> tuple[Path, Path]:
    payload = json.loads(CORPUS.read_text(encoding="utf-8"))
    mutate(payload)
    corpus = tmp_path / CORPUS.name
    corpus.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    manifest = tmp_path / MANIFEST.name
    _write_manifest(manifest, corpus)
    return corpus, manifest


def test_hand_authored_geometry_corpus_passes_through_production_boundaries() -> None:
    report = evaluate_held_out_geometry(
        corpus_path=CORPUS, manifest_path=MANIFEST, allow_held_out=True
    )

    assert report == {
        "corpus_id": "jaimini_geometry_held_out_v1",
        "case_count": 26,
        "passed_count": 26,
        "failed_count": 0,
        "failures": [],
    }


def test_held_out_execution_requires_an_explicit_gate() -> None:
    with pytest.raises(ValueError, match="allow_held_out=True"):
        evaluate_held_out_geometry(corpus_path=CORPUS, manifest_path=MANIFEST)


def test_evaluator_dispatches_by_rule_family_not_case_id(tmp_path: Path) -> None:
    corpus, manifest = _mutated_paths(
        tmp_path, lambda payload: payload["cases"][0].update(id="renamed_oracle_case")
    )

    report = evaluate_held_out_geometry(
        corpus_path=corpus, manifest_path=manifest, allow_held_out=True
    )

    assert report["failed_count"] == 0


def test_checksum_drift_is_rejected_before_execution(tmp_path: Path) -> None:
    corpus = tmp_path / CORPUS.name
    corpus.write_bytes(CORPUS.read_bytes() + b"\n")
    manifest = tmp_path / MANIFEST.name
    manifest.write_bytes(MANIFEST.read_bytes())

    with pytest.raises(HeldOutCorpusError, match="checksum mismatch"):
        evaluate_held_out_geometry(
            corpus_path=corpus, manifest_path=manifest, allow_held_out=True
        )


def test_expected_value_drift_reports_a_failed_oracle_case(tmp_path: Path) -> None:
    corpus, manifest = _mutated_paths(
        tmp_path,
        lambda payload: payload["cases"][0].update(expected={"AK": "Sun"}),
    )

    report = evaluate_held_out_geometry(
        corpus_path=corpus, manifest_path=manifest, allow_held_out=True
    )

    assert report["failed_count"] == 1
    assert report["failures"] == [
        {"rule_family": "karakas", "expected": {"AK": "Sun"}, "observed": {
            "AK": "Mars", "AmK": "Venus", "BK": "Mercury", "MK": "Sun",
            "PK": "Jupiter", "GK": "Moon", "DK": "Saturn",
        }}
    ]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda payload: payload.pop("school"), "school identity"),
        (lambda payload: payload.update(school="wrong-school"), "school identity"),
        (lambda payload: payload.update(rule_profile_id="wrong_profile"), "profile identity"),
        (lambda payload: payload.update(rule_profile_sha256="0" * 64), "profile SHA-256"),
        (lambda payload: payload["cases"].append(payload["cases"][0]), "duplicate case ID"),
        (lambda payload: payload.update(used_for_tuning=True), "used_for_tuning"),
        (
            lambda payload: payload["cases"][0]["input"].update(
                source_path="private_sources/forbidden.pdf"
            ),
            "synthetic scalar/sign inputs",
        ),
    ],
)
def test_corpus_identity_and_privacy_mutations_fail_closed(
    tmp_path: Path, mutate, message: str
) -> None:
    corpus, manifest = _mutated_paths(tmp_path, mutate)

    with pytest.raises(HeldOutCorpusError, match=message):
        evaluate_held_out_geometry(
            corpus_path=corpus, manifest_path=manifest, allow_held_out=True
        )
