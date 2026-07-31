from __future__ import annotations

import copy
import hashlib
import json

import pytest

from server import runninghub_standard_contract as contract


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _binding(
    index: int,
    role: str,
    *,
    artifact_name: str,
    cut_ids: list[str],
    page: int | None = None,
    approval_set_sha256: str | None = None,
    purpose: str,
) -> dict[str, object]:
    return {
        "image_index": index,
        "tag": f"@Image{index}",
        "role": role,
        "artifact_name": artifact_name,
        "sha256": _sha(artifact_name),
        "url": f"https://media.example/{artifact_name}",
        "cut_ids": cut_ids,
        "page": page,
        "approval_set_sha256": approval_set_sha256,
        "purpose": purpose,
    }


def _case(*, storyboard_pages: int = 2, extra_images: int = 0) -> tuple[dict[str, object], dict[str, object]]:
    approval_sha = _sha("approved-board-set")
    bindings = [
        _binding(
            1,
            "new_model_identity",
            artifact_name="new-model.png",
            cut_ids=["C01", "C02", "C03", "C04"],
            purpose="replace face, hair, and body identity only",
        ),
        _binding(
            2,
            "product_or_app_truth",
            artifact_name="product.png",
            cut_ids=["C02", "C03"],
            purpose="lock product shape, packaging, and logo",
        ),
    ]
    page_cuts = [["C01", "C02"], ["C03", "C04"]]
    for page in range(1, storyboard_pages + 1):
        bindings.append(
            _binding(
                len(bindings) + 1,
                "director_storyboard",
                artifact_name=f"segment_01_v1_page_{page}.png",
                cut_ids=page_cuts[page - 1],
                page=page,
                approval_set_sha256=approval_sha,
                purpose=f"approved director storyboard page {page}",
            )
        )
    for extra in range(extra_images):
        index = len(bindings) + 1
        bindings.append(
            _binding(
                index,
                "additional_reference",
                artifact_name=f"extra-{extra + 1}.png",
                cut_ids=["C04"],
                purpose=f"lock the verified additional prop reference {extra + 1}",
            )
        )
    prompt = " ".join(f"{row['tag']} {row['purpose']}." for row in bindings)
    prompt += " @Video1 controls source motion. @Audio1 controls the approved audio window."
    payload = {
        "prompt": prompt,
        "imageUrls": [str(row["url"]) for row in bindings],
        "videoUrls": ["https://media.example/source-slice.mp4"],
        "audioUrls": ["https://media.example/music-slice.wav"],
    }
    sidecar = {
        "schema_version": "usfr-multimodal-reference-binding/v2",
        "ordered_image_urls": list(payload["imageUrls"]),
        "approval_set_sha256": approval_sha,
        "image_bindings": bindings,
        "slot_policy": "continuous-present-role-order/v1",
        "forbidden_artifact_names": ["seedance_execution_carrier.png"],
    }
    return payload, sidecar


def _validate(payload: dict[str, object], sidecar: dict[str, object]) -> None:
    contract.validate_image_reference_binding(payload, sidecar)


def test_accepts_one_through_nine_images_and_keeps_video_audio_namespaces_independent() -> None:
    for count in range(1, 10):
        payload, sidecar = _case(storyboard_pages=2, extra_images=5)
        bindings = sidecar["image_bindings"][:count]
        sidecar["image_bindings"] = bindings
        sidecar["ordered_image_urls"] = [row["url"] for row in bindings]
        payload["imageUrls"] = list(sidecar["ordered_image_urls"])
        payload["prompt"] = " ".join(f"{row['tag']} {row['purpose']}." for row in bindings)
        payload["prompt"] += " @Video1 source motion. @Audio1 approved audio."
        if not any(row["role"] == "director_storyboard" for row in bindings):
            sidecar["approval_set_sha256"] = None
        _validate(payload, sidecar)


def test_binds_both_approved_storyboard_pages_with_page_and_cut_scope() -> None:
    payload, sidecar = _case(storyboard_pages=2)
    _validate(payload, sidecar)
    storyboards = [row for row in sidecar["image_bindings"] if row["role"] == "director_storyboard"]
    assert [row["page"] for row in storyboards] == [1, 2]
    assert [row["cut_ids"] for row in storyboards] == [["C01", "C02"], ["C03", "C04"]]


@pytest.mark.parametrize("field", ["image_index", "tag", "sha256", "role", "artifact_name", "cut_ids", "purpose"])
def test_every_uploaded_image_requires_complete_machine_binding(field: str) -> None:
    payload, sidecar = _case()
    del sidecar["image_bindings"][0][field]
    with pytest.raises(contract.RunningHubStandardPayloadError):
        _validate(payload, sidecar)


def test_rejects_uploaded_image_not_referenced_by_prompt() -> None:
    payload, sidecar = _case()
    payload["prompt"] = str(payload["prompt"]).replace("@Image4", "the second storyboard")
    with pytest.raises(contract.RunningHubStandardPayloadError, match="prompt"):
        _validate(payload, sidecar)


def test_rejects_prompt_reference_to_missing_image() -> None:
    payload, sidecar = _case()
    payload["prompt"] = f"{payload['prompt']} @Image5 does something."
    with pytest.raises(contract.RunningHubStandardPayloadError, match="prompt"):
        _validate(payload, sidecar)


def test_rejects_url_order_different_from_binding_order() -> None:
    payload, sidecar = _case()
    payload["imageUrls"][0], payload["imageUrls"][1] = payload["imageUrls"][1], payload["imageUrls"][0]
    with pytest.raises(contract.RunningHubStandardPayloadError, match="order"):
        _validate(payload, sidecar)


def test_rejects_model_product_or_storyboard_role_moved_to_wrong_position() -> None:
    payload, sidecar = _case()
    sidecar["image_bindings"][0]["role"] = "director_storyboard"
    with pytest.raises(contract.RunningHubStandardPayloadError, match="role order"):
        _validate(payload, sidecar)


@pytest.mark.parametrize("mutation", ["missing_page", "duplicate_page", "overlapping_cut", "wrong_approval_set"])
def test_rejects_incomplete_or_ambiguous_storyboard_page_binding(mutation: str) -> None:
    payload, sidecar = _case()
    storyboards = [row for row in sidecar["image_bindings"] if row["role"] == "director_storyboard"]
    if mutation == "missing_page":
        storyboards[0]["page"] = None
    elif mutation == "duplicate_page":
        storyboards[1]["page"] = 1
    elif mutation == "overlapping_cut":
        storyboards[1]["cut_ids"] = ["C02", "C04"]
    else:
        storyboards[1]["approval_set_sha256"] = _sha("different-set")
    with pytest.raises(contract.RunningHubStandardPayloadError, match="storyboard"):
        _validate(payload, sidecar)


def test_allows_image5_through_image9_only_with_explicit_scope_and_prompt_use() -> None:
    payload, sidecar = _case(storyboard_pages=2, extra_images=5)
    _validate(payload, sidecar)
    assert len(payload["imageUrls"]) == 9


def test_rejects_legacy_single_storyboard_url_binding_for_multi_image_request() -> None:
    payload, _ = _case()
    legacy = {"schema_version": "usfr-video-reference/v1", "storyboard_url": payload["imageUrls"][0]}
    with pytest.raises(contract.RunningHubStandardPayloadError):
        _validate(payload, legacy)


def test_rejects_execution_carrier_as_uploaded_or_bound_image() -> None:
    payload, sidecar = _case()
    row = sidecar["image_bindings"][2]
    row["artifact_name"] = "seedance_execution_carrier.png"
    row["url"] = "https://media.example/seedance_execution_carrier.png"
    payload["imageUrls"][2] = row["url"]
    sidecar["ordered_image_urls"][2] = row["url"]
    with pytest.raises(contract.RunningHubStandardPayloadError, match="execution carrier"):
        _validate(payload, sidecar)


def test_binding_digest_changes_when_image_order_or_role_changes() -> None:
    _, sidecar = _case()
    first = contract.image_reference_binding_sha256(sidecar)
    changed = copy.deepcopy(sidecar)
    changed["image_bindings"][0]["purpose"] = "different authority"
    second = contract.image_reference_binding_sha256(changed)
    assert first != second
    assert first == hashlib.sha256(
        json.dumps(sidecar, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def test_video_reference_binds_the_complete_image_sidecar_digest_not_one_storyboard_url() -> None:
    payload, sidecar = _case()
    payload.update({"realPersonMode": True})
    common = {
        "schema_version": "usfr-video-reference/v1",
        "url": payload["videoUrls"][0],
        "source_video_sha256": _sha("source"),
        "source_slice_sha256": _sha("slice"),
        "segment_id": "S01",
        "segment_plan_sha256": _sha("plan"),
        "source_video_reference_artifact_id": "source-reference:S01",
        "start_ms": 0,
        "end_ms": 4000,
        "target_changes": [{"kind": "new_model_image", "sha256": _sha("new-model.png")}],
    }
    legacy = {**common, "storyboard_url": payload["imageUrls"][2]}
    with pytest.raises(contract.RunningHubStandardPayloadError):
        contract.validate_video_reference_binding(payload, legacy)

    current = {
        **common,
        "image_reference_binding_sha256": contract.image_reference_binding_sha256(sidecar),
    }
    contract.validate_video_reference_binding(payload, current)
