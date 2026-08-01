from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import jyotish_agent.muhurta_evaluation as muhurta_evaluation
from jyotish_agent.muhurta_evaluation import MuhurtaHeldOutCorpusError


ROOT = Path(__file__).parents[2]
CORPUS = ROOT / "eval/muhurta/independent-held-out-v1.json"
MANIFEST = ROOT / "eval/muhurta/independent-held-out-v1-checksums.json"


def _reseal(tmp_path: Path, payload: dict[str, object]) -> tuple[Path, Path]:
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


def test_muhurta_independent_held_out_corpus_is_executable() -> None:
    evaluate = getattr(
        muhurta_evaluation, "evaluate_muhurta_held_out_cases", None
    )

    assert callable(evaluate)
    assert evaluate(allow_held_out=True) == {
        "corpus_id": "muhurta_independent_held_out_v1",
        "corpus_sha256": "90bb92e7aef06be67ba38d93ffdc5477383aca11547987049bcbe0c9a198b0b1",
        "corpus_manifest_sha256": "e6643be2f730e67b2cd6b80f64cfe46894240bb112a0ff26cae22a0c390c2e07",
        "compiled_profile_sha256": "ecba14ace48d508b0a4789262cc67a4078c72bdd244e6d0a629499b67b7e8f81",
        "source_admission_mode": "synthetic_inputs_against_admitted_private_baseline",
        "status": "passed",
        "case_count": 19,
        "passed_count": 19,
        "failed_count": 0,
        "material_error_count": 0,
        "material_error_rate": 0.0,
        "covered_categories": [
            "eligibility",
            "personalization",
            "ranking",
            "route",
            "skipped_date_search",
        ],
        "covered_profiles": [
            "creative_production",
            "focused_work",
            "general_private_task",
            "low_risk_travel_planning",
            "product_launch_communication",
            "study_learning",
        ],
        "failures": [],
    }


def test_muhurta_held_out_execution_requires_explicit_opt_in() -> None:
    with pytest.raises(ValueError, match="allow_held_out=True"):
        muhurta_evaluation.evaluate_muhurta_held_out_cases()


def test_muhurta_held_out_checksum_rejects_unsealed_changes(tmp_path: Path) -> None:
    corpus = tmp_path / CORPUS.name
    corpus.write_bytes(CORPUS.read_bytes() + b"\n")

    with pytest.raises(MuhurtaHeldOutCorpusError, match="checksum mismatch"):
        muhurta_evaluation.evaluate_muhurta_held_out_cases(
            corpus_path=corpus,
            manifest_path=MANIFEST,
            allow_held_out=True,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("used_for_tuning", True),
        ("compiled_profile_sha256", "f" * 64),
        ("source_admission_mode", "production_outcomes"),
    ],
)
def test_muhurta_held_out_provenance_substitution_is_rejected_after_reseal(
    tmp_path: Path, field: str, value: object
) -> None:
    payload = json.loads(CORPUS.read_text(encoding="utf-8"))
    payload[field] = value
    corpus, manifest = _reseal(tmp_path, payload)

    with pytest.raises(MuhurtaHeldOutCorpusError, match="provenance"):
        muhurta_evaluation.evaluate_muhurta_held_out_cases(
            corpus_path=corpus,
            manifest_path=manifest,
            allow_held_out=True,
        )


def test_muhurta_held_out_incomplete_coverage_is_rejected_after_reseal(
    tmp_path: Path,
) -> None:
    payload = json.loads(CORPUS.read_text(encoding="utf-8"))
    payload["cases"][16]["coverage_tags"] = ["ranking"]
    corpus, manifest = _reseal(tmp_path, payload)

    with pytest.raises(MuhurtaHeldOutCorpusError, match="incomplete required coverage"):
        muhurta_evaluation.evaluate_muhurta_held_out_cases(
            corpus_path=corpus,
            manifest_path=manifest,
            allow_held_out=True,
        )


def test_muhurta_held_out_failure_does_not_echo_input_payload(
    tmp_path: Path,
) -> None:
    payload = json.loads(CORPUS.read_text(encoding="utf-8"))
    payload["cases"][0]["input"]["activity"] = "deep work codename argon"
    payload["cases"][0]["expected"]["reason_code"] = "WRONG_EXPECTATION"
    corpus, manifest = _reseal(tmp_path, payload)

    result = muhurta_evaluation.evaluate_muhurta_held_out_cases(
        corpus_path=corpus,
        manifest_path=manifest,
        allow_held_out=True,
    )

    assert result["status"] == "failed"
    assert result["material_error_count"] == 1
    assert result["material_error_rate"] == 0.052632
    assert "argon" not in json.dumps(result).casefold()
