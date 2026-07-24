import pytest

from app.qa_matrix import QaMatrixError, build_qa_matrix, validate_qa_coverage


def test_qa_matrix_scopes_checks_by_region_origin_changed_layers_and_risk():
    execution_map = {
        "regions": [
            {"region_id": "ui", "media_origin": "opaque_ui", "changed_layers": ["ui"]},
            {"region_id": "generated-ui", "media_origin": "generated_ui", "changed_layers": ["ui"]},
            {"region_id": "face", "media_origin": "generated", "changed_layers": ["model"]},
            {"region_id": "hand", "media_origin": "generated", "changed_layers": ["product"]},
        ]
    }
    source_contract = {
        "regions": [
            {"region_id": "face", "close_face": True, "speaking": True},
            {"region_id": "hand", "handheld_product": True},
        ]
    }

    matrix = build_qa_matrix(execution_map, source_contract)
    by_id = {row["region_id"]: row for row in matrix["regions"]}

    assert by_id["ui"]["required_checks"] == ["technical_stream", "timeline_placement"]
    assert "ui_ocr_layout" in by_id["generated-ui"]["required_checks"]
    assert "identity_consistency" in by_id["face"]["required_checks"]
    assert "lip_sync" in by_id["face"]["required_checks"]
    assert "hand_product_contact" in by_id["hand"]["required_checks"]
    assert matrix["final_technical_qc"] is True


def test_qa_receipt_requires_every_mandatory_check_and_rejects_opaque_semantic_qc():
    matrix = {
        "regions": [
            {
                "region_id": "ui",
                "media_origin": "opaque_ui",
                "required_checks": ["technical_stream", "timeline_placement"],
                "skipped_checks": ["ui_ocr_layout"],
            }
        ],
        "final_technical_qc": True,
    }
    with pytest.raises(QaMatrixError, match="QA_COVERAGE_REQUIRED"):
        validate_qa_coverage(
            qa_receipt={
                "regions": [{"region_id": "ui", "checks": {"technical_stream": {"passed": True}}}],
                "final_technical": {"passed": True},
            },
            qa_matrix=matrix,
        )


def test_qa_receipt_rejects_duplicate_or_unknown_regions_instead_of_ignoring_them():
    matrix = {
        "regions": [
            {
                "region_id": "body",
                "media_origin": "generated",
                "required_checks": ["timeline_placement"],
                "skipped_checks": [],
            }
        ],
        "final_technical_qc": True,
    }
    with pytest.raises(QaMatrixError, match="QA_COVERAGE_REQUIRED"):
        validate_qa_coverage(
            qa_receipt={
                "regions": [
                    {"region_id": "body", "checks": {"timeline_placement": {"passed": True}}},
                    {"region_id": "foreign", "checks": {"timeline_placement": {"passed": True}}},
                ],
                "final_technical": {"passed": True},
            },
            qa_matrix=matrix,
        )


def test_qa_receipt_rejects_semantic_checks_for_an_opaque_region():
    matrix = {
        "regions": [
            {
                "region_id": "ui",
                "media_origin": "opaque_ui",
                "required_checks": ["technical_stream", "timeline_placement"],
                "skipped_checks": ["ui_ocr_layout"],
            }
        ],
        "final_technical_qc": True,
    }
    with pytest.raises(QaMatrixError, match="QA_OPAQUE_SEMANTIC_CHECK_FORBIDDEN"):
        validate_qa_coverage(
            qa_receipt={
                "regions": [
                    {
                        "region_id": "ui",
                        "checks": {
                            "technical_stream": {"passed": True},
                            "timeline_placement": {"passed": True},
                            "ui_ocr_layout": {"passed": True},
                        },
                    }
                ],
                "final_technical": {"passed": True},
            },
            qa_matrix=matrix,
        )
