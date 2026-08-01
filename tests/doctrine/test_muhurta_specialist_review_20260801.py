from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from jyotish_agent.doctrine.specialist_review import (
    MuhurtaSpecialistDecision,
    MuhurtaSpecialistReviewHandoff,
    MuhurtaSpecialistReviewReport,
    MuhurtaSpecialistReviewResponse,
    build_muhurta_specialist_review_handoff,
    evaluate_muhurta_specialist_review,
    muhurta_specialist_review_response_schema,
)
from jyotish_agent.research_store import canonical_json


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/run_muhurta_specialist_review.py"
HANDOFF = ROOT / "docs/evidence/doctrine/muhurta-specialist-review-handoff.json"
RESPONSE_SCHEMA = (
    ROOT / "docs/evidence/doctrine/muhurta-specialist-review-response.schema.json"
)


def _response(
    handoff: MuhurtaSpecialistReviewHandoff,
    *,
    decisions: tuple[MuhurtaSpecialistDecision, ...] | None = None,
) -> MuhurtaSpecialistReviewResponse:
    return MuhurtaSpecialistReviewResponse(
        review_id="muhurta_review_release_gate_v1",
        handoff_sha256=handoff.handoff_sha256,
        reviewer_name="Qualified Reviewer",
        reviewer_role="electional_astrology_specialist",
        qualification_note="Independent practitioner with electional review scope.",
        independence_attested=True,
        source_access_attested=True,
        contains_source_text=False,
        decisions=decisions
        or tuple(
            MuhurtaSpecialistDecision(
                subject_type=subject.subject_type,
                subject_id=subject.subject_id,
                subject_sha256=subject.subject_sha256,
                decision="approved",
            )
            for subject in handoff.subjects
        ),
    )


def test_tracked_handoff_is_exact_complete_and_contains_no_private_material() -> None:
    generated = build_muhurta_specialist_review_handoff()
    recorded = MuhurtaSpecialistReviewHandoff.model_validate_json(HANDOFF.read_text())

    assert generated == recorded
    assert generated.ready_for_external_review is True
    assert generated.external_review_status == "missing"
    assert generated.subject_count == 9
    assert sum(item.subject_type == "rule" for item in generated.subjects) == 2
    assert sum(item.subject_type == "profile" for item in generated.subjects) == 6
    assert (
        sum(item.subject_type == "overlay_comparison" for item in generated.subjects)
        == 1
    )
    rendered = generated.model_dump_json()
    assert "private_sources/" not in rendered
    assert "local_file" not in rendered
    assert ".pdf" not in rendered
    assert "overlay:bv_raman_modern_overlay_v1:rahu_kala" in rendered
    assert generated.response_schema_ref.endswith("response.schema.json")
    assert json.loads(RESPONSE_SCHEMA.read_text()) == (
        muhurta_specialist_review_response_schema()
    )
    assert json.loads(RESPONSE_SCHEMA.read_text())["additionalProperties"] is False


def test_complete_approved_review_passes_without_exporting_reviewer_identity() -> None:
    handoff = build_muhurta_specialist_review_handoff()
    response = _response(handoff)
    report = evaluate_muhurta_specialist_review(handoff, response)

    assert report.gate_status == "passed"
    assert report.specialist_review_complete is True
    assert report.reviewed_count == report.approved_count == 9
    assert report.amended_count == report.rejected_count == 0
    assert report.blockers == ()
    rendered = report.model_dump_json()
    assert "Qualified Reviewer" not in rendered
    assert "Independent practitioner" not in rendered


def test_partial_amended_and_rejected_reviews_remain_fail_closed() -> None:
    handoff = build_muhurta_specialist_review_handoff()
    first, second = handoff.subjects[:2]

    partial = _response(
        handoff,
        decisions=(
            MuhurtaSpecialistDecision(
                subject_type=first.subject_type,
                subject_id=first.subject_id,
                subject_sha256=first.subject_sha256,
                decision="approved",
            ),
        ),
    )
    partial_report = evaluate_muhurta_specialist_review(handoff, partial)
    assert partial_report.gate_status == "missing"
    assert partial_report.blockers == ("missing_subject_decisions:8",)

    amended = _response(
        handoff,
        decisions=tuple(
            MuhurtaSpecialistDecision(
                subject_type=subject.subject_type,
                subject_id=subject.subject_id,
                subject_sha256=subject.subject_sha256,
                decision="amended" if subject == first else "approved",
                amendment_summary=(
                    "Narrow the applicability before re-review."
                    if subject == first
                    else None
                ),
            )
            for subject in handoff.subjects
        ),
    )
    amended_report = evaluate_muhurta_specialist_review(handoff, amended)
    assert amended_report.gate_status == "missing"
    assert amended_report.blockers == ("amendments_pending_implementation:1",)

    rejected = _response(
        handoff,
        decisions=(
            MuhurtaSpecialistDecision(
                subject_type=second.subject_type,
                subject_id=second.subject_id,
                subject_sha256=second.subject_sha256,
                decision="rejected",
                note="Source does not support this exact scope.",
            ),
        ),
    )
    rejected_report = evaluate_muhurta_specialist_review(handoff, rejected)
    assert rejected_report.gate_status == "failed"
    assert rejected_report.blockers == (
        "missing_subject_decisions:8",
        "rejected_subjects:1",
    )


def test_handoff_and_response_substitution_are_rejected() -> None:
    handoff = build_muhurta_specialist_review_handoff()
    payload = handoff.model_dump(mode="json")
    payload["subjects"][0]["artifact_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="not content-addressed"):
        MuhurtaSpecialistReviewHandoff.model_validate(payload)

    coordinated = handoff.model_dump(mode="json")
    coordinated["subjects"][0]["current_status"] = "available"
    subject_payload = dict(coordinated["subjects"][0])
    subject_payload.pop("subject_sha256")
    coordinated["subjects"][0]["subject_sha256"] = _hash(subject_payload)
    handoff_payload = dict(coordinated)
    handoff_payload.pop("handoff_sha256")
    coordinated["handoff_sha256"] = _hash(handoff_payload)
    substituted = MuhurtaSpecialistReviewHandoff.model_validate(coordinated)
    with pytest.raises(ValueError, match="does not match packaged artifacts"):
        evaluate_muhurta_specialist_review(substituted, _response(substituted))

    subject = handoff.subjects[0]
    response = _response(
        handoff,
        decisions=(
            MuhurtaSpecialistDecision(
                subject_type=subject.subject_type,
                subject_id=subject.subject_id,
                subject_sha256="0" * 64,
                decision="approved",
            ),
        ),
    )
    with pytest.raises(ValueError, match="changed the subject identity"):
        evaluate_muhurta_specialist_review(handoff, response)


def test_response_schema_rejects_raw_content_and_unqualified_shortcuts() -> None:
    handoff = build_muhurta_specialist_review_handoff()
    valid = json.loads(_response(handoff).model_dump_json())
    valid["source_excerpt"] = "private copyrighted text"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        MuhurtaSpecialistReviewResponse.model_validate(valid)

    valid = json.loads(_response(handoff).model_dump_json())
    valid["source_access_attested"] = False
    with pytest.raises(ValidationError, match="Input should be True"):
        MuhurtaSpecialistReviewResponse.model_validate(valid)

    subject = handoff.subjects[0]
    with pytest.raises(ValidationError, match="amendment summary"):
        MuhurtaSpecialistDecision(
            subject_type=subject.subject_type,
            subject_id=subject.subject_id,
            subject_sha256=subject.subject_sha256,
            decision="amended",
        )


def test_cli_generates_exact_handoff_and_fails_closed_without_secret_echo(
    tmp_path: Path,
) -> None:
    generated_path = tmp_path / "handoff.json"
    schema_path = tmp_path / "response-schema.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "handoff",
            "--json-out",
            str(generated_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert MuhurtaSpecialistReviewHandoff.model_validate_json(
        generated_path.read_text()
    ) == build_muhurta_specialist_review_handoff()
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "response-schema",
            "--json-out",
            str(schema_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert json.loads(schema_path.read_text()) == (
        muhurta_specialist_review_response_schema()
    )

    response_path = tmp_path / "response.json"
    report_path = tmp_path / "report.json"
    handoff = build_muhurta_specialist_review_handoff()
    response_path.write_text(_response(handoff).model_dump_json(), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "evaluate",
            str(generated_path),
            str(response_path),
            "--json-out",
            str(report_path),
            "--require-approved",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert MuhurtaSpecialistReviewReport.model_validate_json(
        report_path.read_text()
    ).gate_status == "passed"

    first = handoff.subjects[0]
    partial = _response(
        handoff,
        decisions=(
            MuhurtaSpecialistDecision(
                subject_type=first.subject_type,
                subject_id=first.subject_id,
                subject_sha256=first.subject_sha256,
                decision="approved",
            ),
        ),
    )
    response_path.write_text(partial.model_dump_json(), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "evaluate",
            str(generated_path),
            str(response_path),
            "--json-out",
            str(report_path),
            "--require-approved",
        ],
        cwd=ROOT,
        check=False,
    )
    assert completed.returncode == 2

    rejected = _response(
        handoff,
        decisions=(
            MuhurtaSpecialistDecision(
                subject_type=first.subject_type,
                subject_id=first.subject_id,
                subject_sha256=first.subject_sha256,
                decision="rejected",
                note="Exact source scope was rejected.",
            ),
        ),
    )
    response_path.write_text(rejected.model_dump_json(), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "evaluate",
            str(generated_path),
            str(response_path),
            "--json-out",
            str(report_path),
            "--require-approved",
        ],
        cwd=ROOT,
        check=False,
    )
    assert completed.returncode == 3

    response_path.write_text(_response(handoff).model_dump_json(), encoding="utf-8")
    invalid = json.loads(response_path.read_text())
    invalid["source_excerpt"] = "SUPER-PRIVATE-REVIEW"
    response_path.write_text(json.dumps(invalid), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "evaluate",
            str(generated_path),
            str(response_path),
            "--json-out",
            str(report_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    assert completed.stderr == "SPECIALIST_REVIEW_INPUT_INVALID\n"
    assert "SUPER-PRIVATE-REVIEW" not in completed.stderr


def _hash(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
