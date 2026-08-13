from __future__ import annotations

import importlib.util
import hashlib
import inspect
import json
from dataclasses import replace
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from bind_input_slots import InputSlotError, bind_slots, validate_slots  # noqa: E402
import seedance_prompt_compiler  # noqa: E402
from server import orchestrator, recovery_workflow, runninghub_workflows  # noqa: E402
from server import packaged_stages, production_ports, runninghub_standard_contract  # noqa: E402
from server.errors import ReplicationError  # noqa: E402
from server.ephemeral_driver import _dedupe  # noqa: E402
from server.ephemeral_service import ReplicationService  # noqa: E402
from server.job_models import ArtifactRef, JobSnapshot  # noqa: E402


compile_edit_prompt = getattr(seedance_prompt_compiler, "compile_edit_prompt", None)
build_asset_reference_bindings = getattr(seedance_prompt_compiler, "build_asset_reference_bindings", None)
build_edit_provider_payload = getattr(seedance_prompt_compiler, "build_edit_provider_payload", None)
EditPromptContractError = getattr(seedance_prompt_compiler, "EditPromptContractError", ValueError)
build_stage_plan = orchestrator.build_stage_plan
invalidate_stage_downstream = getattr(orchestrator, "invalidate_stage_downstream", None)
plan_confirmed_edit_retry = getattr(recovery_workflow, "plan_confirmed_edit_retry", None)
RunningHubWorkflowClient = runninghub_workflows.RunningHubWorkflowClient
AssetBoardGenerationError = getattr(runninghub_workflows, "AssetBoardGenerationError", RuntimeError)


def _provider_only_receipt(prompt: str, *, count: int = 1) -> dict[str, object]:
    return {
        "contract": "provider-only-multi-object-binding/v1",
        "compiler_version": "provider-only-multi-object-binding/v1",
        "binding_mode": "provider_only_multi_object_binding",
        "binding_contract_sha256": "8" * 64,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "image_tags": [f"@Image{index}" for index in range(1, count + 1)],
        "source_object_ids": [f"SRC_{index}" for index in range(1, count + 1)],
    }


SEGMENT_PATH = ROOT / "bundled-skills" / "seedance-storyboard-replication" / "scripts" / "segment_plan.py"
_SPEC = importlib.util.spec_from_file_location("v2_segment_plan", SEGMENT_PATH)
assert _SPEC and _SPEC.loader
segment_plan = importlib.util.module_from_spec(_SPEC)
sys.modules["v2_segment_plan"] = segment_plan
_SPEC.loader.exec_module(segment_plan)

STORYBOARD_PATH = ROOT / "scripts" / "validate_user_director_storyboard.py"
_STORYBOARD_SPEC = importlib.util.spec_from_file_location("v2_storyboard", STORYBOARD_PATH)
assert _STORYBOARD_SPEC and _STORYBOARD_SPEC.loader
storyboard = importlib.util.module_from_spec(_STORYBOARD_SPEC)
sys.modules["v2_storyboard"] = storyboard
_STORYBOARD_SPEC.loader.exec_module(storyboard)


def _files(tmp_path: Path) -> dict[str, Path]:
    names = {
        "source": "source.mp4",
        "model": "model.png",
        "garment": "garment.png",
        "scene": "scene.png",
        "product_a": "product-a.png",
        "product_b": "product-b.png",
        "ui": "ui.mp4",
        "tail": "tail.mp4",
        "music": "music.mp3",
    }
    result: dict[str, Path] = {}
    for key, name in names.items():
        path = tmp_path / name
        path.write_bytes(key.encode())
        result[key] = path
    return result


def _asset_board_template_version(asset_type: str) -> str:
    return "model-identity-v3" if asset_type == "model" else f"{asset_type}-v2"


def _provider_asset_board_contract(asset_type: str, source_sha: str, request_sha: str) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "asset_type": asset_type,
                "template_version": _asset_board_template_version(asset_type),
                "source_asset_sha256": source_sha,
                "provider_request_sha256": request_sha,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _v2_manifest(tmp_path: Path, **extra: object) -> dict:
    files = _files(tmp_path)
    values = {
        "source_video": files["source"],
        "new_model_image": [files["model"], files["garment"], files["scene"]],
        "new_product_image": [files["product_a"], files["product_b"]],
        "ui_operation_video": files["ui"],
        "tail_video": files["tail"],
        **extra,
    }
    return bind_slots(values, edit_mode="v2")


def _manifest_context(tmp_path: Path, *, duplicate_current: bool = False) -> tuple[SimpleNamespace, dict[str, object]]:
    from contextlib import contextmanager

    tmp_path.mkdir(parents=True, exist_ok=True)
    script_sha = "9" * 64
    source_sha = "a" * 64
    request_sha = "b" * 64
    response_sha = "c" * 64
    board_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + (1).to_bytes(4, "big") * 2 + bytes([8, 6, 0, 0, 0])
    board_sha = hashlib.sha256(board_bytes).hexdigest()
    binding = {
        "source_slot": "new_product_image",
        "source_index": 0,
        "source_asset_sha256": source_sha,
        "asset_type": "product",
        "asset_tag": "ProductA",
        "replaces_tag": "ProductA",
        "image_reference": "@Image1",
    }
    binding_sha = hashlib.sha256(json.dumps([binding], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    provider_contract = _provider_asset_board_contract("product", source_sha, request_sha)
    receipt = {
        "schema_version": "runninghub-asset-board/v2",
        "asset_type": "product",
        "template_version": "product-v2",
        "source_asset_sha256": source_sha,
        "request_sha256": request_sha,
        "response_sha256": response_sha,
        "task_id": "task-product",
        "board_sha256": board_sha,
        "provider_asset_board_contract_sha256": provider_contract,
        "provider_receipt": {
            "request_sha256": request_sha,
            "response_sha256": response_sha,
            "task_id": "task-product",
        },
    }
    entry = {
        **binding,
        "board_artifact_id": "board-current",
        "board_sha256": board_sha,
        "board_url": "https://media.example/product-board.png",
        "receipt": receipt,
    }
    mapping_basis = {
        "approved_asset_bindings_sha256": binding_sha,
        "entries": [entry],
        "uploaded_tags": ["ProductA"],
        "binding_tags": ["ProductA"],
        "prompt_tags": ["ProductA"],
    }
    mapping_sha = hashlib.sha256(json.dumps(mapping_basis, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    provider_contracts_sha = hashlib.sha256(json.dumps([provider_contract], separators=(",", ":")).encode()).hexdigest()
    manifest = {
        "schema_version": "asset-board-manifest/v1",
        "approved_script_sha256": script_sha,
        "approved_asset_bindings_sha256": binding_sha,
        "asset_board_mapping_sha256": mapping_sha,
        "provider_asset_board_contracts_sha256": provider_contracts_sha,
        "entries": [entry],
        "uploaded_tags": ["ProductA"],
        "binding_tags": ["ProductA"],
        "prompt_tags": ["ProductA"],
    }
    manifest_path = tmp_path / "asset-board-manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    source_video_path = tmp_path / "source-video.mp4"
    source_video_path.write_bytes(b"current-source-video")
    source_video_sha = hashlib.sha256(source_video_path.read_bytes()).hexdigest()
    segment_plan_path = tmp_path / "segment-plan.json"
    segment_plan_path.write_text(
        json.dumps(
            {"contract": "segment-plan/v1", "segments": [{"segment_id": "S01"}]},
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    segment_plan_sha = hashlib.sha256(segment_plan_path.read_bytes()).hexdigest()
    artifacts: list[dict[str, object]] = [
        {
            "artifact_id": "source-video-current",
            "kind": "source_video",
            "sha256": source_video_sha,
            "metadata": {},
        },
        {
            "artifact_id": "segment-plan-current",
            "kind": "segment_plan",
            "sha256": segment_plan_sha,
            "metadata": {},
        },
        {
            "artifact_id": "board-current",
            "kind": "asset_board",
            "sha256": board_sha,
            "metadata": {
                "asset_type": "product",
                "template_version": "product-v2",
                "source_slot": "new_product_image",
                "source_index": 0,
                "source_asset_sha256": source_sha,
                "asset_tag": "ProductA",
                "replaces_tag": "ProductA",
                "image_reference": "@Image1",
                "board_url": "https://media.example/product-board.png",
                "provider_asset_board_contract_sha256": provider_contract,
                "provider_request_sha256": request_sha,
                "provider_response_sha256": response_sha,
                "provider_task_id": "task-product",
            },
        },
        {
            "artifact_id": "manifest-current",
            "kind": "asset_board_manifest",
            "sha256": manifest_sha,
            "metadata": {
                "approved_script_sha256": script_sha,
                "approved_asset_bindings_sha256": binding_sha,
                "asset_board_mapping_sha256": mapping_sha,
                "provider_asset_board_contracts_sha256": provider_contracts_sha,
            },
        },
    ]
    if duplicate_current:
        current_manifest = next(
            item for item in artifacts if item["artifact_id"] == "manifest-current"
        )
        artifacts.append({
            **current_manifest,
            "artifact_id": "manifest-duplicate",
        })
    paths = {
        "source-video-current": source_video_path,
        "segment-plan-current": segment_plan_path,
        "board-current": tmp_path / "board.png",
        "manifest-current": manifest_path,
    }
    paths["board-current"].write_bytes(board_bytes)

    @contextmanager
    def materialize_artifact(_kind: str, *, artifact_id: str, sha256: str):
        del sha256
        yield SimpleNamespace(path=paths[artifact_id])

    approval = {
        "contract": "approved-script-lines/v2",
        "script_sha256": script_sha,
        "approved_edit_script": {
            "contract": "approved-edit-script/v1",
            "asset_bindings": [binding],
            "asset_bindings_sha256": binding_sha,
            "change_rows": [],
            "change_rows_sha256": hashlib.sha256(b"[]").hexdigest(),
        },
    }
    context = SimpleNamespace(
        job_id="job-manifest-contract",
        snapshot=SimpleNamespace(
            current_script_revision=1,
            approved_script_sha256=script_sha,
            slots_manifest={
                "extensions": {"edit_contract": "video-edit-v2"},
                "slots": {"source_video": {"sha256": [source_video_sha]}},
            },
        ),
        job_store=SimpleNamespace(get_script_approval=lambda *_args: approval),
        artifacts=tuple(artifacts),
        materialize_artifact=materialize_artifact,
    )
    return context, {
        "manifest": manifest,
        "manifest_path": manifest_path,
        "approval": approval,
        "binding": binding,
        "source_video_sha": source_video_sha,
        "segment_plan_sha": segment_plan_sha,
    }


def test_runtime_contract_is_local_and_draft3() -> None:
    contract = ROOT / "references" / "video-edit-v2-contract.md"
    assert contract.is_file(), "v2 runtime contract must be packaged inside the Skill"
    text = contract.read_text(encoding="utf-8")
    assert "v2.0-draft-3" in text
    assert "calibration_pending" in text
    assert "ASSET_BOARD_GENERATION_FAILED" in text
    assert "source text" in text.lower()
    assert "needs_recompute" in text
    assert "adult" not in text.lower()


def test_v2_slot_manifest_is_editor_input_and_cuts_legacy_routes(tmp_path: Path) -> None:
    manifest = _v2_manifest(tmp_path)

    assert manifest["schema_version"] == "fixed-input-slots/v2"
    assert manifest["slots"]["source_video"]["role"] == "edit_object"
    assert manifest["slots"]["new_model_image"]["role"] == "visual_asset_input"
    assert manifest["routes"]["ui"] == "splice_ui_operation_video"
    assert manifest["routes"]["tail"] == "splice_tail_video"
    assert "ui_rebuild_enabled" not in manifest.get("extensions", {})
    assert "generated_ui_demo" not in repr(manifest)
    assert "replacement-control" not in repr(manifest)


def test_legacy_and_v2_manifests_close_with_language_and_music_extensions(tmp_path: Path) -> None:
    files = _files(tmp_path)
    legacy = bind_slots({"source_video": files["source"]}, output_language="ja")
    assert legacy is not None
    assert legacy["output_language"] == "ja"
    assert legacy["routes"]["background_music"] == "none"

    v2 = bind_slots(
        {"source_video": files["source"], "new_product_image": files["product_a"]},
        background_music=files["music"],
        edit_mode="v2",
    )
    assert v2 is not None
    assert v2["extensions"]["edit_contract"] == "video-edit-v2"
    assert v2["extensions"]["background_music"]["provider_route"] == "seedance_audio_reference"
    assert v2["routes"]["background_music"] == "seedance_audio_reference"


def test_unknown_edit_mode_fails_closed(tmp_path: Path) -> None:
    files = _files(tmp_path)
    with pytest.raises(InputSlotError, match="edit_mode"):
        bind_slots({"source_video": files["source"], "new_product_image": files["product_a"]}, edit_mode="future")


def test_v2_segment_plan_uses_natural_cut_tail_boundary_and_keeps_ui_cut() -> None:
    plan = segment_plan.plan_edit_segments(
        cuts=[
            {"cut_id": "C01", "start_ms": 0, "end_ms": 5_000},
            {"cut_id": "C02", "start_ms": 5_000, "end_ms": 11_000},
            {"cut_id": "C03", "start_ms": 11_000, "end_ms": 17_000, "route": "ui"},
            {"cut_id": "C04", "start_ms": 17_000, "end_ms": 19_000, "route": "tail"},
        ],
        source_duration_ms=19_000,
        terminal_tail_boundary_ms=17_000,
    )

    assert plan["tail_boundary"]["detected"] is True
    assert plan["tail_boundary"]["start_ms"] == 17_000
    assert len(plan["segments"]) == 2
    assert all(item["duration_ms"] <= 15_000 for item in plan["segments"])
    assert plan["segments"][-1]["end_ms"] == 17_000
    assert "C03" in plan["segments"][-1]["cut_ids"]
    assert "C04" not in {cut for segment in plan["segments"] for cut in segment["cut_ids"]}
    assert plan["split_policy"] == "natural_cut_only"


def test_v2_segment_plan_rejects_dialogue_window_crossing_hard_cut() -> None:
    with pytest.raises(segment_plan.PlanningError, match="line.*crosses|dialogue.*crosses"):
        segment_plan.plan_edit_segments(
            cuts=[
                {"cut_id": "C01", "start_ms": 0, "end_ms": 9_000},
                {"cut_id": "C02", "start_ms": 9_000, "end_ms": 18_000},
            ],
            source_duration_ms=18_000,
            approved_split_boundary_ms=9_000,
            dialogue_windows=[{"line_id": "L01", "start_ms": 8_500, "end_ms": 9_500}],
        )


def test_edit_prompt_is_template_scoped_and_preserves_source_text() -> None:
    artifact = compile_edit_prompt(
        source_video="@Video1",
        asset_bindings=[
            {"tag": "人物A", "reference": "@Image1", "role": "model"},
            {"tag": "商品A", "reference": "@Image2", "role": "product"},
        ],
        replacements=[
            {"window": "00:06.000-00:10.000", "target": "商品A", "instruction": "替换展示商品"}
        ],
        dialogue_changes=[
            {"window": "00:01.200-00:03.500", "speaker": "人物A", "text": "Hello"}
        ],
        source_text_locks=[
            {"window": "00:00.000-00:00.800", "text": "源帧固有文字", "layer": "physical", "disposition": "keep"}
        ],
        watermark_windows=[
            {"window": "00:12.000-00:13.000", "region": {"x": 0.8, "y": 0.8, "w": 0.1, "h": 0.1}}
        ],
        output_language="ja",
    )

    prompt = artifact["prompt"]
    assert prompt.startswith("编辑视频：")
    assert "源帧固有文字" in prompt
    assert "逐帧保持" in prompt
    assert "00:12.000-00:13.000" in prompt
    assert "剧情" not in prompt
    assert "运镜" not in prompt
    assert len(prompt) <= 1_500
    assert artifact["complexity"]["calibration_status"] == "calibration_pending"


def test_complexity_threshold_and_manual_override_are_recorded() -> None:
    artifact = compile_edit_prompt(
        source_video="@Video1",
        asset_bindings=[{"tag": "人物A", "reference": "@Image1", "role": "model"}],
        replacements=[{"window": "00:01.000-00:02.000", "target": "人物A", "instruction": "替换人物"}],
        dialogue_changes=[],
        complexity_config={"threshold": 3.0},
        complexity_override={"score": 2.0, "reason": "人工确认同次完成"},
    )

    assert artifact["complexity"]["threshold"] == 3.0
    assert artifact["complexity"]["calibration_status"] == "calibration_pending"
    assert artifact["complexity"]["score"] == 2.0
    assert artifact["complexity"]["decision_basis"] == "manual_override"
    assert artifact["complexity"]["override_reason"] == "人工确认同次完成"


def test_complexity_records_language_and_source_text_lock_without_physical_replacement_factor() -> None:
    artifact = compile_edit_prompt(
        source_video="@Video1",
        asset_bindings=[{"tag": "人物A", "reference": "@Image1", "role": "model", "asset_type": "model"}],
        replacements=[{"window": "00:01.000-00:02.000", "target": "人物A", "instruction": "替换人物", "asset_type": "model"}],
        dialogue_changes=[{"window": "00:02.000-00:03.000", "speaker": "人物A", "text": "Approved neutral line"}],
        source_text_locks=[{"window": "00:02.000-00:03.000", "text": "SOURCE", "layer": "physical", "disposition": "keep"}],
        output_language="ja",
        complexity_config={"threshold": 3.0},
    )
    assert "model_replacement" in artifact["complexity"]["factor_ids"]
    assert "language_switch" in artifact["complexity"]["factor_ids"]
    assert "physical_text" not in artifact["complexity"]["factor_ids"]


def test_edit_prompt_rejects_unscoped_watermark_and_unsafe_attraction_language() -> None:
    with pytest.raises(EditPromptContractError, match="WATERMARK_SCOPE_REQUIRED"):
        compile_edit_prompt(
            source_video="@Video1",
            asset_bindings=[],
            replacements=[{"target": "watermark", "instruction": "remove watermark"}],
            dialogue_changes=[],
        )


def test_edit_prompt_rejects_watermark_region_mismatch_even_when_window_matches() -> None:
    with pytest.raises(EditPromptContractError, match="WATERMARK_SCOPE_REQUIRED"):
        compile_edit_prompt(
            source_video="@Video1",
            asset_bindings=[],
            replacements=[
                {
                    "window": "00:12.000-00:13.000",
                    "region": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2},
                    "target": "watermark",
                    "instruction": "remove approved watermark",
                }
            ],
            watermark_windows=[
                {
                    "window": "00:12.000-00:13.000",
                    "region": {"x": 0.8, "y": 0.8, "w": 0.1, "h": 0.1},
                }
            ],
            dialogue_changes=[],
        )


def test_edit_prompt_uses_only_explicit_video_reference_and_provider_limit() -> None:
    with pytest.raises(EditPromptContractError, match="EDIT_SOURCE_VIDEO_INVALID"):
        compile_edit_prompt(
            source_video="@Video2",
            asset_bindings=[],
            replacements=[],
            dialogue_changes=[],
        )
    artifact = compile_edit_prompt(
        source_video="@Video1",
        asset_bindings=[],
        replacements=[],
        dialogue_changes=[],
    )
    assert artifact["provider_prompt_limit_chars"] == runninghub_standard_contract.PROVIDER_PROMPT_LIMIT_CHARS
    assert artifact["provider_prompt_limit_chars"] > artifact["compact_target_chars"]


def test_edit_prompt_lip_sync_policy_changes_only_with_approved_dialogue_windows() -> None:
    unchanged = compile_edit_prompt(
        source_video="@Video1",
        asset_bindings=[],
        replacements=[],
        dialogue_changes=[],
    )
    changed = compile_edit_prompt(
        source_video="@Video1",
        asset_bindings=[],
        replacements=[],
        dialogue_changes=[
            {"window": "00:01.000-00:02.000", "speaker": "PersonA", "text": "Approved line"}
        ],
        approved_speaker_tags=["PersonA"],
    )
    assert unchanged["lip_sync_policy"] == "preserve_unmodified_lip_sync"
    assert changed["lip_sync_policy"] == "sync_to_approved_dialogue_windows"
    assert "sync_to_approved_dialogue_windows" in changed["prompt"]


def test_complexity_factor_ids_are_unique_and_overage_has_a_split_decision() -> None:
    artifact = compile_edit_prompt(
        source_video="@Video1",
        asset_bindings=[{"tag": "ProductA", "reference": "@Image1", "asset_type": "product"}],
        replacements=[
            {"window": "00:01.000-00:02.000", "target": "ProductA", "asset_type": "product", "instruction": "replace"},
            {"window": "00:02.000-00:03.000", "target": "ProductA", "asset_type": "product", "instruction": "replace again"},
        ],
        dialogue_changes=[{"window": "00:03.000-00:04.000", "speaker": "PersonA", "text": "Approved line"}],
        approved_speaker_tags=["PersonA"],
        complexity_config={"threshold": 0.5, "over_threshold_strategy": "split"},
    )
    complexity = artifact["complexity"]
    assert len(complexity["factor_ids"]) == len(set(complexity["factor_ids"]))
    assert complexity["decision"] == "split_required"
    assert complexity["split_plan"]
    assert any("dialogue_change" in group["factor_ids"] for group in complexity["split_plan"])


def test_v2_asset_board_receipt_is_versioned_and_consumed_by_standard_payload(tmp_path: Path) -> None:
    files = _files(tmp_path)
    client = RunningHubWorkflowClient(
        api_key="test-key",
        base_url="https://runninghub.example.test",
        upload_file=lambda path: f"https://media.example/{path.name}",
    )
    client.run_image2 = lambda **kwargs: {
        "task_id": "task-v2",
        "image_bytes": b"\x89PNG\r\n\x1a\nboard-v2",
        "result_url": "https://result.example/board-v2.png",
        "reference_urls": ["https://media.example/source.png"],
        "receipt": {"request_sha256": "a" * 64, "response_sha256": "b" * 64, "task_id": "task-v2"},
    }  # type: ignore[method-assign]
    boards = client.run_asset_board_batch(
        [{"tag": "ProductA", "asset_type": "product", "path": files["product_a"]}]
    )
    receipt = boards[0]["receipt"]
    assert receipt["schema_version"] == "runninghub-asset-board/v2"
    assert receipt["asset_type"] == "product"
    assert receipt["template_version"]
    assert receipt["source_asset_sha256"] == hashlib.sha256(files["product_a"].read_bytes()).hexdigest()
    assert receipt["board_sha256"] == hashlib.sha256(b"\x89PNG\r\n\x1a\nboard-v2").hexdigest()
    assert receipt["provider_asset_board_contract_sha256"]
    assert "asset_board_contract_sha256" not in receipt
    refs = build_asset_reference_bindings(boards)
    payload = build_edit_provider_payload(
        video_url="https://media.example/source-slice.mp4",
        prompt="编辑视频：@Video1 是编辑对象。@Image1 绑定 ProductA。",
        asset_bindings=refs,
        source_video_sha256="c" * 64,
        source_slice_sha256="d" * 64,
        segment_plan_sha256="e" * 64,
        segment_id="S01",
        start_ms=0,
        end_ms=10_000,
        source_video_reference_artifact_id="source-slice-S01",
    )
    provider_payload = payload["provider_payload"]
    assert provider_payload["imageUrls"] == [boards[0]["board_url"]]
    assert payload["uploaded_tags"] == payload["binding_tags"] == payload["prompt_tags"] == ["ProductA"]
    assert payload["video_reference_binding"]["schema_version"] == "usfr-video-edit-reference/v1"


def test_v2_binding_schema_is_separate_from_legacy_reference_contract() -> None:
    assert callable(getattr(runninghub_standard_contract, "validate_v2_image_reference_binding", None))
    assert callable(getattr(runninghub_standard_contract, "validate_v2_video_reference_binding", None))
    assert "编辑视频：" not in runninghub_standard_contract.SOURCE_VIDEO_PROMPT_CONTRACT


def test_v2_stage_plan_has_fingerprints_runtime_bindings_and_stale_guard(tmp_path: Path) -> None:
    plan = build_stage_plan(_v2_manifest(tmp_path))
    assert all(isinstance(stage.get("expected_input_fingerprint"), str) and len(stage["expected_input_fingerprint"]) == 64 for stage in plan)
    assert all(stage.get("output_fingerprint") is None for stage in plan)
    submit = next(stage for stage in plan if stage["name"] == "submit_provider_edit")
    assert submit["runtime_stage"] == "submit_provider_video"
    validate = getattr(orchestrator, "validate_stage_artifact_fingerprints", None)
    assert callable(validate)
    with pytest.raises(ValueError, match="stale|fingerprint"):
        validate(plan, {plan[0]["name"]: {"output_fingerprint": "f" * 64}})


def test_existing_packaged_audit_stage_consumes_v2_provider_builder() -> None:
    source = inspect.getsource(packaged_stages.SeedanceAuditStage)
    assert "build_edit_provider_payload" in source
    assert "validate_v2_video_reference_binding" in source

    with pytest.raises(EditPromptContractError, match="CONTENT_SAFETY_BLOCKER"):
        compile_edit_prompt(
            source_video="@Video1",
            asset_bindings=[],
            replacements=[
                {
                    "window": "00:00.000-00:01.000",
                    "target": "人物A",
                    "instruction": "objectifying visual claim",
                }
            ],
            dialogue_changes=[],
        )


def test_edit_prompt_requires_millisecond_windows_and_segment_containment() -> None:
    with pytest.raises(EditPromptContractError, match="EDIT_WINDOW_INVALID"):
        compile_edit_prompt(
            source_video="@Video1",
            asset_bindings=[],
            replacements=[{"window": "00:06-00:10", "target": "商品A", "instruction": "替换"}],
            dialogue_changes=[],
        )
    with pytest.raises(EditPromptContractError, match="EDIT_WINDOW_OUT_OF_SEGMENT"):
        compile_edit_prompt(
            source_video="@Video1",
            asset_bindings=[],
            replacements=[{"window": "00:04.000-00:06.000", "target": "商品A", "instruction": "替换"}],
            dialogue_changes=[],
            segment_window_ms=(0, 5_000),
        )


def test_segment_two_rebinds_global_script_windows_to_segment_local_time() -> None:
    artifact = compile_edit_prompt(
        source_video="@Video1",
        asset_bindings=[{"tag": "商品A", "reference": "@Image1", "asset_type": "product"}],
        replacements=[{"window": "00:16.000-00:18.000", "target": "商品A", "asset_type": "product", "instruction": "替换展示"}],
        dialogue_changes=[],
        segment_window_ms=(15_000, 30_000),
    )
    assert "00:01.000-00:03.000" in artifact["prompt"]
    assert "00:16.000-00:18.000" not in artifact["prompt"]
    assert artifact["time_rebinds"] == [{
        "global_window": "00:16.000-00:18.000",
        "local_window": "00:01.000-00:03.000",
        "segment_start_ms": 15_000,
    }]


def test_thirty_second_edit_rejects_a_15_5_second_natural_boundary() -> None:
    with pytest.raises(segment_plan.PlanningError, match="natural Cut|15"):
        segment_plan.plan_edit_segments(
            cuts=[
                {"cut_id": "C01", "start_ms": 0, "end_ms": 15_500},
                {"cut_id": "C02", "start_ms": 15_500, "end_ms": 30_000},
            ],
            source_duration_ms=30_000,
        )


def test_asset_board_batch_emits_image2_receipts_and_five_templates(tmp_path: Path) -> None:
    files = _files(tmp_path)
    requests: list[dict] = []

    client = RunningHubWorkflowClient(
        api_key="test-key",
        base_url="https://runninghub.example.test",
        upload_file=lambda path: f"https://media.example/{path.name}",
    )

    def fake_image2(**kwargs):
        requests.append(kwargs)
        return {
            "task_id": f"task-{len(requests)}",
            "image_bytes": b"\x89PNG\r\n\x1a\nboard",
            "result_url": f"https://result.example/board-{len(requests)}.png",
            "reference_urls": ["https://media.example/source.png"],
            "receipt": {"schema_version": "runninghub-image2-storyboard/v1", "request_sha256": "a" * 64, "response_sha256": "b" * 64, "task_id": f"task-{len(requests)}"},
        }

    client.run_image2 = fake_image2  # type: ignore[method-assign]
    bindings = [
        {"tag": "人物A", "asset_type": "model", "path": files["model"]},
        {"tag": "服装A", "asset_type": "garment", "path": files["garment"]},
        {"tag": "场景A", "asset_type": "scene", "path": files["scene"]},
        {"tag": "商品A", "asset_type": "product", "path": files["product_a"]},
        {"tag": "AppA", "asset_type": "app", "path": files["scene"]},
    ]
    boards = client.run_asset_board_batch(bindings)

    assert len(requests) == 5
    assert {item["template"] for item in requests} == {"model", "garment", "scene", "product", "app"}
    model_request = next(item for item in requests if item["template"] == "model")
    assert "one dominant head-and-shoulders portrait" in model_request["prompt"]
    assert all(token not in model_request["prompt"] for token in ("A-pose", "front, side, and back", "wardrobe"))
    model_board = next(item for item in boards if item["asset_type"] == "model")
    assert model_board["receipt"]["template_version"] == "model-identity-v3"
    assert all(item["receipt"]["task_id"] for item in boards)
    refs = build_asset_reference_bindings(boards)
    payload = build_edit_provider_payload(
        video_url="https://media.example/source.mp4",
        prompt="编辑视频：@Video1 是编辑对象。@Image1 人物A @Image2 服装A @Image3 场景A @Image4 商品A @Image5 AppA",
        asset_bindings=refs,
        source_video_sha256="a" * 64,
        source_slice_sha256="b" * 64,
        segment_plan_sha256="c" * 64,
        segment_id="S01",
        start_ms=0,
        end_ms=10_000,
        source_video_reference_artifact_id="source-S01",
    )
    assert [item["tag"] for item in refs] == ["人物A", "服装A", "场景A", "商品A", "AppA"]
    assert [item["reference"] for item in refs] == ["@Image1", "@Image2", "@Image3", "@Image4", "@Image5"]
    assert payload["provider_payload"]["imageUrls"] == [item["board_url"] for item in boards]
    assert payload["asset_board_receipts"]


def test_asset_board_failure_is_typed_and_never_falls_back_to_original(tmp_path: Path) -> None:
    client = RunningHubWorkflowClient(
        api_key="test-key",
        base_url="https://runninghub.example.test",
        upload_file=lambda path: f"https://media.example/{path.name}",
    )
    client.run_image2 = lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("provider failed"))  # type: ignore[method-assign]
    with pytest.raises(AssetBoardGenerationError, match="ASSET_BOARD_GENERATION_FAILED"):
        client.run_asset_board_batch([{"tag": "商品A", "asset_type": "product", "path": tmp_path / "missing.png"}])


def test_storyboard_validator_accepts_only_sketch_cut_logic_and_two_pages() -> None:
    cuts = [
        {"cut_id": f"C{i:02d}", "start_ms": (i - 1) * 1_000, "end_ms": i * 1_000, "action_purpose": "展示卖点", "motion": "向前", "asset_detail": "禁止"}
        for i in range(1, 13)
    ]
    with pytest.raises(storyboard.UserDirectorStoryboardError, match="asset_detail|sketch"):
        storyboard.validate_sketch_cut_board(cuts)

    clean_cuts = [
        {key: value for key, value in cut.items() if key != "asset_detail"}
        for cut in cuts
    ]
    result = storyboard.validate_sketch_cut_board(clean_cuts)
    assert result["pages"] and len(result["pages"]) == 2
    assert all(len(page) <= 6 for page in result["pages"])
    assert all("asset_detail" not in cut for page in result["pages"] for cut in page)
    assert result["approval_gates"] == ["script_document", "sketch_storyboard"]


def test_v2_stage_plan_has_dependencies_and_cuts_legacy_activity_paths(tmp_path: Path) -> None:
    splice_manifest = _v2_manifest(tmp_path)
    splice_plan = build_stage_plan(splice_manifest)
    assert splice_manifest["routes"]["ui"] == "splice_ui_operation_video"
    assert "generate_app_asset_board" not in [stage["name"] for stage in splice_plan]
    assert "generated_ui_demo" not in repr(splice_plan)

    files = _files(tmp_path)
    asset_manifest = _v2_manifest(
        tmp_path,
        ui_operation_video=None,
        ui_screenshot=files["scene"],
    )
    plan = build_stage_plan(asset_manifest)
    names = [stage["name"] for stage in plan]
    assert asset_manifest["routes"]["ui"] == "app_asset_seedance_edit"
    assert "compile_edit_prompt" in names
    assert "generate_asset_boards" in names
    assert "generate_sketch_storyboard" not in names
    assert "generate_storyboards" not in [stage["runtime_stage"] for stage in plan]
    assert "await_storyboard_approval" not in names
    assert [stage["name"] for stage in plan if stage["kind"] == "approval"] == [
        "await_script_approval",
    ]
    assert next(stage for stage in plan if stage["name"] == "plan_segments")["depends_on"] == [
        "analyze_source",
        "await_script_approval",
        "generate_asset_boards",
    ]
    assert "generated_ui_demo" not in repr(plan)
    assert "replacement-control" not in repr(plan)
    assert "seedance_invocation_a" not in repr(plan)
    assert "seedance_invocation_b" not in repr(plan)
    assert all("depends_on" in stage for stage in plan[1:])
    assert all(stage.get("edit_contract") == "video-edit-v2" for stage in plan)


def test_v2_legacy_storyboard_metadata_is_excluded_from_authority_and_dedupe() -> None:
    snapshot = JobSnapshot.new(
        job_id="v2-storyboard-history",
        capability_token_hash="a" * 64,
        slots_manifest={
            "extensions": {"edit_contract": "video-edit-v2"},
            "slots": {"source_video": {"present": True}},
        },
        expires_at_ms=1_900_000_000_000,
    )
    snapshot = replace(
        snapshot,
        current_script_revision=1,
        approved_script_sha256="b" * 64,
        current_storyboard_revision=1,
        approved_storyboard_sha256="c" * 64,
    )
    service = ReplicationService(job_store=SimpleNamespace(get_job=lambda _job_id: snapshot))
    changed_history = replace(
        snapshot,
        current_storyboard_revision=2,
        approved_storyboard_sha256="d" * 64,
    )

    assert service.current_authority(snapshot.job_id) == {
        "approved_script_sha256": "b" * 64,
        "slots_manifest": snapshot.slots_manifest,
    }
    assert _dedupe(snapshot.job_id, "segment_plan", snapshot) == _dedupe(
        snapshot.job_id,
        "segment_plan",
        changed_history,
    )
    plan = build_stage_plan(
        snapshot.slots_manifest,
        approval_state={
            "script_revision": snapshot.current_script_revision,
            "script_sha256": snapshot.approved_script_sha256,
            "storyboard_revision": snapshot.current_storyboard_revision,
            "storyboard_sha256": snapshot.approved_storyboard_sha256,
        },
    )
    assert {stage["name"] for stage in plan}.isdisjoint(
        {"generate_storyboards", "await_storyboard_approval"}
    )


def test_v2_script_revision_preserves_legacy_storyboard_history_and_invalidates_without_it() -> None:
    import fakeredis

    from server.redis_job_store import RedisEphemeralJobStore

    store = RedisEphemeralJobStore(
        fakeredis.FakeRedis(decode_responses=False), prefix="v2-storyboard-history"
    )
    job = store.create_job(
        slots_manifest={"extensions": {"edit_contract": "video-edit-v2"}},
        capability_token_hash="a" * 64,
        ttl_seconds=3600,
    )
    seeded = store.cas_transition(
        job_id=job.job_id,
        expected_version=job.version,
        command="seed_legacy_storyboard_history",
        updates={
            "current_storyboard_revision": 4,
            "approved_storyboard_sha256": "c" * 64,
        },
        ttl_seconds=3600,
    )
    artifact = ArtifactRef(
        artifact_id="legacy-storyboard-artifact",
        kind="storyboard_image",
        object_key=f"temporary/{job.job_id}/legacy-storyboard.png",
        sha256="d" * 64,
        content_type="image/png",
        size_bytes=1,
    )
    store.put_artifact(job_id=job.job_id, artifact=artifact)

    appended = store.append_revision(
        job_id=job.job_id,
        kind="script",
        expected_version=seeded.version,
        manifest={"revision": 1, "sha256": "b" * 64},
        invalidate_downstream=True,
        ttl_seconds=3600,
    )

    assert appended.current_storyboard_revision == 4
    assert appended.approved_storyboard_sha256 == "c" * 64
    assert "storyboard" not in appended.invalidated
    assert {"segment_plan", "prompt_audit", "provider_plan", "assembly", "qc"}.issubset(
        appended.invalidated
    )
    assert store.get_artifact(job.job_id, artifact.artifact_id) == artifact


def test_v2_deterministic_splice_keeps_the_single_script_approval_contract() -> None:
    manifest = {
        "extensions": {"edit_contract": "video-edit-v2"},
        "slots": {
            "source_video": {"present": True},
            "ui_operation_video": {"present": True},
        },
        "routes": {
            "product": "preserve_source_product",
            "character": "preserve_source_character",
            "ui": "splice_ui_operation_video",
            "tail": "remove_source_tail_card",
            "background_music": "none",
        },
    }

    plan = build_stage_plan(manifest)
    names = [stage["name"] for stage in plan]

    assert "plan_segments" in names
    assert [stage["name"] for stage in plan if stage["kind"] == "approval"] == [
        "await_script_approval",
    ]
    assert "generate_sketch_storyboard" not in names
    assert "await_storyboard_approval" not in names
    assert next(stage for stage in plan if stage["name"] == "plan_segments")["depends_on"] == [
        "analyze_source",
        "await_script_approval",
        "generate_asset_boards",
    ]


def test_v2_language_only_keeps_a_zero_paid_asset_board_contract_stage() -> None:
    manifest = {
        "extensions": {"edit_contract": "video-edit-v2"},
        "slots": {"source_video": {"present": True}},
        "routes": {},
        "admission": {"language_only": True},
        "output_language": "ja",
    }

    plan = build_stage_plan(manifest)
    names = [stage["name"] for stage in plan]

    assert [stage["name"] for stage in plan if stage["kind"] == "approval"] == [
        "await_script_approval",
    ]
    assert "generate_asset_boards" in names
    asset_boards = next(stage for stage in plan if stage["name"] == "generate_asset_boards")
    assert asset_boards["provider"] is False
    assert next(stage for stage in plan if stage["name"] == "plan_segments")["depends_on"] == [
        "analyze_source",
        "await_script_approval",
        "generate_asset_boards",
    ]


@pytest.mark.parametrize(
    ("has_screenshot", "has_store_url", "expected_route"),
    [
        (True, False, "app_asset_seedance_edit"),
        (False, True, "app_asset_seedance_edit"),
        (True, True, "app_asset_seedance_edit"),
        (False, False, "preserve_source_ui"),
    ],
)
def test_v2_app_evidence_routes_cover_screenshot_url_both_and_empty(
    tmp_path: Path, has_screenshot: bool, has_store_url: bool, expected_route: str
) -> None:
    files = _files(tmp_path)
    values: dict[str, object] = {"source_video": files["source"]}
    if has_screenshot:
        values["ui_screenshot"] = files["scene"]
    if has_store_url:
        values["app_store_url"] = "https://apps.apple.com/app/id123456789"
    manifest = validate_slots(values, edit_mode="v2")
    assert manifest["routes"]["ui"] == expected_route


def test_v2_driver_resolves_semantic_stage_to_existing_runtime_stage() -> None:
    from server.ephemeral_driver import EphemeralStageDriver

    resolve = getattr(EphemeralStageDriver, "runtime_stage", None)
    assert callable(resolve)
    assert resolve({"name": "audit_edit_request", "runtime_stage": "audit_seedance_request"}) == "audit_seedance_request"
    assert resolve({"name": "submit_provider_edit", "runtime_stage": "submit_provider_video"}) == "submit_provider_video"


def test_upstream_stage_failure_marks_all_downstream_for_recompute(tmp_path: Path) -> None:
    plan = build_stage_plan(_v2_manifest(tmp_path))
    invalidated = invalidate_stage_downstream(plan, "build_edit_script")
    assert invalidated
    assert all(stage["status"] == "needs_recompute" for stage in invalidated)
    assert all(stage["recompute_reason"] == "upstream_failed:build_edit_script" for stage in invalidated)


def test_confirmed_seedance_failure_gets_one_narrowed_retry_but_ambiguous_reconciles() -> None:
    retry = plan_confirmed_edit_retry(
        failure={"status": "FAILED", "failure_type": "dialogue_mismatch", "confirmed": True},
        request={"prompt": "编辑视频：替换台词", "attempt": 1},
    )
    assert retry["action"] == "retry_once"
    assert retry["request"]["attempt"] == 2
    assert retry["request"]["adjustment"] == "narrow_dialogue_window"

    ambiguous = plan_confirmed_edit_retry(
        failure={"status": "AMBIGUOUS", "failure_type": "provider_timeout", "confirmed": False},
        request={"prompt": "编辑视频：替换台词", "attempt": 1},
    )
    assert ambiguous["action"] == "reconcile"
    assert ambiguous["create_count_delta"] == 0


def test_audio_lane_keeps_ui_dialogue_outside_song_lip_sync() -> None:
    from server.audio_lane_router import route_audio_line

    ui_dialogue = route_audio_line(content_type="spoken", visibility="on_camera", operation_mode="normal_replication")
    song = route_audio_line(content_type="sung", visibility="on_camera", operation_mode="normal_replication")
    assert ui_dialogue["replacement_route"] == "approved_dialogue_in_generation_prompt"
    assert song["replacement_route"] == "h3_mv_song_edit"


def test_v2_audit_stage_run_emits_versioned_standard_audit_envelope(monkeypatch, tmp_path: Path) -> None:
    from contextlib import contextmanager

    source_slice_path = tmp_path / "source-slice.mp4"
    source_slice_path.write_bytes(b"\x00\x00\x00\x18ftypisom-v2-source-slice")
    source_slice_sha = hashlib.sha256(source_slice_path.read_bytes()).hexdigest()
    board_path = tmp_path / "board.png"
    board_path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + (1).to_bytes(4, "big") * 2 + bytes([8, 6, 0, 0, 0]))
    board_sha = hashlib.sha256(board_path.read_bytes()).hexdigest()
    approved_script_sha = "9" * 64
    approved_binding = {
        "source_slot": "new_product_image",
        "source_index": 0,
        "source_asset_sha256": "a" * 64,
        "asset_type": "product",
        "asset_tag": "ProductA",
        "replaces_tag": "ProductA",
        "image_reference": "@Image1",
    }
    approved_bindings_sha = hashlib.sha256(json.dumps([approved_binding], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    provider_contract = _provider_asset_board_contract("product", "a" * 64, "b" * 64)
    manifest_entry = {
        "source_slot": "new_product_image",
        "source_index": 0,
        "source_asset_sha256": "a" * 64,
        "asset_type": "product",
        "asset_tag": "ProductA",
        "replaces_tag": "ProductA",
        "image_reference": "@Image1",
        "board_artifact_id": "board-S01",
        "board_sha256": board_sha,
        "board_url": "https://media.example/actual-board.png",
    }
    materialized = {
        "source-slice-S01": source_slice_path,
        "board-S01": board_path,
    }

    @contextmanager
    def materialize_artifact(*_args, **kwargs):
        yield SimpleNamespace(path=materialized[str(kwargs.get("artifact_id"))])

    board_receipt = {
        "schema_version": "runninghub-asset-board/v2",
        "asset_type": "product",
        "template_version": "product-v2",
        "source_asset_sha256": "a" * 64,
        "request_sha256": "b" * 64,
        "response_sha256": "c" * 64,
        "task_id": "task-board",
        "board_sha256": board_sha,
        "provider_asset_board_contract_sha256": provider_contract,
        "provider_receipt": {"request_sha256": "b" * 64, "response_sha256": "c" * 64, "task_id": "task-board"},
    }
    manifest_entry["receipt"] = board_receipt
    mapping_basis = {
        "approved_asset_bindings_sha256": approved_bindings_sha,
        "entries": [manifest_entry],
        "uploaded_tags": ["ProductA"],
        "binding_tags": ["ProductA"],
        "prompt_tags": ["ProductA"],
    }
    mapping_sha = hashlib.sha256(json.dumps(mapping_basis, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    provider_contracts_sha = hashlib.sha256(json.dumps([provider_contract], separators=(",", ":")).encode()).hexdigest()
    manifest_value = {
        "schema_version": "asset-board-manifest/v1",
        "approved_script_sha256": approved_script_sha,
        "approved_asset_bindings_sha256": approved_bindings_sha,
        "asset_board_mapping_sha256": mapping_sha,
        "provider_asset_board_contracts_sha256": provider_contracts_sha,
        "entries": [manifest_entry],
        "uploaded_tags": ["ProductA"],
        "binding_tags": ["ProductA"],
        "prompt_tags": ["ProductA"],
    }
    manifest_path = tmp_path / "asset-board-manifest.json"
    manifest_path.write_text(json.dumps(manifest_value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    materialized["manifest-S01"] = manifest_path
    audit_prompt = "编辑视频：@Video1 是编辑对象。@Image1 绑定 ProductA。"
    contract = {
        "schema_version": "video-edit-v2-input/v1",
        "edit_contract": "video-edit-v2",
        "segments": [
            {
                "segment_id": "S01",
                "segment_plan_sha256": "e" * 64,
                "source_video_sha256": "f" * 64,
                    "source_slice_sha256": source_slice_sha,
                "source_video_reference_artifact_id": "source-slice-S01",
                "start_ms": 15_000,
                "end_ms": 25_000,
                "video_url": "https://media.example/slice-S01.mp4",
                    "compiled_prompt": {
                        "prompt": audit_prompt,
                        "provider_only_binding_receipt": _provider_only_receipt(audit_prompt),
                    },
                    "asset_bindings": [
                        {
                        "tag": "ForgedTag",
                        "reference": "@Image9",
                        "asset_type": "scene",
                        "source_slot": "new_model_image",
                        "source_index": 99,
                        "source_asset_sha256": "f" * 64,
                        "replaces_tag": "ForgedReplacement",
                        "board_url": "https://media.example/untrusted-board.png",
                        "board_artifact_id": "forged-board",
                            "receipt": {"schema_version": "forged-receipt/v0"},
                        }
                    ],
                }
            ],
    }
    monkeypatch.setattr(packaged_stages, "_read_json_artifact", lambda *_args, **_kwargs: contract)
    context = SimpleNamespace(
        publish_bytes=lambda **kwargs: {"kind": kwargs["kind"], "sha256": kwargs["expected_sha256"]},
        artifacts=(
            {
                "artifact_id": "source-slice-S01",
                "kind": "source_video_reference",
                "sha256": source_slice_sha,
                "metadata": {
                    "source_video_sha256": "f" * 64,
                    "segment_id": "S01",
                    "segment_plan_sha256": "e" * 64,
                    "start_ms": 15_000,
                    "end_ms": 25_000,
                },
            },
            {
                "artifact_id": "board-S01",
                "kind": "asset_board",
                "sha256": board_sha,
                "metadata": {
                    "asset_type": "product",
                    "source_slot": "new_product_image",
                    "source_index": 0,
                    "source_asset_sha256": "a" * 64,
                    "asset_tag": "ProductA",
                    "replaces_tag": "ProductA",
                    "image_reference": "@Image1",
                    "template_version": "product-v2",
                        "board_url": "https://media.example/actual-board.png",
                        "provider_asset_board_contract_sha256": provider_contract,
                        "provider_request_sha256": "b" * 64,
                        "provider_response_sha256": "c" * 64,
                        "provider_task_id": "task-board",
                },
            },
                {
                    "artifact_id": "manifest-S01",
                "kind": "asset_board_manifest",
                "sha256": manifest_sha,
                "metadata": {
                    "approved_asset_bindings_sha256": approved_bindings_sha,
                    "approved_script_sha256": approved_script_sha,
                    "asset_board_mapping_sha256": mapping_sha,
                    "provider_asset_board_contracts_sha256": provider_contracts_sha,
                    },
                },
            ),
        materialize_artifact=materialize_artifact,
        job_id="job-audit-manifest",
        snapshot=SimpleNamespace(
            current_script_revision=1,
            approved_script_sha256=approved_script_sha,
            slots_manifest={"slots": {"source_video": {"sha256": ["f" * 64]}}},
        ),
        job_store=SimpleNamespace(
            get_script_approval=lambda *_args: {
                "contract": "approved-script-lines/v2",
                "script_sha256": approved_script_sha,
                "approved_edit_script": {
                    "contract": "approved-edit-script/v1",
                    "asset_bindings": [approved_binding],
                    "asset_bindings_sha256": approved_bindings_sha,
                    "change_rows": [],
                    "change_rows_sha256": hashlib.sha256(b"[]").hexdigest(),
                },
            }
        ),
        work_dir=Path("."),
    )
    stage = packaged_stages.SeedanceAuditStage(
        provider=object(),
        media_uploader=SimpleNamespace(
            upload_media=lambda _path: "https://media.example/actual-slice.mp4"
        ),
    )
    result = stage.run(context=context, input_artifacts=[])
    envelope = result["seedance_request_audit"]
    row = envelope["segments"][0]
    assert envelope["edit_contract"] == "video-edit-v2"
    assert set(row["payload_template"]) == set(runninghub_standard_contract.RUNNINGHUB_STANDARD_SEEDANCE_FIELDS)
    assert row["payload_template"]["videoUrls"] == ["https://media.example/actual-slice.mp4"]
    assert row["payload_template"]["imageUrls"] == ["https://media.example/actual-board.png"]
    assert row["asset_board_manifest_artifact_id"] == "manifest-S01"
    assert row["asset_board_manifest_sha256"] == manifest_sha
    canonical_image = row["image_reference_binding"]["image_bindings"][0]
    assert canonical_image["asset_type"] == "product"
    assert canonical_image["tag"] == "ProductA"
    assert canonical_image["reference"] == "@Image1"
    assert canonical_image["board_sha256"] == board_sha
    assert canonical_image["receipt"]["source_asset_sha256"] == "a" * 64
    assert canonical_image["receipt"] == board_receipt
    assert len(row["image_reference_binding"]["image_bindings"]) == 1
    assert not {"storyboard_bindings", "storyboard_receipts", "approved_storyboard_manifest_sha256", "approved_storyboard_cut_sha256s"}.intersection(row)
    serialized_row = json.dumps(row, ensure_ascii=False)
    assert all(value not in serialized_row for value in ("ForgedTag", "ForgedReplacement", "untrusted-board", "forged-board", "forged-receipt"))
    tampered_receipt = dict(manifest_entry["receipt"])
    tampered_receipt["provider_asset_board_contract_sha256"] = "f" * 64
    manifest_entry["receipt"] = tampered_receipt
    mapping_basis["entries"] = [manifest_entry]
    manifest_value["asset_board_mapping_sha256"] = hashlib.sha256(
        json.dumps(mapping_basis, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    manifest_value["provider_asset_board_contracts_sha256"] = hashlib.sha256(
        json.dumps(["f" * 64], separators=(",", ":")).encode()
    ).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest_value, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    manifest_descriptor = next(
        item for item in context.artifacts if item["artifact_id"] == "manifest-S01"
    )
    manifest_descriptor["sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    manifest_descriptor["metadata"]["asset_board_mapping_sha256"] = manifest_value["asset_board_mapping_sha256"]
    manifest_descriptor["metadata"]["provider_asset_board_contracts_sha256"] = manifest_value["provider_asset_board_contracts_sha256"]
    with pytest.raises(ReplicationError, match="provider (?:contract|receipt)"):
        packaged_stages._resolve_v2_asset_board_manifest(context)
    assert row["video_reference_binding"]["schema_version"] == "usfr-video-edit-reference/v1"
    assert row["video_reference_binding"]["source_slice_sha256"] == source_slice_sha
    assert row["time_receipt"]["local_window"] == "00:00.000-00:10.000"


def test_v2_audit_rejects_forged_full_source_claim_without_server_evidence(tmp_path: Path) -> None:
    from contextlib import contextmanager

    source_path = tmp_path / "full-source.mp4"
    source_path.write_bytes(b"\x00\x00\x00\x18ftypisom-frozen-source")
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    artifact_id = "source-full-S01"

    @contextmanager
    def materialize_artifact(*_args, **kwargs):
        assert kwargs["artifact_id"] == artifact_id
        yield SimpleNamespace(path=source_path)

    context = SimpleNamespace(
        artifacts=(
            {
                "artifact_id": artifact_id,
                "kind": "source_video_reference",
                "sha256": source_sha,
                "metadata": {
                    "source_video_sha256": source_sha,
                    "segment_id": "S01",
                    "segment_plan_sha256": "e" * 64,
                    "start_ms": 0,
                    "end_ms": 10_000,
                    "source_duration_ms": 30_000,
                },
            },
        ),
        snapshot=SimpleNamespace(
            slots_manifest={"slots": {"source_video": {"sha256": [source_sha]}}},
        ),
        materialize_artifact=materialize_artifact,
    )
    item = {
        "segment_id": "S01",
        "segment_plan_sha256": "e" * 64,
        "source_video_sha256": source_sha,
        "source_slice_sha256": source_sha,
        "source_video_reference_artifact_id": artifact_id,
        "start_ms": 0,
        "end_ms": 10_000,
        "source_is_full_segment": True,
    }
    stage = packaged_stages.SeedanceAuditStage(
        provider=object(),
        media_uploader=SimpleNamespace(upload_media=lambda _path: "https://media.example/source.mp4"),
    )
    with pytest.raises(ReplicationError, match="complete source duration") as exc_info:
        stage._v2_published_source_reference(context=context, item=item)
    assert exc_info.value.code == "SOURCE_SLICE_SHA_INVALID"


def test_v2_audit_blocks_visual_asset_when_canonical_manifest_is_missing() -> None:
    binding = {
        "tag": "ProductA",
        "reference": "@Image1",
        "asset_type": "product",
        "board_artifact_id": "board-forged",
        "receipt": {"board_sha256": "a" * 64, "provider_asset_board_contract_sha256": "b" * 64},
    }
    with pytest.raises(ReplicationError, match="manifest") as exc_info:
        packaged_stages.SeedanceAuditStage._v2_published_board_url(
            SimpleNamespace(artifacts=()), binding=binding
        )
    assert exc_info.value.code == "ARTIFACT_NOT_FOUND"


def test_v2_manifest_selects_current_mapping_and_rejects_ambiguous_current_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(packaged_stages, "_read_json_artifact", lambda *_args, **_kwargs: {})
    context, _state = _manifest_context(tmp_path)
    historical = dict(context.artifacts[1])
    historical["artifact_id"] = "manifest-history"
    historical["metadata"] = {
        **historical["metadata"],
        "approved_script_sha256": "8" * 64,
    }
    context.artifacts = (*context.artifacts, historical)
    selected = packaged_stages._resolve_v2_asset_board_manifest(context)
    assert selected["artifact_id"] == "manifest-current"

    ambiguous, _ = _manifest_context(tmp_path / "ambiguous", duplicate_current=True)
    ambiguous.artifacts = (*ambiguous.artifacts, historical)
    with pytest.raises(ReplicationError, match="ambiguous") as exc_info:
        packaged_stages._resolve_v2_asset_board_manifest(ambiguous)
    assert exc_info.value.code == "CONTRACT_INVALID"


def test_v2_manifest_rejects_noncurrent_approved_mapping_bytes_and_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(packaged_stages, "_read_json_artifact", lambda *_args, **_kwargs: {})
    context, state = _manifest_context(tmp_path)
    changed_binding = {**state["binding"], "asset_tag": "ProductB", "replaces_tag": "ProductB"}
    changed_binding_sha = hashlib.sha256(
        json.dumps([changed_binding], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    context.job_store = SimpleNamespace(
        get_script_approval=lambda *_args: {
            **state["approval"],
            "approved_edit_script": {
                **state["approval"]["approved_edit_script"],
                "asset_bindings": [changed_binding],
                "asset_bindings_sha256": changed_binding_sha,
            },
        }
    )
    with pytest.raises(ReplicationError, match="missing or ambiguous") as exc_info:
        packaged_stages._resolve_v2_asset_board_manifest(context)
    assert exc_info.value.code == "CONTRACT_INVALID"

    context, _state = _manifest_context(tmp_path / "bytes")
    manifest_descriptor = next(item for item in context.artifacts if item["artifact_id"] == "manifest-current")
    manifest_descriptor["sha256"] = "d" * 64
    with pytest.raises(ReplicationError, match="bytes differ") as exc_info:
        packaged_stages._resolve_v2_asset_board_manifest(context)
    assert exc_info.value.code == "ARTIFACT_HASH_MISMATCH"

    context, _state = _manifest_context(tmp_path / "metadata")
    manifest_descriptor = next(item for item in context.artifacts if item["artifact_id"] == "manifest-current")
    manifest_descriptor["metadata"]["asset_board_mapping_sha256"] = "e" * 64
    with pytest.raises(ReplicationError, match="metadata digests") as exc_info:
        packaged_stages._resolve_v2_asset_board_manifest(context)
    assert exc_info.value.code == "CONTRACT_INVALID"


def test_v2_single_full_source_segment_allows_same_source_and_slice_sha() -> None:
    payload = build_edit_provider_payload(
        video_url="https://media.example/full-source.mp4",
        prompt="编辑视频：@Video1 是编辑对象。",
        asset_bindings=[],
        source_video_sha256="a" * 64,
        source_slice_sha256="a" * 64,
        segment_plan_sha256="b" * 64,
        segment_id="S01",
        start_ms=0,
        end_ms=15_000,
        source_video_reference_artifact_id="source-full-S01",
        source_is_full_segment=True,
    )
    assert payload["video_reference_binding"]["source_slice_sha256"] == payload["video_reference_binding"]["source_video_sha256"]


def test_v2_equal_source_and_slice_sha_requires_explicit_full_source_contract() -> None:
    with pytest.raises(EditPromptContractError, match="SOURCE_SLICE_SHA_INVALID"):
        build_edit_provider_payload(
            video_url="https://media.example/slice-not-full.mp4",
            prompt=seedance_prompt_compiler.V2_EDIT_PROMPT_PREFIX + "@Video1",
            asset_bindings=[],
            source_video_sha256="a" * 64,
            source_slice_sha256="a" * 64,
            segment_plan_sha256="b" * 64,
            segment_id="S01",
            start_ms=5_000,
            end_ms=15_000,
            source_video_reference_artifact_id="source-slice-S01",
        )


def test_submit_provider_request_consumes_v2_image_and_video_sidecars() -> None:
    receipt = {
        "schema_version": "runninghub-asset-board/v2",
        "asset_type": "product",
        "template_version": "product-v2",
        "source_asset_sha256": "a" * 64,
        "request_sha256": "b" * 64,
        "response_sha256": "c" * 64,
        "task_id": "task-submit",
        "board_sha256": "d" * 64,
    }
    binding = [{
        "tag": "ProductA",
        "reference": "@Image1",
        "asset_type": "product",
        "board_url": "https://media.example/board-submit.png",
        "receipt": receipt,
    }]
    prompt = seedance_prompt_compiler.V2_EDIT_PROMPT_PREFIX + "@Video1 @Image1 ProductA"
    built = build_edit_provider_payload(
        video_url="https://media.example/source-submit.mp4",
        prompt=prompt,
        asset_bindings=binding,
        source_video_sha256="e" * 64,
        source_slice_sha256="f" * 64,
        segment_plan_sha256="1" * 64,
        segment_id="S01",
        start_ms=0,
        end_ms=10_000,
        source_video_reference_artifact_id="source-submit-S01",
    )
    from server.packaged_stages import SubmitProviderVideoStage

    request = SubmitProviderVideoStage._provider_request(
        built["provider_payload"],
        built["video_reference_binding"],
        image_reference_binding=built["image_reference_binding"],
        final_reference_lineage=None,
        audio_reference_binding=None,
        provider_only_binding_receipt=_provider_only_receipt(prompt),
    )
    assert request.video_reference_binding["edit_contract"] == "video-edit-v2"
    assert request.image_reference_binding["schema_version"] == "usfr-video-edit-image-binding/v1"


def test_submit_provider_request_rejects_image_binding_sha_that_does_not_match_sidecar() -> None:
    receipt = {
        "schema_version": "runninghub-asset-board/v2",
        "asset_type": "product",
        "template_version": "product-v2",
        "source_asset_sha256": "a" * 64,
        "request_sha256": "b" * 64,
        "response_sha256": "c" * 64,
        "task_id": "task-submit-sha",
        "board_sha256": "d" * 64,
    }
    built = build_edit_provider_payload(
        video_url="https://media.example/source-submit-sha.mp4",
        prompt=seedance_prompt_compiler.V2_EDIT_PROMPT_PREFIX + "@Video1 @Image1 ProductA",
        asset_bindings=[{
            "tag": "ProductA",
            "reference": "@Image1",
            "asset_type": "product",
            "board_url": "https://media.example/board-submit-sha.png",
            "receipt": receipt,
        }],
        source_video_sha256="e" * 64,
        source_slice_sha256="f" * 64,
        segment_plan_sha256="1" * 64,
        segment_id="S01",
        start_ms=0,
        end_ms=10_000,
    )
    tampered_video_binding = {
        **built["video_reference_binding"],
        "image_reference_binding_sha256": "0" * 64,
    }
    from server.packaged_stages import SubmitProviderVideoStage

    with pytest.raises(ReplicationError, match="image reference binding") as exc_info:
        SubmitProviderVideoStage._provider_request(
            built["provider_payload"],
            tampered_video_binding,
            image_reference_binding=built["image_reference_binding"],
            final_reference_lineage=None,
            audio_reference_binding=None,
            provider_only_binding_receipt=_provider_only_receipt(str(built["provider_payload"]["prompt"])),
        )
    assert exc_info.value.code == "PROMPT_INTEGRITY_FAILED"


def test_submit_provider_run_rejects_untrusted_v2_manifest_sidecar_before_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from contextlib import contextmanager
    from server.packaged_stages import SubmitProviderVideoStage

    monkeypatch.setattr(packaged_stages, "_read_json_artifact", lambda context, **_kwargs: context._audit)
    context, state = _manifest_context(tmp_path)
    entry = state["manifest"]["entries"][0]
    built = build_edit_provider_payload(
        video_url="https://media.example/source-submit-run.mp4",
        prompt=seedance_prompt_compiler.V2_EDIT_PROMPT_PREFIX + "@Video1 @Image1 ProductA",
        asset_bindings=[{
            "tag": entry["asset_tag"],
            "reference": entry["image_reference"],
            "asset_type": entry["asset_type"],
            "board_url": entry["board_url"],
            "receipt": entry["receipt"],
        }],
        source_video_sha256=state["source_video_sha"],
        source_slice_sha256="f" * 64,
        segment_plan_sha256=state["segment_plan_sha"],
        segment_id="S01",
        start_ms=0,
        end_ms=10_000,
    )
    context._audit = {
        "schema_version": "seedance-request-audit/v2",
        "edit_contract": "video-edit-v2",
        "segments": [{
            "segment_id": "S01",
            "approved_script_sha256": state["approval"]["script_sha256"],
            "source_video_sha256": state["source_video_sha"],
            "segment_plan_sha256": state["segment_plan_sha"],
            "payload_template": built["provider_payload"],
            "provider_only_binding_receipt": _provider_only_receipt(str(built["provider_payload"]["prompt"])),
            "image_reference_binding": built["image_reference_binding"],
            "video_reference_binding": built["video_reference_binding"],
            "asset_board_manifest_artifact_id": "manifest-current",
            "asset_board_manifest_sha256": "0" * 64,
        }],
    }
    context._audit["stage_fingerprint"] = packaged_stages._sha(context._audit)
    audit_path = tmp_path / "audit.json"
    audit_path.write_text(json.dumps(context._audit, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    audit_sha = hashlib.sha256(audit_path.read_bytes()).hexdigest()
    context.artifacts = (*context.artifacts, {
        "artifact_id": "audit-current",
        "kind": "seedance_request_audit",
        "sha256": audit_sha,
        "metadata": {
            "stage_fingerprint": context._audit["stage_fingerprint"],
            "approved_script_sha256": "9" * 64,
        },
    })
    original_materialize = context.materialize_artifact

    @contextmanager
    def materialize(kind: str, *, artifact_id: str, sha256: str):
        if kind == "seedance_request_audit":
            assert artifact_id == "audit-current"
            yield SimpleNamespace(path=audit_path)
            return
        with original_materialize(kind, artifact_id=artifact_id, sha256=sha256) as media:
            yield media

    context.materialize_artifact = materialize
    context.job_store.list_provider_attempts = lambda _job_id: ()
    context.job_store.get_job = lambda _job_id: SimpleNamespace(version=1, expires_at_ms=10**15)
    provider = SimpleNamespace(create_video=lambda _request: pytest.fail("provider must not be called"))
    with pytest.raises(ReplicationError, match="manifest") as exc_info:
        SubmitProviderVideoStage(provider=provider, audit_secret="secret").run(
            context=context, input_artifacts=[]
        )
    assert exc_info.value.code in {"ARTIFACT_HASH_MISMATCH", "CONTRACT_INVALID"}


def test_submit_provider_run_consumes_v2_lineage_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from contextlib import contextmanager
    from server.job_models import ProviderAttempt
    from server.packaged_stages import SubmitProviderVideoStage

    monkeypatch.setattr(packaged_stages, "_read_json_artifact", lambda context, **_kwargs: context._audit)
    monkeypatch.setattr(
        packaged_stages,
        "mint_audio_provider_authorization",
        lambda **_kwargs: ({"schema_version": "test"}, lambda *_args, **_kwargs: None),
    )
    context, state = _manifest_context(tmp_path)
    entry = state["manifest"]["entries"][0]
    built = build_edit_provider_payload(
        video_url="https://media.example/source-submit-idempotent.mp4",
        prompt=seedance_prompt_compiler.V2_EDIT_PROMPT_PREFIX + "@Video1 @Image1 ProductA",
        asset_bindings=[{
            "tag": entry["asset_tag"],
            "reference": entry["image_reference"],
            "asset_type": entry["asset_type"],
            "board_url": entry["board_url"],
            "source_slot": entry["source_slot"],
            "source_index": entry["source_index"],
            "source_asset_sha256": entry["source_asset_sha256"],
            "replaces_tag": entry["replaces_tag"],
            "board_artifact_id": entry["board_artifact_id"],
            "board_sha256": entry["board_sha256"],
            "receipt": entry["receipt"],
        }],
        source_video_sha256=state["source_video_sha"],
        source_slice_sha256="f" * 64,
        segment_plan_sha256=state["segment_plan_sha"],
        segment_id="S01",
        start_ms=0,
        end_ms=10_000,
    )
    context._audit = {
        "schema_version": "seedance-request-audit/v2",
        "edit_contract": "video-edit-v2",
        "segments": [{
            "segment_id": "S01",
            "approved_script_sha256": state["approval"]["script_sha256"],
            "source_video_sha256": state["source_video_sha"],
            "segment_plan_sha256": state["segment_plan_sha"],
            "payload_template": built["provider_payload"],
            "provider_only_binding_receipt": _provider_only_receipt(str(built["provider_payload"]["prompt"])),
            "image_reference_binding": built["image_reference_binding"],
            "video_reference_binding": built["video_reference_binding"],
            "asset_board_manifest_artifact_id": "manifest-current",
            "asset_board_manifest_sha256": next(
                item["sha256"] for item in context.artifacts if item["artifact_id"] == "manifest-current"
            ),
            "approved_script_sha256": "9" * 64,
        }],
    }
    context._audit["stage_fingerprint"] = packaged_stages._sha(context._audit)
    audit_path = tmp_path / "audit.json"
    audit_path.write_text(json.dumps(context._audit, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    audit_sha = hashlib.sha256(audit_path.read_bytes()).hexdigest()
    context.artifacts = (*context.artifacts, {
        "artifact_id": "audit-current",
        "kind": "seedance_request_audit",
        "sha256": audit_sha,
        "metadata": {
            "stage_fingerprint": context._audit["stage_fingerprint"],
            "approved_script_sha256": "9" * 64,
        },
    })
    original_materialize = context.materialize_artifact

    @contextmanager
    def materialize(kind: str, *, artifact_id: str, sha256: str):
        if kind == "seedance_request_audit":
            yield SimpleNamespace(path=audit_path)
            return
        with original_materialize(kind, artifact_id=artifact_id, sha256=sha256) as media:
            yield media

    context.materialize_artifact = materialize

    class Store:
        def __init__(self) -> None:
            self.snapshot = SimpleNamespace(version=1, expires_at_ms=10**15)
            self.attempts: list[ProviderAttempt] = []

        def get_script_approval(self, *_args):
            return state["approval"]

        def get_job(self, _job_id):
            return self.snapshot

        def list_provider_attempts(self, _job_id):
            return tuple(self.attempts)

        def begin_provider_attempt(self, **kwargs):
            attempt = ProviderAttempt(
                attempt_id=f"attempt-{len(self.attempts) + 1}",
                operation=kwargs["operation"],
                request_sha256=kwargs["request_sha256"],
                status="SUBMITTING",
                segment_id=kwargs["segment_id"],
                segment_plan_sha256=kwargs["segment_plan_sha256"],
            )
            self.attempts.append(attempt)
            self.snapshot.version += 1
            return attempt

        def update_provider_attempt(self, *, expected_version, attempt, **_kwargs):
            assert expected_version == self.snapshot.version
            self.attempts = [
                attempt if item.attempt_id == attempt.attempt_id else item
                for item in self.attempts
            ]
            self.snapshot.version += 1
            return self.snapshot

    store = Store()
    context.job_store = store
    create_count = {"value": 0}
    provider_payload_sha = packaged_stages._sha(built["provider_payload"])

    def create_video(_request):
        create_count["value"] += 1
        if create_count["value"] > 1:
            raise ConnectionError("provider connection lost after submission")
        return {
            "task_id": "task-created",
            "receipt": {
                "request_sha256": provider_payload_sha,
                "response_sha256": "c" * 64,
                "task_id": "task-created",
            },
        }

    stage = SubmitProviderVideoStage(
        provider=SimpleNamespace(create_video=create_video),
        audit_secret="secret",
    )
    first = stage.run(context=context, input_artifacts=[])
    second = stage.run(context=context, input_artifacts=[])
    assert first["provider_attempts"][0]["status"] == "RUNNING"
    assert second["provider_attempts"][0]["status"] == "RUNNING"
    assert create_count["value"] == 1
    assert len(store.attempts) == 1
    assert store.attempts[0].request_sha256 != provider_payload_sha

    context._audit["segments"][0]["retry"] = {
        "confirmed": True,
        "failure_type": "confirmed_provider_failure",
    }
    context._audit.pop("stage_fingerprint", None)
    context._audit["stage_fingerprint"] = packaged_stages._sha(context._audit)
    audit_path.write_text(json.dumps(context._audit, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    audit_descriptor = next(item for item in context.artifacts if item["artifact_id"] == "audit-current")
    audit_descriptor["sha256"] = hashlib.sha256(audit_path.read_bytes()).hexdigest()
    audit_descriptor["metadata"]["stage_fingerprint"] = context._audit["stage_fingerprint"]
    store.attempts[0] = replace(store.attempts[0], status="FAILED", failure_kind="provider")
    with pytest.raises(ReplicationError, match="retry|reconcile") as exc_info:
        stage.run(context=context, input_artifacts=[])
    assert exc_info.value.code == "PROVIDER_RETRY_INVALID"
    assert create_count["value"] == 1
    assert len(store.attempts) == 1


def _submit_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    mint,
):
    from contextlib import contextmanager
    from server.job_models import ProviderAttempt

    monkeypatch.setattr(packaged_stages, "_read_json_artifact", lambda context, **_kwargs: context._audit)
    monkeypatch.setattr(packaged_stages, "mint_audio_provider_authorization", mint)
    context, state = _manifest_context(tmp_path)
    entry = state["manifest"]["entries"][0]
    built = build_edit_provider_payload(
        video_url="https://media.example/source-submit-state.mp4",
        prompt=seedance_prompt_compiler.V2_EDIT_PROMPT_PREFIX + "@Video1 @Image1 ProductA",
        asset_bindings=[{
            "tag": entry["asset_tag"],
            "reference": entry["image_reference"],
            "asset_type": entry["asset_type"],
            "board_url": entry["board_url"],
            "source_slot": entry["source_slot"],
            "source_index": entry["source_index"],
            "source_asset_sha256": entry["source_asset_sha256"],
            "replaces_tag": entry["replaces_tag"],
            "board_artifact_id": entry["board_artifact_id"],
            "board_sha256": entry["board_sha256"],
            "receipt": entry["receipt"],
        }],
        source_video_sha256=state["source_video_sha"],
        source_slice_sha256="f" * 64,
        segment_plan_sha256=state["segment_plan_sha"],
        segment_id="S01",
        start_ms=0,
        end_ms=10_000,
        source_video_reference_artifact_id="source-slice-S01",
    )
    context._audit = {
        "schema_version": "seedance-request-audit/v2",
        "edit_contract": "video-edit-v2",
        "segments": [{
            "segment_id": "S01",
            "approved_script_sha256": state["approval"]["script_sha256"],
            "source_video_sha256": state["source_video_sha"],
            "segment_plan_sha256": state["segment_plan_sha"],
            "payload_template": built["provider_payload"],
            "provider_only_binding_receipt": _provider_only_receipt(str(built["provider_payload"]["prompt"])),
            "image_reference_binding": built["image_reference_binding"],
            "video_reference_binding": built["video_reference_binding"],
            "asset_board_manifest_artifact_id": "manifest-current",
            "asset_board_manifest_sha256": next(
                item["sha256"] for item in context.artifacts if item["artifact_id"] == "manifest-current"
            ),
            "approved_script_sha256": "9" * 64,
        }],
    }
    context._audit["stage_fingerprint"] = packaged_stages._sha(context._audit)
    audit_path = tmp_path / "submit-state-audit.json"
    audit_path.write_text(json.dumps(context._audit, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    audit_sha = hashlib.sha256(audit_path.read_bytes()).hexdigest()
    context.artifacts = (*context.artifacts, {
        "artifact_id": "audit-current",
        "kind": "seedance_request_audit",
        "sha256": audit_sha,
        "metadata": {
            "stage_fingerprint": context._audit["stage_fingerprint"],
            "approved_script_sha256": "9" * 64,
        },
    })
    original_materialize = context.materialize_artifact

    @contextmanager
    def materialize(kind: str, *, artifact_id: str, sha256: str):
        if kind == "seedance_request_audit":
            yield SimpleNamespace(path=audit_path)
            return
        with original_materialize(kind, artifact_id=artifact_id, sha256=sha256) as media:
            yield media

    context.materialize_artifact = materialize

    class Store:
        def __init__(self) -> None:
            self.snapshot = SimpleNamespace(version=1, expires_at_ms=10**15)
            self.attempts: list[ProviderAttempt] = []

        def get_script_approval(self, *_args):
            return state["approval"]

        def get_job(self, _job_id):
            return self.snapshot

        def list_provider_attempts(self, _job_id):
            return tuple(self.attempts)

        def begin_provider_attempt(self, **kwargs):
            attempt = ProviderAttempt(
                attempt_id=f"attempt-{len(self.attempts) + 1}",
                operation=kwargs["operation"],
                request_sha256=kwargs["request_sha256"],
                status="SUBMITTING",
                segment_id=kwargs["segment_id"],
                segment_plan_sha256=kwargs["segment_plan_sha256"],
            )
            self.attempts.append(attempt)
            self.snapshot.version += 1
            return attempt

        def update_provider_attempt(self, *, expected_version, attempt, **_kwargs):
            assert expected_version == self.snapshot.version
            self.attempts = [
                attempt if item.attempt_id == attempt.attempt_id else item
                for item in self.attempts
            ]
            self.snapshot.version += 1
            return self.snapshot

    store = Store()
    context.job_store = store
    return context, store, built


def _valid_submit_mint(**_kwargs):
    return ({"schema_version": "test"}, lambda *_args, **_kwargs: None)


def test_submit_provider_run_reuses_succeeded_same_intent_without_create(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from server.job_models import ProviderAttempt
    from server.packaged_stages import SubmitProviderVideoStage

    context, store, built = _submit_fixture(tmp_path, monkeypatch, mint=_valid_submit_mint)
    create_count = {"value": 0}
    provider_payload_sha = packaged_stages._sha(built["provider_payload"])

    def create_video(_request):
        create_count["value"] += 1
        return {
            "task_id": "task-success",
            "receipt": {
                "request_sha256": provider_payload_sha,
                "response_sha256": "c" * 64,
                "task_id": "task-success",
            },
        }

    stage = SubmitProviderVideoStage(
        provider=SimpleNamespace(create_video=create_video),
        audit_secret="secret",
    )
    first = stage.run(context=context, input_artifacts=[])
    assert first["provider_attempts"][0]["status"] == "RUNNING"
    store.attempts[0] = ProviderAttempt(
        **{
            **store.attempts[0].to_dict(),
            "status": "SUCCEEDED",
            "provider_task_id": "task-success",
            "response_sha256": "c" * 64,
        }
    )
    store.attempts.append(
        ProviderAttempt(
            attempt_id="attempt-history",
            operation="CreateVideo",
            request_sha256=store.attempts[0].request_sha256,
            status="FAILED",
            segment_id="S01",
            segment_plan_sha256="1" * 64,
        )
    )
    second = stage.run(context=context, input_artifacts=[])
    assert second["provider_attempts"] == [{
        "segment_id": "S01",
        "attempt_id": "attempt-1",
        "task_id": "task-success",
        "status": "SUCCEEDED",
    }]
    assert create_count["value"] == 1
    assert len(store.attempts) == 2


@pytest.mark.parametrize("invalid_receipt", ["missing_task", "request_mismatch"])
def test_submit_provider_unverifiable_create_result_is_ambiguous(
    invalid_receipt: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from server.packaged_stages import SubmitProviderVideoStage

    context, store, built = _submit_fixture(tmp_path, monkeypatch, mint=_valid_submit_mint)
    provider_payload_sha = packaged_stages._sha(built["provider_payload"])
    create_count = {"value": 0}

    def create_video(_request):
        create_count["value"] += 1
        task_id = "" if invalid_receipt == "missing_task" else "task-unverifiable"
        request_sha = "0" * 64 if invalid_receipt == "request_mismatch" else provider_payload_sha
        return {
            "task_id": task_id,
            "receipt": {
                "request_sha256": request_sha,
                "response_sha256": "f" * 64,
                "task_id": task_id,
            },
        }

    stage = SubmitProviderVideoStage(
        provider=SimpleNamespace(create_video=create_video),
        audit_secret="secret",
    )
    with pytest.raises(ReplicationError, match="unverifiable|ambiguous") as exc_info:
        stage.run(context=context, input_artifacts=[])
    assert exc_info.value.code == "PROVIDER_AMBIGUOUS"
    assert store.attempts[0].status == "AMBIGUOUS"

    with pytest.raises(ReplicationError, match="reconcile") as second_exc:
        stage.run(context=context, input_artifacts=[])
    assert second_exc.value.code == "PROVIDER_AMBIGUOUS"
    assert create_count["value"] == 1


@pytest.mark.parametrize("active_status", ["RUNNING", "AMBIGUOUS"])
def test_submit_provider_checks_active_state_before_retry_budget(
    active_status: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from server.job_models import ProviderAttempt
    from server.packaged_stages import SubmitProviderVideoStage

    context, store, built = _submit_fixture(tmp_path, monkeypatch, mint=_valid_submit_mint)
    provider_payload_sha = packaged_stages._sha(built["provider_payload"])
    create_count = {"value": 0}

    def create_video(_request):
        create_count["value"] += 1
        return {
            "task_id": "task-active-order",
            "receipt": {
                "request_sha256": provider_payload_sha,
                "response_sha256": "a" * 64,
                "task_id": "task-active-order",
            },
        }

    stage = SubmitProviderVideoStage(
        provider=SimpleNamespace(create_video=create_video),
        audit_secret="secret",
    )
    first = stage.run(context=context, input_artifacts=[])
    assert first["provider_attempts"][0]["status"] == "RUNNING"
    store.attempts[0] = ProviderAttempt(
        **{**store.attempts[0].to_dict(), "status": active_status}
    )
    store.attempts.append(
        ProviderAttempt(
            attempt_id="attempt-history",
            operation="CreateVideo",
            request_sha256="b" * 64,
            status="FAILED",
            segment_id="S01",
            segment_plan_sha256="1" * 64,
        )
    )
    if active_status == "RUNNING":
        result = stage.run(context=context, input_artifacts=[])
        assert result["provider_attempts"][0]["status"] == "RUNNING"
    else:
        with pytest.raises(ReplicationError, match="reconcile") as exc_info:
            stage.run(context=context, input_artifacts=[])
        assert exc_info.value.code == "PROVIDER_AMBIGUOUS"
    assert create_count["value"] == 1


@pytest.mark.parametrize("historical_failure_kind", ["preflight", None])
def test_wait_provider_ignores_historical_failed_attempts_and_polls_running(
    historical_failure_kind: str | None,
    tmp_path: Path,
) -> None:
    from server.job_models import ProviderAttempt
    from server.packaged_stages import WaitProviderVideoStage

    failed = ProviderAttempt(
        attempt_id="attempt-failed",
        operation="CreateVideo",
        request_sha256="a" * 64,
        status="FAILED",
        segment_id="S01",
        segment_plan_sha256="b" * 64,
        failure_kind=historical_failure_kind,
    )
    running = ProviderAttempt(
        attempt_id="attempt-running",
        operation="CreateVideo",
        request_sha256="c" * 64,
        status="RUNNING",
        segment_id="S01",
        segment_plan_sha256="b" * 64,
        provider_task_id="task-running",
    )

    class Store:
        def __init__(self) -> None:
            self.attempts = [failed, running]
            self.snapshot = SimpleNamespace(expires_at_ms=10**15, version=1)

        def list_provider_attempts(self, _job_id):
            return tuple(self.attempts)

        def get_job(self, _job_id):
            return self.snapshot

        def update_provider_attempt(self, *, attempt, **_kwargs):
            self.attempts = [attempt if item.attempt_id == attempt.attempt_id else item for item in self.attempts]
            self.snapshot.version += 1
            return self.snapshot

    store = Store()

    class Provider:
        def lookup(self, intent):
            assert intent == {"taskId": "task-running"}
            return {"status": "SUCCESS"}

        def download(self, task_id, destination):
            assert task_id == "task-running"
            destination.write_bytes(b"\x00\x00\x00\x18ftypisom-result")
            return {"task_id": task_id, "response_sha256": "d" * 64}

    context = SimpleNamespace(
        job_id="job-wait-history",
        job_store=store,
        work_dir=tmp_path,
        publish_bytes=lambda **kwargs: {"artifact_id": "video-result", "sha256": kwargs["expected_sha256"]},
    )
    result = WaitProviderVideoStage(provider=Provider(), poll_seconds=0, timeout_seconds=1).run(
        context=context, input_artifacts=[]
    )
    assert result["provider_videos"][0]["segment_id"] == "S01"
    assert store.attempts[1].status == "SUCCEEDED"


def test_submit_provider_adapter_preflight_failure_is_failed_not_ambiguous(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from server.packaged_stages import SubmitProviderVideoStage
    from server.production_ports import ProductionPortsError

    context, store, _built = _submit_fixture(tmp_path, monkeypatch, mint=_valid_submit_mint)
    calls = {"value": 0}

    def create_video(_request):
        calls["value"] += 1
        raise ProductionPortsError("RunningHub Seedance authorization preflight rejected")

    with pytest.raises(ReplicationError, match="preflight") as exc_info:
        SubmitProviderVideoStage(
            provider=SimpleNamespace(create_video=create_video),
            audit_secret="secret",
        ).run(context=context, input_artifacts=[])
    assert exc_info.value.code == "PROVIDER_PREFLIGHT_FAILED"
    assert store.attempts[0].status == "FAILED"
    assert store.attempts[0].failure_kind == "preflight"
    assert calls["value"] == 1


def test_submit_provider_run_missing_secret_does_not_reserve_attempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from server.packaged_stages import SubmitProviderVideoStage

    context, store, _built = _submit_fixture(tmp_path, monkeypatch, mint=_valid_submit_mint)
    with pytest.raises(ReplicationError, match="authorization secret") as exc_info:
        SubmitProviderVideoStage(
            provider=SimpleNamespace(create_video=lambda _request: pytest.fail("provider must not be called")),
            audit_secret=None,
        ).run(context=context, input_artifacts=[])
    assert exc_info.value.code == "CAPABILITY_UNAVAILABLE"
    assert store.attempts == []


def test_submit_provider_preflight_failures_are_terminal_for_attempt_but_not_retry_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from server.audio_provider_authorization import AudioProviderAuthorizationError
    from server.packaged_stages import SubmitProviderVideoStage

    phase = {"value": "mint-fails"}

    def mint(**_kwargs):
        if phase["value"] == "mint-fails":
            raise AudioProviderAuthorizationError("mint failed locally")
        return _valid_submit_mint()

    context, store, built = _submit_fixture(tmp_path, monkeypatch, mint=mint)
    provider_payload_sha = packaged_stages._sha(built["provider_payload"])
    create_count = {"value": 0}

    def create_video(_request):
        create_count["value"] += 1
        return {
            "task_id": "task-after-preflight",
            "receipt": {
                "request_sha256": provider_payload_sha,
                "response_sha256": "d" * 64,
                "task_id": "task-after-preflight",
            },
        }

    stage = SubmitProviderVideoStage(
        provider=SimpleNamespace(create_video=create_video),
        audit_secret="secret",
    )
    with pytest.raises(ReplicationError, match="authorization cannot be minted") as exc_info:
        stage.run(context=context, input_artifacts=[])
    assert exc_info.value.code == "PROMPT_INTEGRITY_FAILED"
    assert store.attempts[0].status == "FAILED"
    assert store.attempts[0].failure_kind == "preflight"

    phase["value"] = "ok"
    result = stage.run(context=context, input_artifacts=[])
    assert result["provider_attempts"][0]["status"] == "RUNNING"
    assert len(store.attempts) == 2
    assert create_count["value"] == 1


def test_submit_provider_local_pre_call_failure_is_not_ambiguous_or_retry_consuming(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from server.packaged_stages import SubmitProviderVideoStage

    context, store, built = _submit_fixture(tmp_path, monkeypatch, mint=_valid_submit_mint)

    class BrokenPayload(dict):
        @property
        def audio_provider_authorization(self):
            return None

        @audio_provider_authorization.setter
        def audio_provider_authorization(self, _value):
            raise RuntimeError("local request assembly failed")

    original_provider_request = SubmitProviderVideoStage._provider_request
    monkeypatch.setattr(
        SubmitProviderVideoStage,
        "_provider_request",
        staticmethod(lambda *_args, **_kwargs: BrokenPayload()),
    )
    stage = SubmitProviderVideoStage(
        provider=SimpleNamespace(create_video=lambda _request: pytest.fail("provider must not be called")),
        audit_secret="secret",
    )
    with pytest.raises(ReplicationError, match="before provider call") as exc_info:
        stage.run(context=context, input_artifacts=[])
    assert exc_info.value.code == "PROVIDER_PREFLIGHT_FAILED"
    assert store.attempts[0].status == "FAILED"
    assert store.attempts[0].failure_kind == "preflight"

    monkeypatch.setattr(SubmitProviderVideoStage, "_provider_request", staticmethod(original_provider_request))
    built_sha = packaged_stages._sha(built["provider_payload"])
    monkeypatch.setattr(
        packaged_stages,
        "mint_audio_provider_authorization",
        _valid_submit_mint,
    )
    stage = SubmitProviderVideoStage(
        provider=SimpleNamespace(create_video=lambda _request: {
            "task_id": "task-after-local-preflight",
            "receipt": {
                "request_sha256": built_sha,
                "response_sha256": "e" * 64,
                "task_id": "task-after-local-preflight",
            },
        }),
        audit_secret="secret",
    )
    result = stage.run(context=context, input_artifacts=[])
    assert result["provider_attempts"][0]["status"] == "RUNNING"
    assert len(store.attempts) == 2


def test_v2_provider_payload_rejects_unbound_target_changes() -> None:
    with pytest.raises(EditPromptContractError, match="TARGET_CHANGES_NOT_APPROVED"):
        build_edit_provider_payload(
            video_url="https://media.example/source-target.mp4",
            prompt=seedance_prompt_compiler.V2_EDIT_PROMPT_PREFIX + "@Video1",
            asset_bindings=[],
            source_video_sha256="a" * 64,
            source_slice_sha256="b" * 64,
            segment_plan_sha256="c" * 64,
            segment_id="S01",
            start_ms=0,
            end_ms=10_000,
            source_video_reference_artifact_id="source-target-S01",
            target_changes=[{"kind": "replacement", "target": "forged"}],
        )


def test_approved_edit_script_change_contract_round_trips_through_redis_canonicalization() -> None:
    import fakeredis

    from server.redis_job_store import RedisEphemeralJobStore
    from server.review_models import RevisionManifest
    from server.visible_text_contract import visible_text_locks_sha256

    store = RedisEphemeralJobStore(
        fakeredis.FakeRedis(decode_responses=False), prefix="v2-approved-edit"
    )
    job = store.create_job(
        slots_manifest={"admission": {"can_proceed": True}},
        capability_token_hash="a" * 64,
        ttl_seconds=3600,
    )
    script_sha = "b" * 64
    line_contracts_sha = hashlib.sha256(b"[]").hexdigest()
    change_rows = [
        {
            "change_id": "CH07",
            "kind": "language",
            "start_ms": 7000,
            "end_ms": 8000,
            "speaker": "PersonA",
            "language": "ja",
            "text": "Approved localized line",
        },
        {
            "change_id": "CH02",
            "kind": "replacement",
            "start_ms": 2000,
            "end_ms": 3000,
            "asset_tag": "ModelA",
            "instruction": "Replace the named person with the approved model asset.",
        },
        {
            "change_id": "CH05",
            "kind": "replacement",
            "start_ms": 5000,
            "end_ms": 6000,
            "asset_tag": "SceneA",
            "instruction": "Replace the scene with the approved scene asset.",
        },
        {
            "change_id": "CH01",
            "kind": "dialogue",
            "start_ms": 1000,
            "end_ms": 2000,
            "speaker": "PersonA",
            "text": "Approved neutral line",
        },
        {
            "change_id": "CH06",
            "kind": "replacement",
            "start_ms": 6000,
            "end_ms": 7000,
            "asset_tag": "AppA",
            "instruction": "Replace the app proof with the approved app asset.",
        },
        {
            "change_id": "CH04",
            "kind": "text",
            "start_ms": 4000,
            "end_ms": 5000,
            "text_target": "title-main",
            "layer": "overlay",
            "text": "Approved title",
        },
        {
            "change_id": "CH03",
            "kind": "replacement",
            "start_ms": 3000,
            "end_ms": 4000,
            "asset_tag": "ProductA",
            "instruction": "Replace the product with the approved product asset.",
        },
        {
            "change_id": "CH08",
            "kind": "replacement",
            "start_ms": 8000,
            "end_ms": 9000,
            "asset_tag": "GarmentA",
            "instruction": "Replace the garment with the approved garment asset.",
        },
    ]
    canonical_rows = sorted(change_rows, key=lambda row: (row["start_ms"], row["end_ms"], row["change_id"]))
    change_rows_sha = hashlib.sha256(
        json.dumps(canonical_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    asset_bindings = [
        {
            "source_slot": "new_product_image",
            "source_index": 0,
            "source_asset_sha256": "d" * 64,
            "asset_type": "product",
            "asset_tag": "ProductA",
            "replaces_tag": "ProductA",
        },
        {
            "source_slot": "new_model_image",
            "source_index": 2,
            "source_asset_sha256": "c" * 64,
            "asset_type": "scene",
            "asset_tag": "SceneA",
            "replaces_tag": "SceneA",
        },
        {
            "source_slot": "app_evidence_bundle",
            "source_index": 0,
            "source_asset_sha256": "f" * 64,
            "asset_type": "app",
            "asset_tag": "AppA",
            "replaces_tag": "AppA",
            "source_artifact_id": "app-evidence-001",
        },
        {
            "source_slot": "new_model_image",
            "source_index": 1,
            "source_asset_sha256": "e" * 64,
            "asset_type": "garment",
            "asset_tag": "GarmentA",
            "replaces_tag": "PersonA",
        },
        {
            "source_slot": "new_model_image",
            "source_index": 0,
            "source_asset_sha256": "a" * 64,
            "asset_type": "model",
            "asset_tag": "ModelA",
            "replaces_tag": "PersonA",
        },
    ]
    asset_slot_order = {"new_model_image": 0, "new_product_image": 1, "app_evidence_bundle": 4}
    canonical_asset_bindings = [
        {**binding, "image_reference": f"@Image{index}"}
        for index, binding in enumerate(
            sorted(asset_bindings, key=lambda row: (asset_slot_order[row["source_slot"]], row["source_index"], row["asset_tag"])),
            start=1,
        )
    ]
    asset_bindings_sha = hashlib.sha256(
        json.dumps(canonical_asset_bindings, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    approval = {
        "contract": "approved-script-lines/v2",
        "revision": 1,
        "script_sha256": script_sha,
        "source_content_timeline_sha256": "c" * 64,
        "line_contracts": [],
        "line_contracts_sha256": line_contracts_sha,
        "visible_text_locks": [],
        "visible_text_locks_sha256": visible_text_locks_sha256([]),
        "approved_edit_script": {
            "contract": "approved-edit-script/v1",
            "asset_bindings": asset_bindings,
            "asset_bindings_sha256": asset_bindings_sha,
            "change_rows": change_rows,
            "change_rows_sha256": change_rows_sha,
        },
    }
    manifest = RevisionManifest.script(
        revision=1,
        object_key="scripts/revision-1.json",
        sha256=script_sha,
        inputs_sha256="d" * 64,
    )
    snapshot = store.append_revision(
        job_id=job.job_id,
        kind="script",
        expected_version=job.version,
        manifest=manifest,
        invalidate_downstream=True,
        ttl_seconds=3600,
    )
    approved_snapshot = store.approve_revision(
        job_id=job.job_id,
        kind="script",
        revision=1,
        expected_version=snapshot.version,
        expected_sha256=script_sha,
        script_approval=approval,
        ttl_seconds=3600,
    )
    round_trip = store.get_script_approval(job.job_id, 1)
    assert round_trip["contract"] == "approved-script-lines/v2"
    assert round_trip["approved_edit_script"]["asset_bindings"] == canonical_asset_bindings
    assert round_trip["approved_edit_script"]["change_rows"] == canonical_rows
    assert approved_snapshot.approved_script_sha256 == script_sha
    with pytest.raises(ReplicationError, match="change_rows_sha256") as exc_info:
        store.approve_revision(
            job_id=job.job_id,
            kind="script",
            revision=1,
            expected_version=approved_snapshot.version,
            expected_sha256=script_sha,
            script_approval={**approval, "approved_edit_script": {
                **approval["approved_edit_script"], "change_rows_sha256": "e" * 64
            }},
            ttl_seconds=3600,
        )
    assert exc_info.value.code == "INVALID_INPUT"
    with pytest.raises(ReplicationError, match="positive integer") as exc_info:
        store.get_script_approval(job.job_id, 0)
    assert exc_info.value.code == "INVALID_INPUT"


def test_asset_board_stage_consumes_only_approved_asset_bindings_and_publishes_receipts(tmp_path: Path) -> None:
    from contextlib import contextmanager

    source_files = {
        "model": tmp_path / "model.png",
        "garment": tmp_path / "garment.png",
        "scene": tmp_path / "scene.png",
        "product": tmp_path / "product.png",
        "app": tmp_path / "app-store-proof.png",
    }
    for name, path in source_files.items():
        path.write_bytes(name.encode())
    sha = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in source_files.items()}
    app_store_path = tmp_path / "app-store-screenshot.png"
    app_store_path.write_bytes(b"app-store-screenshot")
    app_store_sha = hashlib.sha256(app_store_path.read_bytes()).hexdigest()
    app_store_evidence_path = tmp_path / "app-store-evidence.json"
    app_store_evidence_path.write_text(json.dumps({
        "contract": "app-store-evidence",
        "contract_version": 1,
        "store_app_id": "demo",
        "screenshots": [{
            "file_path": app_store_path.name,
            "sha256": app_store_sha,
            "content_type": "image/png",
            "store_media_ordinal": 1,
            "source_url": "https://store.example/app",
        }],
    }), encoding="utf-8")
    app_store_evidence_sha = hashlib.sha256(app_store_evidence_path.read_bytes()).hexdigest()
    bundle_path = tmp_path / "app-evidence-bundle.json"
    bundle_value = {
        "schema_version": "app-evidence-bundle/v1",
        "official_url_evidence": {
            "artifact_id": "app-url-1",
            "sha256": app_store_evidence_sha,
            "url": "https://store.example/app",
            "verified": True,
        },
        "members": [
            {"artifact_id": "app-ui-1", "sha256": sha["app"], "kind": "ui_screenshot", "order": 1},
            {"artifact_id": "app-store-1", "sha256": app_store_sha, "kind": "app_store_screenshot", "order": 2},
        ],
    }
    bundle_path.write_text(json.dumps(bundle_value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    bundle_sha = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + (1).to_bytes(4, "big") * 2 + bytes([8, 6, 0, 0, 0])
    bindings = [
        {"source_slot": "new_model_image", "source_index": 0, "source_asset_sha256": sha["model"], "asset_type": "model", "asset_tag": "ModelA", "replaces_tag": "PersonA", "image_reference": "@Image1"},
        {"source_slot": "new_model_image", "source_index": 1, "source_asset_sha256": sha["garment"], "asset_type": "garment", "asset_tag": "GarmentA", "replaces_tag": "PersonA", "image_reference": "@Image2"},
        {"source_slot": "new_model_image", "source_index": 2, "source_asset_sha256": sha["scene"], "asset_type": "scene", "asset_tag": "SceneA", "replaces_tag": "SceneA", "image_reference": "@Image3"},
        {"source_slot": "new_product_image", "source_index": 0, "source_asset_sha256": sha["product"], "asset_type": "product", "asset_tag": "ProductA", "replaces_tag": "ProductA", "image_reference": "@Image4"},
        {"source_slot": "app_evidence_bundle", "source_index": 0, "source_asset_sha256": bundle_sha, "asset_type": "app", "asset_tag": "AppA", "replaces_tag": "AppA", "source_artifact_id": "app-evidence-1", "image_reference": "@Image5"},
    ]
    asset_bindings_sha = hashlib.sha256(json.dumps(bindings, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    approval = {
        "contract": "approved-script-lines/v2",
        "script_sha256": "b" * 64,
        "approved_edit_script": {
            "contract": "approved-edit-script/v1",
            "asset_bindings": bindings,
            "asset_bindings_sha256": asset_bindings_sha,
            "change_rows": [],
            "change_rows_sha256": hashlib.sha256(b"[]").hexdigest(),
        },
    }
    calls: list[list[dict[str, object]]] = []
    workflow = SimpleNamespace(
        run_asset_board_batch=lambda rows: calls.append([dict(row) for row in rows]) or [
            {
                "tag": row["asset_tag"],
                "asset_type": row["asset_type"],
                "board_url": f"https://media.example/{row['asset_tag']}.png",
                    "board_bytes": png_bytes,
                    "board_sha256": hashlib.sha256(png_bytes).hexdigest(),
                    "task_id": f"task-{row['asset_tag']}",
                    "receipt": {
                    "schema_version": "runninghub-asset-board/v2",
                    "asset_type": row["asset_type"],
                    "template_version": _asset_board_template_version(row["asset_type"]),
                    "source_asset_sha256": row["source_asset_sha256"],
                    "request_sha256": "1" * 64,
                    "response_sha256": "2" * 64,
                    "task_id": f"task-{row['asset_tag']}",
                    "board_sha256": hashlib.sha256(png_bytes).hexdigest(),
                    "provider_asset_board_contract_sha256": _provider_asset_board_contract(row["asset_type"], row["source_asset_sha256"], "1" * 64),
                    "provider_receipt": {"request_sha256": "1" * 64, "response_sha256": "2" * 64, "task_id": f"task-{row['asset_tag']}"},
                },
            }
            for row in rows
        ],
    )
    published: list[dict[str, object]] = []

    @contextmanager
    def materialize_slot(slot_id: str, *, index: int = 0):
        mapping = {
            ("new_model_image", 0): source_files["model"],
            ("new_model_image", 1): source_files["garment"],
            ("new_model_image", 2): source_files["scene"],
            ("new_product_image", 0): source_files["product"],
        }
        yield SimpleNamespace(path=mapping[(slot_id, index)])

    @contextmanager
    def materialize_artifact(kind: str, *, artifact_id: str, sha256: str):
        if (kind, artifact_id) == ("app_evidence_bundle", "app-evidence-1"):
            assert sha256 == bundle_sha
            yield SimpleNamespace(path=bundle_path)
        else:
            member_paths = {
                ("app_store_evidence", "app-url-1"): app_store_evidence_path,
                ("ui_screenshot", "app-ui-1"): source_files["app"],
                ("app_store_screenshot", "app-store-1"): app_store_path,
            }
            yield SimpleNamespace(path=member_paths[(kind, artifact_id)])

    def publish_bytes(**kwargs):
        row = {
            "artifact_id": f"published-{len(published) + 1}",
            "kind": kwargs["kind"],
            "sha256": kwargs["expected_sha256"],
            "metadata": kwargs.get("metadata", {}),
            "data": kwargs.get("data"),
        }
        published.append(row)
        return row

    context = SimpleNamespace(
        job_id="job-asset-stage",
        snapshot=SimpleNamespace(
            current_script_revision=1,
            approved_script_sha256="b" * 64,
            slots_manifest={
                "slots": {
                    "new_model_image": {"present": True, "sha256": [sha["model"], sha["garment"], sha["scene"]]},
                    "new_product_image": {"present": True, "sha256": [sha["product"]]},
                    "ui_screenshot": {"present": False, "sha256": []},
                    "app_store_url": {"present": True, "sha256": [sha["app"]]},
                }
            },
        ),
        job_store=SimpleNamespace(get_script_approval=lambda *_args: approval),
        artifacts=(
            {"artifact_id": "app-evidence-1", "kind": "app_evidence_bundle", "sha256": bundle_sha, "metadata": {"member_sha256s": [sha["app"], app_store_sha], "member_order": ["app-ui-1", "app-store-1"]}},
            {"artifact_id": "app-url-1", "kind": "app_store_evidence", "sha256": app_store_evidence_sha, "metadata": {}},
            {"artifact_id": "app-ui-1", "kind": "ui_screenshot", "sha256": sha["app"], "metadata": {}},
            {"artifact_id": "app-store-1", "kind": "app_store_screenshot", "sha256": app_store_sha, "metadata": {}},
        ),
        materialize_slot=materialize_slot,
        materialize_artifact=materialize_artifact,
        publish_bytes=publish_bytes,
    )
    stage = packaged_stages.AssetBoardStage(workflow_client=workflow)
    result = stage.run(context=context, input_artifacts=[])
    assert [row["asset_tag"] for row in calls[0]] == ["ModelA", "GarmentA", "SceneA", "ProductA", "AppA"]
    assert [row["image_reference"] for row in calls[0]] == ["@Image1", "@Image2", "@Image3", "@Image4", "@Image5"]
    assert len(result["asset_board_receipts"]) == 5
    assert len([row for row in published if row["kind"] == "asset_board"]) == 5
    manifests = [row for row in published if row["kind"] == "asset_board_manifest"]
    assert len(manifests) == 1
    assert manifests[0]["metadata"]["approved_asset_bindings_sha256"] == asset_bindings_sha
    manifest = json.loads(manifests[0]["data"])
    assert manifest["schema_version"] == "asset-board-manifest/v1"
    assert manifest["approved_asset_bindings_sha256"] == asset_bindings_sha
    assert manifest["asset_board_mapping_sha256"] != manifest["provider_asset_board_contracts_sha256"]
    assert manifest["uploaded_tags"] == manifest["binding_tags"] == manifest["prompt_tags"] == [
        "ModelA", "GarmentA", "SceneA", "ProductA", "AppA"
    ]
    assert [entry["asset_tag"] for entry in manifest["entries"]] == [
        "ModelA", "GarmentA", "SceneA", "ProductA", "AppA"
    ]
    for entry in manifest["entries"]:
        assert {
            "source_slot", "source_index", "source_asset_sha256", "asset_type",
            "asset_tag", "replaces_tag", "image_reference", "board_artifact_id",
            "board_sha256", "board_url", "receipt",
        }.issubset(entry)
    assert manifests[0]["artifact_id"]
    assert manifests[0]["sha256"] == hashlib.sha256(manifests[0]["data"]).hexdigest()
    assert result["asset_board_manifest"]["artifact_id"] == manifests[0]["artifact_id"]
    assert result["asset_board_manifest"]["sha256"] == manifests[0]["sha256"]
    assert result["uploaded_tags"] == result["binding_tags"] == result["prompt_tags"]

    context.publish_bytes = lambda **kwargs: {"kind": kwargs["kind"], "sha256": kwargs["expected_sha256"]}
    with pytest.raises(ReplicationError, match="immutable artifact_id") as exc_info:
        stage.run(context=context, input_artifacts=[])
    assert exc_info.value.code == "ASSET_BOARD_GENERATION_FAILED"


def test_v2_asset_binding_order_is_role_and_approved_replacement_order_not_upload_order() -> None:
    from server.approved_edit_contract import canonicalize_approved_edit_script

    change_rows = [
        {"change_id": "P-B", "kind": "replacement", "start_ms": 100, "end_ms": 200, "asset_tag": "ProductB", "instruction": "Replace the approved product layer."},
        {"change_id": "P-A", "kind": "replacement", "start_ms": 300, "end_ms": 400, "asset_tag": "ProductA", "instruction": "Replace the approved product layer."},
    ]
    raw_bindings = [
        {"source_slot": "app_evidence_bundle", "source_index": 0, "source_asset_sha256": "7" * 64, "asset_type": "app", "asset_tag": "AppA", "replaces_tag": "AppA", "source_artifact_id": "app-bundle-1"},
        {"source_slot": "new_product_image", "source_index": 0, "source_asset_sha256": "6" * 64, "asset_type": "product", "asset_tag": "ProductA", "replaces_tag": "ProductA"},
        {"source_slot": "new_model_image", "source_index": 4, "source_asset_sha256": "5" * 64, "asset_type": "scene", "asset_tag": "SceneA", "replaces_tag": "SceneA"},
        {"source_slot": "new_model_image", "source_index": 2, "source_asset_sha256": "4" * 64, "asset_type": "garment", "asset_tag": "GarmentA", "replaces_tag": "PersonA"},
        {"source_slot": "new_product_image", "source_index": 1, "source_asset_sha256": "3" * 64, "asset_type": "product", "asset_tag": "ProductB", "replaces_tag": "ProductB"},
        {"source_slot": "new_model_image", "source_index": 1, "source_asset_sha256": "2" * 64, "asset_type": "model", "asset_tag": "PersonB", "replaces_tag": "PersonB"},
        {"source_slot": "new_model_image", "source_index": 0, "source_asset_sha256": "1" * 64, "asset_type": "model", "asset_tag": "PersonA", "replaces_tag": "PersonA"},
    ]
    expected_order = ["PersonA", "PersonB", "GarmentA", "SceneA", "ProductB", "ProductA", "AppA"]
    expected = []
    by_tag = {row["asset_tag"]: row for row in raw_bindings}
    for index, tag in enumerate(expected_order, start=1):
        expected.append({**by_tag[tag], "image_reference": f"@Image{index}"})
    value = {
        "contract": "approved-edit-script/v1",
        "asset_bindings": raw_bindings,
        "asset_bindings_sha256": hashlib.sha256(json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "change_rows": change_rows,
        "change_rows_sha256": hashlib.sha256(json.dumps(change_rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
    }
    canonical = canonicalize_approved_edit_script(value)
    assert [row["asset_tag"] for row in canonical["asset_bindings"]] == expected_order
    assert canonical["asset_bindings"] == expected


def test_approved_edit_contract_builder_assigns_canonical_references_and_digests() -> None:
    from server.approved_edit_contract import build_approved_edit_script

    bindings = [
        {"source_slot": "app_evidence_bundle", "source_index": 0, "source_asset_sha256": "7" * 64, "asset_type": "app", "asset_tag": "AppA", "replaces_tag": "AppA", "source_artifact_id": "bundle-1"},
        {"source_slot": "new_product_image", "source_index": 0, "source_asset_sha256": "6" * 64, "asset_type": "product", "asset_tag": "ProductA", "replaces_tag": "ProductA"},
        {"source_slot": "new_model_image", "source_index": 1, "source_asset_sha256": "2" * 64, "asset_type": "model", "asset_tag": "PersonB", "replaces_tag": "PersonB"},
        {"source_slot": "new_model_image", "source_index": 0, "source_asset_sha256": "1" * 64, "asset_type": "model", "asset_tag": "PersonA", "replaces_tag": "PersonA"},
    ]
    rows = [
        {"change_id": "P-A", "kind": "replacement", "start_ms": 300, "end_ms": 400, "asset_tag": "ProductA", "instruction": "Replace the approved product layer."},
    ]

    canonical = build_approved_edit_script(bindings, rows)

    assert [row["asset_tag"] for row in canonical["asset_bindings"]] == ["PersonA", "PersonB", "ProductA", "AppA"]
    assert [row["image_reference"] for row in canonical["asset_bindings"]] == ["@Image1", "@Image2", "@Image3", "@Image4"]
    assert canonical["asset_bindings_sha256"] == hashlib.sha256(
        json.dumps(canonical["asset_bindings"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert canonical["change_rows_sha256"] == hashlib.sha256(
        json.dumps(canonical["change_rows"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert "image_reference" not in bindings[0]


def test_approved_product_replacement_preserves_adapt_action_execution_mode() -> None:
    from server.approved_edit_contract import build_approved_edit_script

    canonical = build_approved_edit_script(
        [{
            "source_slot": "new_product_image",
            "source_index": 0,
            "source_asset_sha256": "6" * 64,
            "asset_type": "product",
            "asset_tag": "ProductA",
            "replaces_tag": "SOURCE_CANDY",
        }],
        [{
            "change_id": "PRODUCT-ACTION-01",
            "kind": "replacement",
            "start_ms": 1200,
            "end_ms": 3800,
            "asset_tag": "ProductA",
            "instruction": "Subject 1 picks up @Image1, opens the bottle, drinks it, and shows a natural pleased reaction.",
            "execution_mode": "adapt_action",
        }],
    )

    assert canonical["change_rows"][0]["execution_mode"] == "adapt_action"


def test_approved_person_replacement_rejects_adapt_action_execution_mode() -> None:
    from server.approved_edit_contract import build_approved_edit_script

    with pytest.raises(ReplicationError, match="execution_mode"):
        build_approved_edit_script(
            [_explicit_model_binding()],
            [{
                **_explicit_replacement_row(),
                "execution_mode": "adapt_action",
            }],
        )


def test_approved_edit_contract_preserves_explicit_source_object_binding_fields() -> None:
    from server.approved_edit_contract import build_approved_edit_script

    binding = {
        "source_slot": "new_model_image",
        "source_index": 0,
        "source_asset_sha256": "1" * 64,
        "asset_type": "model",
        "asset_tag": "TargetMan",
        "replaces_tag": "PERSON_A",
        "source_object_descriptor": "PERSON_A: central male; first appears in frame center; wears black hoodie",
        "target_identity_descriptor": "young man with a shaved buzz cut, long oval face, strong brows, narrow dark eyes, and broad lips",
        "replacement_scope": "face_hair_skin",
        "preserve_scope": "source_wardrobe_body_motion_interaction",
        "binding_confidence": 0.97,
        "identity_scope": "face_hair_skin",
        "wardrobe_policy": "identity_from_reference_preserve_source_wardrobe",
        "target_wardrobe_evidence": "absent",
        "source_wardrobe_descriptor": "black hoodie",
        "person_asset_profile": "model-identity-v3-local-crop",
        "asset_mime_type": "image/png",
        "asset_width": 1024,
        "asset_height": 1024,
        "identity_subject_count": 1,
        "asset_layout": "identity_dominant",
        "asset_composition": "close_portrait_square",
    }

    canonical = build_approved_edit_script(
        [binding],
        [{
            "change_id": "R01",
            "kind": "replacement",
            "start_ms": 0,
            "end_ms": 1000,
            "asset_tag": "TargetMan",
            "instruction": "Replace only the approved identity layer.",
        }],
    )

    assert canonical["asset_bindings"][0] == {**binding, "image_reference": "@Image1"}


def _explicit_model_binding() -> dict[str, object]:
    return {
        "source_slot": "new_model_image",
        "source_index": 0,
        "source_asset_sha256": "8" * 64,
        "asset_type": "model",
        "asset_tag": "TargetPerson",
        "replaces_tag": "PERSON_A",
        "source_object_descriptor": "PERSON_A: opening-center speaker wearing a black hoodie and holding a dark phone",
        "target_identity_descriptor": "red mesh sleeveless top, bright green crossbody strap, silver chain",
        "replacement_scope": "identity, hair, skin, and visible wardrobe",
        "preserve_scope": "source body motion, gestures, contact, perspective, lighting, occlusion, and timing",
        "binding_confidence": 0.97,
        "identity_scope": "face_hair_skin",
        "wardrobe_policy": "identity_and_wardrobe_from_reference",
        "target_wardrobe_evidence": "visible",
        "person_asset_profile": "model-identity-v3-local-crop",
        "asset_mime_type": "image/png",
        "asset_width": 1024,
        "asset_height": 1024,
        "identity_subject_count": 1,
        "asset_layout": "identity_dominant",
        "asset_composition": "upper_body_square",
    }


def _explicit_replacement_row() -> dict[str, object]:
    return {
        "change_id": "R-PERSON",
        "kind": "replacement",
        "start_ms": 0,
        "end_ms": 1000,
        "asset_tag": "TargetPerson",
        "instruction": "Replace the approved person identity and visible wardrobe.",
    }


def test_approved_model_binding_preserves_reference_wardrobe_policy() -> None:
    from server.approved_edit_contract import build_approved_edit_script

    binding = _explicit_model_binding()
    canonical = build_approved_edit_script([binding], [_explicit_replacement_row()])

    assert canonical["asset_bindings"][0]["wardrobe_policy"] == "identity_and_wardrobe_from_reference"
    assert canonical["asset_bindings"][0]["target_identity_descriptor"] == binding["target_identity_descriptor"]


def test_approved_model_binding_preserves_head_only_source_wardrobe_policy() -> None:
    from server.approved_edit_contract import build_approved_edit_script

    binding = _explicit_model_binding()
    binding.update({
        "target_identity_descriptor": "ragdoll cat head",
        "replacement_scope": "head identity only",
        "preserve_scope": "source human body, black hoodie, motion, gestures, contact, lighting, and timing",
        "wardrobe_policy": "identity_from_reference_preserve_source_wardrobe",
        "target_wardrobe_evidence": "absent",
        "source_wardrobe_descriptor": "black hoodie",
    })
    canonical = build_approved_edit_script([binding], [_explicit_replacement_row()])

    assert canonical["asset_bindings"][0]["wardrobe_policy"] == "identity_from_reference_preserve_source_wardrobe"
    assert canonical["asset_bindings"][0]["target_wardrobe_evidence"] == "absent"
    assert canonical["asset_bindings"][0]["source_wardrobe_descriptor"] == "black hoodie"


@pytest.mark.parametrize("missing", ["wardrobe_policy", "target_wardrobe_evidence", "binding_confidence", "preserve_scope"])
def test_approved_model_binding_rejects_missing_source_object_evidence(missing: str) -> None:
    from server.approved_edit_contract import build_approved_edit_script

    binding = _explicit_model_binding()
    binding.pop(missing)
    with pytest.raises(ReplicationError, match="approved asset binding source or identity is invalid"):
        build_approved_edit_script([binding], [_explicit_replacement_row()])


def test_approved_model_binding_rejects_complete_appearance_with_source_wardrobe() -> None:
    from server.approved_edit_contract import build_approved_edit_script

    binding = _explicit_model_binding()
    binding.update({
        "wardrobe_policy": "identity_from_reference_preserve_source_wardrobe",
        "target_wardrobe_evidence": "absent",
        "source_wardrobe_descriptor": "black hoodie",
        "replacement_scope": "complete identity, appearance, and wardrobe",
    })
    with pytest.raises(ReplicationError, match="person wardrobe policy conflicts with replacement scope"):
        build_approved_edit_script([binding], [_explicit_replacement_row()])


def test_v2_script_uses_shared_neutral_marketing_contract_not_test_marker_heuristics() -> None:
    from server.marketing_terms import MarketingTermsError, validate_neutral_marketing_terms

    source = inspect.getsource(production_ports)
    assert "validate_neutral_marketing_terms" in source
    assert "unsafe-attraction" not in source
    assert "non-neutral" not in source
    validate_neutral_marketing_terms("appearance-led opening with confident presentation", surface="script")
    for surface in ("script", "asset_board", "storyboard", "prompt"):
        with pytest.raises(MarketingTermsError) as exc_info:
            validate_neutral_marketing_terms("objectifying visual claim", surface=surface)
        assert exc_info.value.code == "CONTENT_SAFETY_BLOCKER"


def test_v2_app_binding_requires_one_immutable_evidence_bundle() -> None:
    from server.approved_edit_contract import canonicalize_approved_edit_script

    binding = {
        "source_slot": "app_evidence_bundle",
        "source_index": 0,
        "source_asset_sha256": "a" * 64,
        "asset_type": "app",
        "asset_tag": "AppA",
        "replaces_tag": "AppA",
        "source_artifact_id": "bundle-1",
    }
    digest = hashlib.sha256(json.dumps([{**binding, "image_reference": "@Image1"}], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    value = {
        "contract": "approved-edit-script/v1",
        "asset_bindings": [binding],
        "asset_bindings_sha256": digest,
        "change_rows": [],
        "change_rows_sha256": hashlib.sha256(b"[]").hexdigest(),
    }
    assert canonicalize_approved_edit_script(value)["asset_bindings"][0]["source_artifact_id"] == "bundle-1"


@pytest.mark.parametrize(
    ("mismatch_field", "bad_value"),
    [
        ("receipt_asset_type", "garment"),
        ("template_version", "scene-v2"),
        ("receipt_source_asset_sha256", "f" * 64),
        ("receipt_board_sha256", "f" * 64),
        ("receipt_task_id", ""),
        ("receipt_request_sha256", "not-a-sha"),
        ("result_asset_type", "garment"),
        ("result_board_sha256", "f" * 64),
        ("result_task_id", "task-other"),
        ("receipt_result_asset_type", "garment"),
        ("receipt_result_board_sha256", "f" * 64),
        ("receipt_result_task_id", "task-other"),
        ("provider_request_sha256", "f" * 64),
        ("provider_response_sha256", "f" * 64),
        ("provider_task_id", "task-other"),
        ("provider_contract_sha256", "f" * 64),
        ("board_url", "http://media.example/not-https.png"),
        ("board_url", "https://localhost/board.png"),
        ("board_url", "https://127.0.0.1/board.png"),
        ("board_url", "https://user:pass@media.example/board.png"),
        ("board_url", "https://192.168.1.1/board.png"),
    ],
)
def test_asset_board_stage_rejects_provider_receipt_lineage_mismatch(tmp_path: Path, mismatch_field: str, bad_value: str) -> None:
    from contextlib import contextmanager

    path = tmp_path / "product.png"
    path.write_bytes(b"product")
    source_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    board_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + (1).to_bytes(4, "big") * 2 + bytes([8, 6, 0, 0, 0])
    binding = {
        "source_slot": "new_product_image",
        "source_index": 0,
        "source_asset_sha256": source_sha,
        "asset_type": "product",
        "asset_tag": "ProductA",
        "replaces_tag": "ProductA",
        "image_reference": "@Image1",
    }
    approval = {
        "contract": "approved-script-lines/v2",
        "script_sha256": "b" * 64,
        "approved_edit_script": {
            "contract": "approved-edit-script/v1",
            "asset_bindings": [binding],
            "asset_bindings_sha256": hashlib.sha256(json.dumps([binding], sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "change_rows": [],
            "change_rows_sha256": hashlib.sha256(b"[]").hexdigest(),
        },
    }
    workflow = SimpleNamespace(run_asset_board_batch=lambda _rows: [{
        "tag": "ProductA",
            "asset_type": bad_value if mismatch_field == "result_asset_type" else "product",
        "board_url": bad_value if mismatch_field == "board_url" else "https://media.example/board.png",
        "board_bytes": board_bytes,
        "board_sha256": bad_value if mismatch_field == "result_board_sha256" else hashlib.sha256(board_bytes).hexdigest(),
            "task_id": bad_value if mismatch_field in {"result_task_id", "receipt_result_task_id"} else "task-1",
            "receipt": {
            "schema_version": "runninghub-asset-board/v2",
                "asset_type": bad_value if mismatch_field in {"receipt_asset_type", "receipt_result_asset_type"} else "product",
            "template_version": bad_value if mismatch_field == "template_version" else "product-v2",
            "source_asset_sha256": bad_value if mismatch_field == "receipt_source_asset_sha256" else source_sha,
            "request_sha256": bad_value if mismatch_field == "receipt_request_sha256" else "1" * 64,
            "response_sha256": "2" * 64,
            "task_id": bad_value if mismatch_field == "receipt_task_id" else "task-1",
                "board_sha256": bad_value if mismatch_field in {"receipt_board_sha256", "receipt_result_board_sha256"} else hashlib.sha256(board_bytes).hexdigest(),
                "provider_asset_board_contract_sha256": bad_value if mismatch_field == "provider_contract_sha256" else _provider_asset_board_contract("product", source_sha, "1" * 64),
                "provider_receipt": {
                    "request_sha256": bad_value if mismatch_field == "provider_request_sha256" else "1" * 64,
                    "response_sha256": bad_value if mismatch_field == "provider_response_sha256" else "2" * 64,
                    "task_id": bad_value if mismatch_field == "provider_task_id" else "task-1",
                },
        },
    }])

    @contextmanager
    def materialize_slot(_slot_id: str, *, index: int = 0):
        assert index == 0
        yield SimpleNamespace(path=path)

    context = SimpleNamespace(
        job_id="job-asset-receipt-mismatch",
        snapshot=SimpleNamespace(current_script_revision=1, approved_script_sha256="b" * 64, slots_manifest={"slots": {"new_product_image": {"present": True, "sha256": [source_sha]}}}),
        job_store=SimpleNamespace(get_script_approval=lambda *_args: approval),
        artifacts=(),
        materialize_slot=materialize_slot,
        publish_bytes=lambda **kwargs: {"artifact_id": "board-1", "kind": kwargs["kind"], "sha256": kwargs["expected_sha256"], "metadata": kwargs.get("metadata", {})},
    )
    with pytest.raises(ReplicationError, match="receipt|asset_type|HTTPS|board SHA|result|contract") as exc_info:
        packaged_stages.AssetBoardStage(workflow_client=workflow).run(context=context, input_artifacts=[])
    assert exc_info.value.code == "ASSET_BOARD_GENERATION_FAILED"


@pytest.mark.parametrize(
    "board_bytes",
    [
        b"not-png",
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIH",
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + (0).to_bytes(4, "big") * 2 + bytes([8, 6, 0, 0, 0]),
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + (100_000).to_bytes(4, "big") * 2 + bytes([8, 6, 0, 0, 0]),
    ],
)
def test_asset_board_stage_rejects_invalid_png_result(tmp_path: Path, board_bytes: bytes) -> None:
    from contextlib import contextmanager

    path = tmp_path / "product.png"
    path.write_bytes(b"product")
    source_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    binding = {"source_slot": "new_product_image", "source_index": 0, "source_asset_sha256": source_sha, "asset_type": "product", "asset_tag": "ProductA", "replaces_tag": "ProductA", "image_reference": "@Image1"}
    approval = {"contract": "approved-script-lines/v2", "script_sha256": "b" * 64, "approved_edit_script": {"contract": "approved-edit-script/v1", "asset_bindings": [binding], "asset_bindings_sha256": hashlib.sha256(json.dumps([binding], sort_keys=True, separators=(",", ":")).encode()).hexdigest(), "change_rows": [], "change_rows_sha256": hashlib.sha256(b"[]").hexdigest()}}

    @contextmanager
    def materialize_slot(_slot_id: str, *, index: int = 0):
        assert index == 0
        yield SimpleNamespace(path=path)

    workflow = SimpleNamespace(run_asset_board_batch=lambda _rows: [{"tag": "ProductA", "asset_type": "product", "board_url": "https://media.example/board.png", "board_bytes": board_bytes, "board_sha256": hashlib.sha256(board_bytes).hexdigest(), "task_id": "task-1", "receipt": {"schema_version": "runninghub-asset-board/v2", "asset_type": "product", "template_version": "product-v2", "source_asset_sha256": source_sha, "request_sha256": "1" * 64, "response_sha256": "2" * 64, "task_id": "task-1", "board_sha256": hashlib.sha256(board_bytes).hexdigest(), "provider_asset_board_contract_sha256": _provider_asset_board_contract("product", source_sha, "1" * 64), "provider_receipt": {"request_sha256": "1" * 64, "response_sha256": "2" * 64, "task_id": "task-1"}}}])
    context = SimpleNamespace(job_id="job-invalid-png", snapshot=SimpleNamespace(current_script_revision=1, approved_script_sha256="b" * 64, slots_manifest={"slots": {"new_product_image": {"present": True, "sha256": [source_sha]}}}), job_store=SimpleNamespace(get_script_approval=lambda *_args: approval), artifacts=(), materialize_slot=materialize_slot, publish_bytes=lambda **kwargs: {"artifact_id": "board-1", "kind": kwargs["kind"], "sha256": kwargs["expected_sha256"], "metadata": kwargs.get("metadata", {})})
    with pytest.raises(ReplicationError, match="PNG") as exc_info:
        packaged_stages.AssetBoardStage(workflow_client=workflow).run(context=context, input_artifacts=[])
    assert exc_info.value.code == "ASSET_BOARD_GENERATION_FAILED"


def test_approved_edit_change_rows_require_replacement_instruction_and_text_target_layer() -> None:
    import fakeredis

    from server.redis_job_store import RedisEphemeralJobStore
    from server.visible_text_contract import visible_text_locks_sha256

    store = RedisEphemeralJobStore(fakeredis.FakeRedis(decode_responses=False), prefix="v2-change-fields")
    job = store.create_job(slots_manifest={"admission": {"can_proceed": True}}, capability_token_hash="a" * 64, ttl_seconds=3600)
    script_sha = "b" * 64
    appended = store.append_revision(job_id=job.job_id, kind="script", expected_version=job.version, manifest={"revision": 1, "sha256": script_sha}, invalidate_downstream=False, ttl_seconds=3600)
    binding = {
        "source_slot": "new_product_image",
        "source_index": 0,
        "source_asset_sha256": "a" * 64,
        "asset_type": "product",
        "asset_tag": "ProductA",
        "replaces_tag": "ProductA",
        "image_reference": "@Image1",
    }
    base = {
        "contract": "approved-script-lines/v2",
        "revision": 1,
        "script_sha256": script_sha,
        "source_content_timeline_sha256": "c" * 64,
        "line_contracts": [],
        "line_contracts_sha256": hashlib.sha256(b"[]").hexdigest(),
        "visible_text_locks": [],
        "visible_text_locks_sha256": visible_text_locks_sha256([]),
    }
    def approve_rows(rows):
        return {
            **base,
            "approved_edit_script": {
                "contract": "approved-edit-script/v1",
                "asset_bindings": [binding],
                "asset_bindings_sha256": hashlib.sha256(json.dumps([binding], sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                "change_rows": rows,
                "change_rows_sha256": hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            },
        }
    with pytest.raises(ReplicationError, match="instruction"):
        store.approve_revision(job_id=job.job_id, kind="script", revision=1, expected_version=appended.version, expected_sha256=script_sha, script_approval=approve_rows([{"change_id": "CH01", "kind": "replacement", "start_ms": 0, "end_ms": 1000, "asset_tag": "ProductA"}]), ttl_seconds=3600)
    with pytest.raises(ReplicationError, match="text_target|layer"):
        store.approve_revision(job_id=job.job_id, kind="script", revision=1, expected_version=appended.version, expected_sha256=script_sha, script_approval=approve_rows([{"change_id": "CH02", "kind": "text", "start_ms": 0, "end_ms": 1000, "text": "Approved title"}]), ttl_seconds=3600)

    valid_rows = [
        {"change_id": "CH03", "kind": "replacement", "start_ms": 0, "end_ms": 1000, "asset_tag": "ProductA", "instruction": "Replace the approved product layer."},
        {"change_id": "CH04", "kind": "dialogue", "start_ms": 1000, "end_ms": 2000, "speaker": "PersonA", "text": "Approved line"},
        {"change_id": "CH05", "kind": "text", "start_ms": 2000, "end_ms": 3000, "text_target": "title-main", "layer": "overlay", "text": "Approved title"},
        {"change_id": "CH06", "kind": "language", "start_ms": 3000, "end_ms": 4000, "language": "ja", "text": "承認済みの台詞"},
    ]
    approved = store.approve_revision(
        job_id=job.job_id,
        kind="script",
        revision=1,
        expected_version=appended.version,
        expected_sha256=script_sha,
        script_approval=approve_rows(valid_rows),
        ttl_seconds=3600,
    )
    assert approved.approved_script_sha256 == script_sha
    round_trip = store.get_script_approval(job.job_id, 1)
    assert [row["change_id"] for row in round_trip["approved_edit_script"]["change_rows"]] == ["CH03", "CH04", "CH05", "CH06"]

    with pytest.raises(ReplicationError, match="text_target|layer"):
        store.approve_revision(
            job_id=job.job_id,
            kind="script",
            revision=1,
            expected_version=approved.version,
            expected_sha256=script_sha,
            script_approval=approve_rows([{
                "change_id": "CH07", "kind": "text", "start_ms": 0, "end_ms": 1000,
                "text_target": "not-an-approved-target", "layer": "overlay", "text": "x",
            }]),
            ttl_seconds=3600,
        )


def test_asset_board_stage_blocks_slot_sha_mismatch_before_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    from server.errors import ReplicationError

    approval = {
        "contract": "approved-script-lines/v2",
        "script_sha256": "b" * 64,
        "approved_edit_script": {
            "contract": "approved-edit-script/v1",
            "asset_bindings": [{
                "source_slot": "new_product_image",
                "source_index": 0,
                "source_asset_sha256": "a" * 64,
                "asset_type": "product",
                "asset_tag": "ProductA",
                "replaces_tag": "ProductA",
                "image_reference": "@Image1",
            }],
            "asset_bindings_sha256": hashlib.sha256(json.dumps([{
                "source_slot": "new_product_image",
                "source_index": 0,
                "source_asset_sha256": "a" * 64,
                "asset_type": "product",
                "asset_tag": "ProductA",
                "replaces_tag": "ProductA",
                "image_reference": "@Image1",
            }], sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "change_rows": [],
            "change_rows_sha256": hashlib.sha256(b"[]").hexdigest(),
        },
    }
    workflow = SimpleNamespace(run_asset_board_batch=lambda _rows: pytest.fail("provider must not be called"))
    context = SimpleNamespace(
        job_id="job-asset-mismatch",
        snapshot=SimpleNamespace(current_script_revision=1, approved_script_sha256="b" * 64, slots_manifest={"slots": {"new_product_image": {"present": True, "sha256": ["c" * 64]}}}),
        job_store=SimpleNamespace(get_script_approval=lambda *_args: approval),
    )
    with pytest.raises(ReplicationError, match="source asset SHA") as exc_info:
        packaged_stages.AssetBoardStage(workflow_client=workflow).run(context=context, input_artifacts=[])
    assert exc_info.value.code == "ASSET_BINDING_SOURCE_MISMATCH"


def test_v2_approved_edit_script_rejects_legacy_outer_contract_and_invalid_rows() -> None:
    import fakeredis

    from server.redis_job_store import RedisEphemeralJobStore
    from server.visible_text_contract import visible_text_locks_sha256

    store = RedisEphemeralJobStore(fakeredis.FakeRedis(decode_responses=False), prefix="v2-approved-shape")
    job = store.create_job(slots_manifest={"admission": {"can_proceed": True}}, capability_token_hash="a" * 64, ttl_seconds=3600)
    script_sha = "b" * 64
    appended = store.append_revision(
        job_id=job.job_id,
        kind="script",
        expected_version=job.version,
        manifest={"revision": 1, "sha256": script_sha},
        invalidate_downstream=False,
        ttl_seconds=3600,
    )
    empty_sha = hashlib.sha256(b"[]").hexdigest()
    base = {
        "revision": 1,
        "script_sha256": script_sha,
        "source_content_timeline_sha256": "c" * 64,
        "line_contracts": [],
        "line_contracts_sha256": empty_sha,
        "visible_text_locks": [],
        "visible_text_locks_sha256": visible_text_locks_sha256([]),
    }
    row = {
        "change_id": "CH01",
        "kind": "dialogue",
        "start_ms": 1000,
        "end_ms": 2000,
        "speaker": "PersonA",
        "text": "Approved line",
    }
    row_sha = hashlib.sha256(json.dumps([row], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with pytest.raises(ReplicationError, match="approved_edit_script requires") as exc_info:
        store.approve_revision(
            job_id=job.job_id,
            kind="script",
            revision=1,
            expected_version=appended.version,
            expected_sha256=script_sha,
            script_approval={
                **base,
                "contract": "approved-script-lines/v1",
                "approved_edit_script": {"contract": "approved-edit-script/v1", "change_rows": [row], "change_rows_sha256": row_sha},
            },
            ttl_seconds=3600,
        )
    assert exc_info.value.code == "INVALID_INPUT"


def test_v2_replacement_rows_require_immutable_asset_mapping_and_unique_image_identity() -> None:
    import fakeredis

    from server.redis_job_store import RedisEphemeralJobStore
    from server.visible_text_contract import visible_text_locks_sha256

    store = RedisEphemeralJobStore(fakeredis.FakeRedis(decode_responses=False), prefix="v2-asset-map")
    job = store.create_job(slots_manifest={"admission": {"can_proceed": True}}, capability_token_hash="a" * 64, ttl_seconds=3600)
    script_sha = "b" * 64
    appended = store.append_revision(
        job_id=job.job_id,
        kind="script",
        expected_version=job.version,
        manifest={"revision": 1, "sha256": script_sha},
        invalidate_downstream=False,
        ttl_seconds=3600,
    )
    empty_sha = hashlib.sha256(b"[]").hexdigest()
    base = {
        "revision": 1,
        "script_sha256": script_sha,
        "source_content_timeline_sha256": "c" * 64,
        "line_contracts": [],
        "line_contracts_sha256": empty_sha,
        "visible_text_locks": [],
        "visible_text_locks_sha256": visible_text_locks_sha256([]),
        "contract": "approved-script-lines/v2",
    }

    missing_mapping = {
        "change_id": "CH01",
        "kind": "replacement",
        "start_ms": 1000,
        "end_ms": 2000,
        "asset_tag": "UnknownAsset",
        "instruction": "Replace with an approved asset.",
    }
    def approval_for(
        rows: list[dict[str, object]],
        bindings: list[dict[str, object]],
    ) -> dict[str, object]:
        slot_order = {"new_model_image": 0, "new_product_image": 1, "ui_screenshot": 2, "app_store_evidence": 3}
        canonical_bindings = [
            {**binding, "image_reference": f"@Image{index}"}
            for index, binding in enumerate(
                sorted(bindings, key=lambda item: (slot_order[item["source_slot"]], item["source_index"], item["asset_tag"])),
                start=1,
            )
        ]
        return {
            **base,
            "approved_edit_script": {
                "contract": "approved-edit-script/v1",
                "asset_bindings": bindings,
                "asset_bindings_sha256": hashlib.sha256(
                    json.dumps(canonical_bindings, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
                "change_rows": rows,
                "change_rows_sha256": hashlib.sha256(
                    json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
            },
        }

    with pytest.raises(ReplicationError, match="asset_bindings|asset_tag") as exc_info:
        store.approve_revision(
            job_id=job.job_id,
            kind="script",
            revision=1,
            expected_version=appended.version,
            expected_sha256=script_sha,
            script_approval=approval_for([missing_mapping], []),
            ttl_seconds=3600,
        )
    assert exc_info.value.code == "INVALID_INPUT"

    first = {
        "source_slot": "new_model_image",
        "source_index": 0,
        "source_asset_sha256": "a" * 64,
        "asset_type": "model",
        "asset_tag": "ModelA",
        "replaces_tag": "PersonA",
    }
    duplicate = {**first, "asset_tag": "GarmentA", "asset_type": "garment"}
    with pytest.raises(ReplicationError, match="source asset") as exc_info:
        store.approve_revision(
            job_id=job.job_id,
            kind="script",
            revision=1,
            expected_version=appended.version,
            expected_sha256=script_sha,
            script_approval=approval_for([], [first, duplicate]),
            ttl_seconds=3600,
        )
    assert exc_info.value.code == "INVALID_INPUT"
    with pytest.raises(ReplicationError, match="approved_edit_script is required") as exc_info:
        store.approve_revision(
            job_id=job.job_id,
            kind="script",
            revision=1,
            expected_version=appended.version,
            expected_sha256=script_sha,
            script_approval={**base, "contract": "approved-script-lines/v2"},
            ttl_seconds=3600,
        )
    assert exc_info.value.code == "INVALID_INPUT"
    invalid_row = {
        "change_id": "CH09",
        "kind": "dialogue",
        "start_ms": 1000,
        "end_ms": 2000,
        "speaker": "PersonA",
        "text": "Approved line",
        "window": "00:01.000-00:02.000",
    }
    with pytest.raises(ReplicationError, match="invalid shape") as exc_info:
        store.approve_revision(
            job_id=job.job_id,
            kind="script",
            revision=1,
            expected_version=appended.version,
            expected_sha256=script_sha,
            script_approval={
                **base,
                "contract": "approved-script-lines/v2",
                "approved_edit_script": {
                    "contract": "approved-edit-script/v1",
                    "asset_bindings": [],
                    "asset_bindings_sha256": hashlib.sha256(b"[]").hexdigest(),
                    "change_rows": [invalid_row],
                    "change_rows_sha256": hashlib.sha256(json.dumps([invalid_row], sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                },
            },
            ttl_seconds=3600,
        )
    assert exc_info.value.code == "INVALID_INPUT"


def test_v2_audit_derives_only_server_approved_change_rows_and_returns_receipts(monkeypatch: pytest.MonkeyPatch) -> None:
    script_sha = "b" * 64
    approved_rows = [
        {
            "change_id": "CH02",
            "kind": "replacement",
            "start_ms": 2000,
            "end_ms": 3000,
            "asset_tag": "ProductA",
            "instruction": "Replace the approved product asset.",
        },
        {
            "change_id": "CH01",
            "kind": "dialogue",
            "start_ms": 1000,
            "end_ms": 2000,
            "speaker": "PersonA",
            "text": "Approved dialogue",
        },
    ]
    canonical_rows = sorted(approved_rows, key=lambda row: (row["start_ms"], row["end_ms"], row["change_id"]))
    approval = {
        "contract": "approved-script-lines/v2",
        "script_sha256": script_sha,
        "approved_edit_script": {
            "contract": "approved-edit-script/v1",
            "asset_bindings": [{
                "source_slot": "new_product_image",
                "source_index": 0,
                "source_asset_sha256": "a" * 64,
                "asset_type": "product",
                "asset_tag": "ProductA",
                "replaces_tag": "ProductA",
            }],
            "asset_bindings_sha256": hashlib.sha256(json.dumps([{
                "source_slot": "new_product_image",
                "source_index": 0,
                "source_asset_sha256": "a" * 64,
                "asset_type": "product",
                "asset_tag": "ProductA",
                "replaces_tag": "ProductA",
                "image_reference": "@Image1",
            }], sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "change_rows": [approved_rows[1], approved_rows[0]],
            "change_rows_sha256": hashlib.sha256(
                json.dumps(
                    sorted(approved_rows, key=lambda row: (row["start_ms"], row["end_ms"], row["change_id"])),
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
        },
        "line_contracts": [{"line_id": "L01", "text": {"exact": "Source line"}}],
        "visible_text_locks": [{"text_id": "LOCK01", "approved_text": "Keep source text"}],
    }
    context = SimpleNamespace(
        job_id="job-v2-derived",
        snapshot=SimpleNamespace(current_script_revision=1, approved_script_sha256=script_sha),
        job_store=SimpleNamespace(get_script_approval=lambda *_args: approval),
    )
    monkeypatch.setattr(
        packaged_stages,
        "_read_json_artifact",
        lambda *_args, **_kwargs: {"script_sha256": script_sha, "artifact": "approved-script"},
    )
    derived, changes_sha, returned_script_sha = packaged_stages.SeedanceAuditStage._v2_approved_target_changes(
        context,
        target_changes=[],
    )
    assert derived == canonical_rows
    assert changes_sha == hashlib.sha256(
        json.dumps(canonical_rows, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert returned_script_sha == script_sha
    assert all(row.get("text_id") != "LOCK01" for row in derived)


def test_v2_audit_fails_closed_when_approved_script_artifact_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from server.errors import ReplicationError

    script_sha = "c" * 64
    approval = {
        "contract": "approved-script-lines/v2",
        "script_sha256": script_sha,
        "approved_edit_script": {
            "contract": "approved-edit-script/v1",
            "asset_bindings": [],
            "asset_bindings_sha256": hashlib.sha256(b"[]").hexdigest(),
            "change_rows": [],
            "change_rows_sha256": hashlib.sha256(b"[]").hexdigest(),
        },
    }
    context = SimpleNamespace(
        job_id="job-v2-missing-script",
        snapshot=SimpleNamespace(current_script_revision=1, approved_script_sha256=script_sha),
        job_store=SimpleNamespace(get_script_approval=lambda *_args: approval),
    )
    monkeypatch.setattr(
        packaged_stages,
        "_read_json_artifact",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ReplicationError("ARTIFACT_NOT_FOUND", "approved script artifact is missing")
        ),
    )
    with pytest.raises(ReplicationError, match="approved script artifact is missing") as exc_info:
        packaged_stages.SeedanceAuditStage._v2_approved_target_changes(context, target_changes=[])
    assert exc_info.value.code == "ARTIFACT_NOT_FOUND"


def test_v2_asset_binding_order_covers_target_assets_and_blocks_more_than_nine_images() -> None:
    types = ["model", "garment", "scene", "product", "product", "app"]
    boards = [
        {
            "tag": f"Asset{index}",
            "asset_type": asset_type,
            "board_url": f"https://media.example/board-{index}.png",
            "board_sha256": f"{index:x}" * 64,
            "receipt": {
                "schema_version": "runninghub-asset-board/v2",
                "asset_type": asset_type,
                "template_version": _asset_board_template_version(asset_type),
                "source_asset_sha256": "a" * 64,
                "request_sha256": "b" * 64,
                "response_sha256": "c" * 64,
                "task_id": f"task-{index}",
                "board_sha256": f"{index:x}" * 64,
            },
        }
        for index, asset_type in enumerate(types, start=1)
    ]
    refs = build_asset_reference_bindings(boards)
    assert [item["reference"] for item in refs] == [f"@Image{index}" for index in range(1, 7)]
    assert [item["asset_type"] for item in refs] == types
    too_many = refs + [
        {**refs[index - 7], "reference": f"@Image{index}", "tag": f"Asset{index}"}
        for index in range(7, 11)
    ]
    assert [item["reference"] for item in too_many] == [f"@Image{index}" for index in range(1, 11)]
    with pytest.raises(EditPromptContractError, match="IMAGE_REFERENCE_LIMIT"):
        build_edit_provider_payload(
            video_url="https://media.example/source.mp4",
            prompt="编辑视频：@Video1 是编辑对象。",
            asset_bindings=too_many,
            source_video_sha256="a" * 64,
            source_slice_sha256="b" * 64,
            segment_plan_sha256="c" * 64,
            segment_id="S01",
            start_ms=0,
            end_ms=10_000,
            source_video_reference_artifact_id="source-S01",
        )


def test_complexity_split_keeps_person_replacement_and_its_dialogue_together() -> None:
    artifact = compile_edit_prompt(
        source_video="@Video1",
        asset_bindings=[
            {"tag": "PersonA", "reference": "@Image1", "asset_type": "model"},
            {"tag": "ProductA", "reference": "@Image2", "asset_type": "product"},
        ],
        replacements=[
            {"window": "00:01.000-00:02.000", "target": "PersonA", "asset_type": "model", "instruction": "replace person"},
            {"window": "00:02.000-00:03.000", "target": "ProductA", "asset_type": "product", "instruction": "replace product"},
        ],
        dialogue_changes=[{"window": "00:01.000-00:02.000", "speaker": "PersonA", "text": "Approved line"}],
        complexity_config={"threshold": 1.5, "over_threshold_strategy": "split"},
    )
    groups = artifact["complexity"]["split_plan"]
    assert any({"model_replacement", "dialogue_change"}.issubset(set(group["factor_ids"])) for group in groups)


def test_stage_fingerprint_validation_uses_executed_artifact_sha_not_plan_placeholder(tmp_path: Path) -> None:
    plan = build_stage_plan(_v2_manifest(tmp_path))
    assert all(stage.get("expected_input_fingerprint") for stage in plan)
    assert all(stage.get("output_fingerprint") is None for stage in plan)
    validate = orchestrator.validate_stage_artifact_fingerprints
    executed = {
        stage["name"]: {
            "input_fingerprint": stage["expected_input_fingerprint"],
            "output_fingerprint": hashlib.sha256(stage["name"].encode()).hexdigest(),
            "contract_version": stage["contract_version"],
            "status": "SUCCEEDED",
        }
        for stage in plan
    }
    validate(plan, executed)
    executed["bind_inputs"]["output_fingerprint"] = "0" * 64
    with pytest.raises(ValueError, match="stale|fingerprint"):
        validate(plan, executed)


def test_v2_execution_record_uses_real_dependency_outputs_and_status(tmp_path: Path) -> None:
    build_record = getattr(orchestrator, "build_stage_execution_record", None)
    assert callable(build_record)
    plan = build_stage_plan(_v2_manifest(tmp_path))
    executed: dict[str, dict[str, object]] = {}
    for stage in plan:
        output_sha = hashlib.sha256(f"executed-artifact:{stage['name']}".encode()).hexdigest()
        executed[stage["name"]] = build_record(
            plan,
            stage["name"],
            executed=executed,
            output_fingerprint=output_sha,
        )
    assert all(record["status"] == "SUCCEEDED" for record in executed.values())
    assert all(record["contract_version"] == "video-edit-v2" for record in executed.values())
    assert all(len(str(record["input_fingerprint"])) == 64 for record in executed.values())
    assert executed["compile_edit_prompt"]["input_fingerprint"] != next(
        stage["expected_input_fingerprint"] for stage in plan if stage["name"] == "compile_edit_prompt"
    )
    orchestrator.validate_stage_artifact_fingerprints(plan, executed)
    executed["generate_asset_boards"]["output_fingerprint"] = "0" * 64
    with pytest.raises(ValueError, match="stale|fingerprint"):
        orchestrator.validate_stage_artifact_fingerprints(plan, executed)


def test_neutral_marketing_language_contract_is_checked_at_script_asset_board_storyboard_and_prompt() -> None:
    validate_terms = getattr(seedance_prompt_compiler, "validate_neutral_marketing_terms", None)
    assert callable(validate_terms)
    neutral = "clear neutral product demonstration with practical feature proof"
    validate_terms(neutral, surface="script")
    validate_terms(neutral, surface="asset_board")
    validate_terms(neutral, surface="storyboard")
    artifact = compile_edit_prompt(
        source_video="@Video1",
        asset_bindings=[{"tag": "ProductA", "reference": "@Image1", "asset_type": "product"}],
        replacements=[{"window": "00:01.000-00:02.000", "target": "ProductA", "asset_type": "product", "instruction": neutral}],
        dialogue_changes=[],
    )
    assert artifact["marketing_language_policy"] == "neutral_marketing_terms_v1"


def test_watermark_region_requires_normalized_finite_coordinates() -> None:
    with pytest.raises(EditPromptContractError, match="WATERMARK_REGION_INVALID"):
        compile_edit_prompt(
            source_video="@Video1",
            asset_bindings=[],
            replacements=[],
            dialogue_changes=[],
            watermark_windows=[{"window": "00:01.000-00:02.000", "region": {"x": 1.2, "y": 0.1, "w": 0.2, "h": 0.2}}],
        )


def test_runninghub_image2_template_is_part_of_paid_request_and_receipt(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "product.png"
    source.write_bytes(b"product-source")
    requests: list[dict] = []
    client = RunningHubWorkflowClient(
        api_key="test-key",
        base_url="https://runninghub.example.test",
        upload_file=lambda path: f"https://media.example/{path.name}",
    )

    def fake_post(*, url: str, payload: dict) -> dict:
        requests.append(dict(payload))
        if url.endswith("/image-to-image"):
            return {"taskId": "task-image2"}
        return {"status": "SUCCESS", "results": [{"outputType": "png", "url": "https://result.example/board.png"}]}

    client._post = fake_post  # type: ignore[method-assign]
    monkeypatch.setattr(runninghub_workflows, "_download_binary", lambda **_kwargs: b"\x89PNG\r\n\x1a\nboard")
    result = client.run_image2(
        prompt="neutral product board",
        reference_images=[source],
        template="product",
    )
    assert set(requests[0]) == {"prompt", "imageUrls", "aspectRatio", "resolution", "quality"}
    assert "template" not in requests[0]
    assert result["receipt"]["template"] == "product"
    assert result["receipt"]["request_sha256"]
