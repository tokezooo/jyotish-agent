from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import jyotish_agent.jaimini_evaluation as jaimini_evaluation
from jyotish_agent.jaimini_evaluation import HandWorkedCorpusError


ROOT = Path(__file__).parents[2]
CORPUS = ROOT / "eval/jaimini/hand-worked-v1.json"
MANIFEST = ROOT / "eval/jaimini/hand-worked-v1-checksums.json"


def _resealed_corpus(tmp_path: Path, payload: dict[str, object]) -> tuple[Path, Path]:
    corpus = tmp_path / CORPUS.name
    corpus.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    manifest = tmp_path / MANIFEST.name
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "algorithm": "sha256",
                "files": {
                    corpus.name: hashlib.sha256(corpus.read_bytes()).hexdigest()
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return corpus, manifest


def test_hand_worked_corpus_runs_literal_multi_rule_cases() -> None:
    evaluate = getattr(jaimini_evaluation, "evaluate_hand_worked_cases", None)

    assert callable(evaluate)
    result = evaluate(allow_hand_worked=True)

    assert result == {
        "corpus_id": "jaimini_hand_worked_v1",
        "corpus_sha256": "cafa1778659323c261798a3065ddbb8f64947538cc0a5412744b69b672c96a0a",
        "rule_profile_sha256": "8a97c43e8438351ae73a59fed731cf5e48ef3c25c347ddf3570dea5818696b58",
        "source_map_sha256": "5e494796568722aff34fdc6a9fc43634809928d5afb6c1771574119c04ea3095",
        "status": "passed",
        "case_count": 5,
        "check_count": 11,
        "passed_count": 11,
        "failed_count": 0,
        "covered_rule_families": [
            "argala",
            "arudha",
            "chara_dasha",
            "co_lord",
            "karakas",
            "rasi_drishti",
            "special_lagnas",
        ],
        "failures": [],
    }


def test_hand_worked_execution_requires_explicit_opt_in() -> None:
    with pytest.raises(ValueError, match="allow_hand_worked=True"):
        jaimini_evaluation.evaluate_hand_worked_cases()


def test_hand_worked_checksum_rejects_unsealed_changes(tmp_path: Path) -> None:
    corpus = tmp_path / CORPUS.name
    corpus.write_bytes(CORPUS.read_bytes() + b"\n")

    with pytest.raises(HandWorkedCorpusError, match="checksum mismatch"):
        jaimini_evaluation.evaluate_hand_worked_cases(
            corpus_path=corpus,
            manifest_path=MANIFEST,
            allow_hand_worked=True,
        )


def test_runtime_derived_expected_state_is_rejected_after_reseal(
    tmp_path: Path,
) -> None:
    payload = json.loads(CORPUS.read_text(encoding="utf-8"))
    payload["cases"][0]["runtime_derived_expected"] = True
    corpus, manifest = _resealed_corpus(tmp_path, payload)

    with pytest.raises(HandWorkedCorpusError, match="provenance"):
        jaimini_evaluation.evaluate_hand_worked_cases(
            corpus_path=corpus,
            manifest_path=manifest,
            allow_hand_worked=True,
        )


def test_literal_expected_mismatch_is_reported_not_rewritten(tmp_path: Path) -> None:
    payload = json.loads(CORPUS.read_text(encoding="utf-8"))
    payload["cases"][0]["checks"][0]["expected"] = 8
    corpus, manifest = _resealed_corpus(tmp_path, payload)

    result = jaimini_evaluation.evaluate_hand_worked_cases(
        corpus_path=corpus,
        manifest_path=manifest,
        allow_hand_worked=True,
    )

    assert result["status"] == "failed"
    assert result["failed_count"] == 1
    assert result["failures"][0]["check_id"] == "hw_aries_arudha_same"
