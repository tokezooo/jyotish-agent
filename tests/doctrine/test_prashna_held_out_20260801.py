from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import jyotish_agent.doctrine.prashna_pack as prashna_pack
from jyotish_agent.doctrine.prashna_pack import PrashnaHeldOutCorpusError


ROOT = Path(__file__).parents[2]
CORPUS = ROOT / "eval/prashna/questions-held-out-v1.json"
MANIFEST = ROOT / "eval/prashna/questions-held-out-v1-checksums.json"


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


def test_prashna_held_out_questions_cover_safe_and_adversarial_routes() -> None:
    evaluate = getattr(prashna_pack, "evaluate_prashna_held_out_questions", None)

    assert callable(evaluate)
    result = evaluate(allow_held_out=True)

    assert result == {
        "corpus_id": "prashna_questions_held_out_v1",
        "corpus_sha256": "ea337e395aadd08f7e7498293e3e3e388c79aa33ca130250aa333ee29a744303",
        "corpus_manifest_sha256": "7f320ba34fadc878ee028826a04d4b0b17b980614e4be212a262fdd552e5378b",
        "radicality_profile_sha256": "259221f4861fc31727e00772520d27f81a1d09816b538cb885d9ae84eb3b20ea",
        "source_admission_mode": "synthetic_test_fixture_only",
        "status": "passed",
        "question_count": 12,
        "passed_count": 12,
        "failed_count": 0,
        "material_error_rate": 0.0,
        "no_answer_rate": 0.125,
        "covered_route_statuses": [
            "ambiguous",
            "composite",
            "high_stakes",
            "supported",
            "unsupported",
        ],
        "covered_profiles": [
            "communication_contact",
            "general_low_risk_outcome",
            "lost_object",
            "work_project_status",
        ],
        "failures": [],
    }


def test_prashna_held_out_execution_requires_explicit_opt_in() -> None:
    with pytest.raises(ValueError, match="allow_held_out=True"):
        prashna_pack.evaluate_prashna_held_out_questions()


def test_prashna_held_out_checksum_rejects_unsealed_changes(tmp_path: Path) -> None:
    corpus = tmp_path / CORPUS.name
    corpus.write_bytes(CORPUS.read_bytes() + b"\n")

    with pytest.raises(PrashnaHeldOutCorpusError, match="checksum mismatch"):
        prashna_pack.evaluate_prashna_held_out_questions(
            corpus_path=corpus,
            manifest_path=MANIFEST,
            allow_held_out=True,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("used_for_tuning", True),
        ("source_admission_mode", "production_admitted"),
    ],
)
def test_prashna_held_out_provenance_substitution_is_rejected_after_reseal(
    tmp_path: Path, field: str, value: object
) -> None:
    payload = json.loads(CORPUS.read_text(encoding="utf-8"))
    payload[field] = value
    corpus, manifest = _reseal(tmp_path, payload)

    with pytest.raises(PrashnaHeldOutCorpusError, match="provenance"):
        prashna_pack.evaluate_prashna_held_out_questions(
            corpus_path=corpus,
            manifest_path=manifest,
            allow_held_out=True,
        )


def test_prashna_held_out_failure_does_not_echo_question_text(
    tmp_path: Path,
) -> None:
    payload = json.loads(CORPUS.read_text(encoding="utf-8"))
    payload["cases"][0]["question"] = "What blocks project Secret-Codename-Argon work?"
    payload["cases"][0]["outcome_expected"]["judgment"] = "mixed"
    corpus, manifest = _reseal(tmp_path, payload)

    result = prashna_pack.evaluate_prashna_held_out_questions(
        corpus_path=corpus,
        manifest_path=manifest,
        allow_held_out=True,
    )

    assert result["status"] == "failed"
    assert result["failed_count"] == 1
    assert result["material_error_rate"] == 0.083333
    assert "Secret-Codename-Argon" not in json.dumps(result)
