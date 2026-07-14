from __future__ import annotations

from jyotish_agent.doctrine.prashna_pack import (
    PrashnaOutcomeGraph,
    PrashnaRadicalityInput,
    PrashnaRadicalityProfile,
    PrashnaTestimony,
    classify_prashna_question,
    decide_prashna_clarification,
    evaluate_prashna_outcome,
    evaluate_prashna_radicality,
    prashna_aspect_profile,
    render_prashna_outcome,
)
from jyotish_agent.mcp_facade import JyotishMcpFacade
from jyotish_agent.prashna import calculate_prashna_aspect_geometry
from jyotish_agent.prashna_models import PrashnaAspectGeometryInput


def _graph() -> PrashnaOutcomeGraph:
    profile = PrashnaRadicalityProfile.model_validate(
        {
            "profile_id": "prasna_marga_radicality_v1",
            "school": "prasna_marga_baseline",
            "profile_kind": "baseline",
            "overlay_profile_id": None,
            "confidence_ceiling": 0.65,
            "criteria": [
                {
                    "criterion_id": criterion,
                    "source_id": "daivajna_vallabha_2003_scan",
                    "pdf_page": index,
                    "printed_page": index,
                    "page_sha256": str(index) * 64,
                    "source_locator": "fixture",
                }
                for index, criterion in enumerate(
                    (
                        "anchor_exact",
                        "question_not_test",
                        "question_once",
                        "question_proper_form",
                    ),
                    start=1,
                )
            ],
        }
    )
    radicality = evaluate_prashna_radicality(
        PrashnaRadicalityInput(
            anchor_state="sealed",
            question_relation="bounded_clarification",
            topic_state="single_safe",
            question_form="proper",
            intent_state="sincere",
            sources_admitted=True,
        ),
        profile,
    )
    route = classify_prashna_question("What blocks this work project?")
    geometry_profile = prashna_aspect_profile("tajika_nilakanthi_overlay").model_copy(
        update={"source_admitted": True, "source_refs": ("fixture:tajika",)}
    )
    geometry = calculate_prashna_aspect_geometry(
        PrashnaAspectGeometryInput(
            anchor_sha256="a" * 64,
            body_a="lagna_lord",
            body_b="primary_house_lord",
            longitude_a=10,
            longitude_b=68,
            speed_a=0.5,
            speed_b=1,
            aspect_degrees=60,
        ),
        geometry_profile,
    )
    return evaluate_prashna_outcome(
        radicality,
        route,
        geometry,
        testimonies=(
            PrashnaTestimony(
                testimony_id="support",
                polarity="assistance",
                confidence=0.5,
                fact_refs=("prashna.lagna.sign",),
                source_refs=("fixture:source",),
            ),
        ),
        available_fact_paths=route.required_fact_paths,
    )


def test_ru_en_quick_full_deep_are_validated_graph_only_and_non_categorical() -> None:
    graph = _graph()
    for language in ("ru", "en"):
        for depth in ("quick", "full", "deep"):
            report = render_prashna_outcome(
                graph, language=language, depth=depth, include_evidence=False
            )
            assert report.status == "completed"
            assert report.graph_sha256 == graph.graph_sha256
            assert report.evidence_appendix is None
            assert report.disclosure == "not_evaluated"
            assert "guarantee" not in report.model_dump_json().casefold()
            assert "гарантир" not in report.model_dump_json().casefold()


def test_evidence_is_opt_in_and_private_refs_fail_closed() -> None:
    graph = _graph()
    hidden = render_prashna_outcome(
        graph, language="en", depth="deep", include_evidence=False
    )
    shown = render_prashna_outcome(
        graph, language="en", depth="deep", include_evidence=True
    )
    assert hidden.evidence_appendix is None
    assert shown.evidence_appendix == graph.source_refs

    unsafe_payload = graph.model_dump(mode="json")
    unsafe_payload["source_refs"] = ["private_sources/secret.pdf?token=abc"]
    unsafe_payload["graph_sha256"] = "0" * 64
    unsafe = PrashnaOutcomeGraph.model_validate(unsafe_payload)
    blocked = render_prashna_outcome(
        unsafe, language="en", depth="deep", include_evidence=True
    )
    assert blocked.status == "unavailable"
    assert "secret" not in blocked.model_dump_json().casefold()


def test_substituted_graph_is_rejected_before_rendering() -> None:
    graph = _graph().model_copy(update={"score": -1.0})
    report = render_prashna_outcome(
        graph, language="en", depth="full", include_evidence=False
    )
    assert report.status == "unavailable"
    assert report.reason_code == "GRAPH_IDENTITY_INVALID"
    assert report.reasoning == ()


def test_retry_and_bounded_clarification_reuse_anchor_but_material_change_does_not() -> (
    None
):
    same = decide_prashna_clarification(
        anchor_sha256="a" * 64,
        original_fingerprint="b" * 64,
        current_fingerprint="c" * 64,
        relation="bounded_clarification",
    )
    changed = decide_prashna_clarification(
        anchor_sha256="a" * 64,
        original_fingerprint="b" * 64,
        current_fingerprint="d" * 64,
        relation="material_mismatch",
    )
    assert same.action == "reuse_sealed_anchor"
    assert same.anchor_sha256 == "a" * 64
    assert changed.action == "create_new_anchor"
    assert changed.anchor_sha256 is None


def test_malformed_adapter_input_never_reflects_secret(tmp_path) -> None:
    facade = JyotishMcpFacade(tmp_path, None)
    result = facade.prashna_full_render_payload(
        {"graph": {"private_token": "SECRET-ARGON"}, "language": "en"}
    )
    rendered = str(result)
    assert result["status"] == "unavailable"
    assert result["error_code"] == "INPUT_INVALID"
    assert "ARGON" not in rendered
    assert "private_token" not in rendered
