from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import io
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server.runninghub_standard_contract as standard_contract


def _source_video_prompt(text: str) -> str:
    return (
        f"{standard_contract.SOURCE_VIDEO_PRIORITY_PREFIX} "
        f"{standard_contract.SOURCE_VIDEO_PROMPT_CONTRACT} {text}"
    )


def _digest(value: bytes) -> str:
    return sha256(value).hexdigest()


def _png_bytes(*, width: int = 720, height: int = 1280, color: tuple[int, int, int] = (96, 96, 96)) -> bytes:
    from PIL import Image

    output = io.BytesIO()
    Image.new("RGB", (width, height), color).save(output, format="PNG")
    return output.getvalue()


def test_control_sheet_sharpness_ratio_rejects_a_blurred_copy() -> None:
    """A control sheet must retain enough source detail to rule out censor-style blur."""

    from PIL import Image, ImageFilter
    from server.packaged_stages import _sharpness_ratio

    source = Image.effect_noise((512, 512), 96).convert("RGB")
    blurred = source.filter(ImageFilter.GaussianBlur(radius=12))

    assert _sharpness_ratio(source, source.copy()) > 0.95
    assert _sharpness_ratio(source, blurred) < 0.60


def test_control_sheet_sharpness_ratio_rejects_localized_detail_loss() -> None:
    """Panel borders must not hide a censored interior region from the quality gate."""

    from PIL import Image, ImageFilter
    from server.packaged_stages import _sharpness_ratio

    source = Image.effect_noise((512, 512), 96).convert("RGB")
    partially_blurred = source.copy()
    blurred_center = source.crop((128, 128, 384, 384)).filter(ImageFilter.GaussianBlur(radius=12))
    partially_blurred.paste(blurred_center, (128, 128))

    assert _sharpness_ratio(source, partially_blurred) < 0.60


def test_control_sheet_sharpness_ratio_rejects_a_single_blurred_detail_tile() -> None:
    """One censored high-detail face, label or text tile is already unacceptable."""

    from PIL import Image, ImageFilter
    from server.packaged_stages import _sharpness_ratio

    source = Image.effect_noise((512, 512), 96).convert("RGB")
    partially_blurred = source.copy()
    blurred_tile = source.crop((128, 128, 256, 256)).filter(ImageFilter.GaussianBlur(radius=12))
    partially_blurred.paste(blurred_tile, (128, 128))

    assert _sharpness_ratio(source, partially_blurred) < 0.60


def _canonical_digest(value: object) -> str:
    import json

    return _digest(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


_EMPTY_VISIBLE_TEXT_LOCKS_SHA = _digest(b"[]")


@dataclass
class _Materialized:
    path: Path
    sha256: str


def test_source_reference_materializer_never_uploads_a_complete_short_source(monkeypatch, tmp_path: Path) -> None:
    """A 2-15s full-window source still becomes a distinct bounded artifact."""

    import server.packaged_stages as stages

    module = stages._load_module(
        "bundled-skills/seedance-storyboard-replication/scripts/source_video_reference.py",
        "test_source_video_reference_materializer",
    )
    source = tmp_path / "source.mp4"
    source.write_bytes(b"complete-source-video")
    calls: list[list[str]] = []
    monkeypatch.setattr(module.shutil, "which", lambda _name: "ffmpeg")

    def render(command: list[str]) -> None:
        calls.append(command)
        Path(command[-1]).write_bytes(b"bounded-source-slice")

    reference = module.materialize_source_video_reference(
        source_video=source,
        segment_plan={
            "segments": [{"segment_id": "S01", "start_ms": 0, "end_ms": 4000, "duration_ms": 4000}]
        },
        segment_id="S01",
        output_dir=tmp_path / "references",
        probe_duration_ms=lambda _path: 4000,
        run_ffmpeg=render,
    )

    assert calls
    assert reference.path != source
    assert reference.reused_source is False
    assert reference.source_slice_sha256 != reference.source_video_sha256


def test_seedance_audit_rejects_a_segment_plan_without_its_canonical_digest() -> None:
    from server.errors import ReplicationError
    from server.packaged_stages import SeedanceAuditStage

    with pytest.raises(ReplicationError, match="segment plan digest"):
        SeedanceAuditStage._frozen_segment_plan(
            {"segment_plan": {"segments": [{
                "segment_id": "S01", "start_ms": 0, "end_ms": 4000,
                "duration_ms": 4000, "cut_ids": ["C01"],
            }]}}
        )


def test_seedance_audit_requires_real_control_artifacts_in_a_durable_context(tmp_path: Path) -> None:
    """Board metadata alone cannot authorize a paid source-fidelity request."""

    from server.errors import ReplicationError
    from server.packaged_stages import SeedanceAuditStage

    board, model, source = (tmp_path / name for name in ("board.png", "model.png", "source.mp4"))
    png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR\x00\x00\x02\xd0\x00\x00\x05\x00\x08\x02\x00\x00\x00"
    board.write_bytes(png)
    model.write_bytes(png + b"model")
    source.write_bytes(b"source-video")
    context = _VideoAuditContext(board=board, source=source, model=model)
    context.job_store = SimpleNamespace(get_current_revision=lambda *_args: object())
    approved_board = {
        "source_video_sha256": _digest(source.read_bytes()),
        "source_keyframe_sheet_sha256": "b" * 64,
        "replacement_control_keyframe_sheet_sha256": "c" * 64,
        "replacement_control_keyframe_receipt_sha256": "d" * 64,
        "replacement_target_sha256s": [_digest(model.read_bytes())],
    }

    with pytest.raises(ReplicationError, match="source_keyframe_sheet artifact"):
        SeedanceAuditStage._validate_internal_board_lineage(
            context, approved_board=approved_board
        )


@pytest.mark.parametrize(
    ("classification_kind", "must_fail"),
    [("song", False), ("background_music", False), ("voiceover", False), ("non_song", True)],
    ids=["song", "background_music", "voiceover", "ambiguous_non_song"],
)
def test_bind_inputs_publishes_the_sha_bound_uploaded_audio_classification(
    tmp_path: Path, classification_kind: str, must_fail: bool
) -> None:
    """The immutable upload classification must exist before script drafting."""

    from server.errors import ReplicationError
    from server.packaged_stages import BindInputsStage

    upload = tmp_path / "replacement.wav"
    upload.write_bytes(b"RIFFreplacement-audio")
    upload_sha = _digest(upload.read_bytes())
    absent = {"present": False, "values": [], "metadata": [], "sha256": []}
    slots = {
        "source_video": {
            "present": True,
            "values": ["uploads/job/source.mp4"],
            "metadata": [{"object_key": "uploads/job/source.mp4", "sha256": "a" * 64}],
            "sha256": ["a" * 64],
        },
        "new_product_image": dict(absent),
        "new_model_image": dict(absent),
        "ui_screenshot": dict(absent),
        "app_store_url": dict(absent),
        "ui_operation_video": dict(absent),
        "tail_video": dict(absent),
    }

    class Classifier:
        def __init__(self) -> None:
            self.calls: list[tuple[Path, str]] = []

        def classify_uploaded_audio(self, path: Path, *, audio_sha256: str):
            self.calls.append((Path(path), audio_sha256))
            return {
                "contract": "uploaded-audio-classification/v1",
                "audio_sha256": audio_sha256,
                "kind": classification_kind,
                "confidence": 0.99,
                "classification_evidence_sha256": "b" * 64,
                "lyrics": [],
            }

    class Context:
        def __init__(self) -> None:
            self.snapshot = SimpleNamespace(
                slots_manifest={
                    "slots": slots,
                    "admission": {"can_proceed": True},
                    "extensions": {
                        "edit_contract": "video-edit-v2",
                        "background_music": {
                            "extension_id": "input_contract_v2.background_music",
                            "values": ["uploads/job/replacement.wav"],
                            "sha256": [upload_sha],
                            "metadata": [{"object_key": "uploads/job/replacement.wav", "sha256": upload_sha}],
                        }
                    },
                }
            )
            self.published: list[dict[str, object]] = []

        @contextmanager
        def materialize_extension(self, extension_id: str, *, index: int = 0):
            assert (extension_id, index) == ("background_music", 0)
            yield _Materialized(upload, upload_sha)

        def publish_bytes(self, *, kind: str, data: bytes, content_type: str, expected_sha256: str, metadata=None):
            assert _digest(data) == expected_sha256
            artifact = {
                "kind": kind,
                "sha256": expected_sha256,
                "content_type": content_type,
                "data": data,
                "metadata": dict(metadata or {}),
            }
            self.published.append(artifact)
            return artifact

    classifier = Classifier()
    context = Context()
    if must_fail:
        with pytest.raises(ReplicationError) as exc_info:
            BindInputsStage(uploaded_audio_classifier=classifier).run(context=context, input_artifacts=[])
        assert exc_info.value.code == "UPLOADED_AUDIO_CLASSIFICATION_REQUIRED"
        assert context.published == []
        return

    result = BindInputsStage(uploaded_audio_classifier=classifier).run(context=context, input_artifacts=[])

    assert classifier.calls == [(upload, upload_sha)]
    assert result["uploaded_audio_classification"]["kind"] == classification_kind
    assert result["published_artifacts"][0]["kind"] == "uploaded_audio_classification"
    assert b'"audio_sha256":"' + upload_sha.encode("ascii") in context.published[0]["data"]
    assert b'"kind":"' + classification_kind.encode("ascii") + b'"' in context.published[0]["data"]


class _StoryboardContext:
    def __init__(self, *, reference: Path) -> None:
        self.reference = reference
        self.work_dir = reference.parent
        empty = {"present": False, "values": [], "metadata": [], "sha256": []}
        slots = {
            "source_video": {"present": True, "values": ["source.mp4"], "metadata": [{}], "sha256": ["a" * 64]},
            "new_product_image": dict(empty),
            "new_model_image": {"present": True, "values": ["model.png"], "metadata": [{}], "sha256": [_digest(reference.read_bytes())]},
            "ui_screenshot": dict(empty),
            "app_store_url": dict(empty),
            "ui_operation_video": dict(empty),
            "tail_video": dict(empty),
        }
        self.snapshot = SimpleNamespace(
            approved_script_sha256="b" * 64,
            slots_manifest={"slots": slots},
        )
        self.stage_outputs = {
            "analyze_dynamics": {
                "source_dynamics_analysis": {
                    "source_cuts": [{"cut_id": "C01", "start_us": 0, "end_us": 4_000_000}],
                }
            },
            "route_regions": {
                "timeline_regions": {
                    "regions": [
                        {
                            "region_id": "R01",
                            "cut_ids": ["C01"],
                            "media_origin": "generated",
                            "source_start_ms": 0,
                            "source_end_ms": 4000,
                        }
                    ]
                }
            }
        }
        self.published: list[dict[str, object]] = []

    @contextmanager
    def materialize_slot(self, slot_id: str, *, index: int = 0):
        assert slot_id == "new_model_image"
        assert index == 0
        yield _Materialized(self.reference, _digest(self.reference.read_bytes()))

    def publish_bytes(self, *, kind: str, data: bytes, content_type: str, expected_sha256: str, metadata=None):
        assert _digest(data) == expected_sha256
        item = {
            "artifact_id": f"artifact-{kind}-{expected_sha256}",
            "kind": kind,
            "object_key": f"temporary/job/{kind}-{expected_sha256}",
            "sha256": expected_sha256,
            "size_bytes": len(data),
            "content_type": content_type,
            "metadata": dict(metadata or {}),
        }
        self.published.append(item)
        return item


class _Image2:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run_image2(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "task_id": "image2-task",
            "image_bytes": _png_bytes(color=(96 + len(self.calls) * 8, 96, 96)),
            "receipt": {"request_sha256": "c" * 64, "response_sha256": "d" * 64, "task_id": "image2-task"},
        }


class _AuditContext:
    def __init__(self, *, board: Path) -> None:
        self.board = board
        self.snapshot = SimpleNamespace(slots_manifest={"slots": {}})
        self.artifacts = (
            {
                "artifact_id": "board-artifact",
                "object_key": "temporary/job/board-artifact.png",
                "kind": "storyboard_image",
                "sha256": _digest(board.read_bytes()),
                "metadata": {"segment_id": "S01", "storyboard_revision": 1},
            },
        )
        self.published: list[dict[str, object]] = []

    @contextmanager
    def materialize_artifact(self, kind: str, *, artifact_id: str | None = None, sha256: str | None = None, **_kwargs):
        assert kind == "storyboard_image"
        assert artifact_id == "board-artifact"
        assert sha256 == _digest(self.board.read_bytes())
        yield _Materialized(self.board, sha256)

    def publish_bytes(self, *, kind: str, data: bytes, content_type: str, expected_sha256: str, metadata=None):
        item = {
            "artifact_id": f"artifact-{kind}-{expected_sha256}",
            "kind": kind,
            "object_key": f"temporary/job/{kind}-{expected_sha256}",
            "sha256": expected_sha256,
            "size_bytes": len(data),
            "content_type": content_type,
            "metadata": dict(metadata or {}),
        }
        self.published.append(item)
        return item


class _Uploader:
    def __init__(self) -> None:
        self.paths: list[Path] = []

    def upload_media(self, path: Path) -> str:
        self.paths.append(Path(path))
        return f"https://media.example.test/{Path(path).name}"


class _VideoAuditContext(_AuditContext):
    def __init__(self, *, board: Path, source: Path, model: Path) -> None:
        super().__init__(board=board)
        self.source = source
        self.model = model
        self.work_dir = board.parent
        self.artifacts[0]["metadata"].update(
            {
                "storyboard_manifest_sha256": "a" * 64,
                "source_video_sha256": _digest(source.read_bytes()),
                "source_keyframe_sheet_sha256": "b" * 64,
                "replacement_control_keyframe_sheet_sha256": "c" * 64,
                "replacement_control_keyframe_receipt_sha256": "d" * 64,
                "replacement_target_sha256s": [_digest(model.read_bytes())],
                "approved_visible_text_locks_sha256": _EMPTY_VISIBLE_TEXT_LOCKS_SHA,
                "visible_text_lock_ids": [],
                "segment_ids": ["S01"],
                "page_cut_ids": ["C01"],
                "storyboard_page": 1,
                "storyboard_page_count": 1,
            }
        )
        absent = {"present": False, "values": [], "metadata": [], "sha256": []}
        self.snapshot = SimpleNamespace(
            slots_manifest={
                "slots": {
                    "source_video": {"present": True, "values": ["source.mp4"], "metadata": [{}], "sha256": [_digest(source.read_bytes())]},
                    "new_product_image": dict(absent),
                    "new_model_image": {"present": True, "values": ["model.png"], "metadata": [{}], "sha256": [_digest(model.read_bytes())]},
                    "ui_screenshot": dict(absent),
                    "app_store_url": dict(absent),
                    "ui_operation_video": dict(absent),
                    "tail_video": dict(absent),
                }
            },
        )

    @contextmanager
    def materialize_slot(self, slot_id: str, *, index: int = 0):
        assert index == 0
        mapping = {"source_video": self.source, "new_model_image": self.model}
        path = mapping[slot_id]
        yield _Materialized(path, _digest(path.read_bytes()))


class _MusicVideoAuditContext(_VideoAuditContext):
    def __init__(self, *, board: Path, source: Path, model: Path, song: Path) -> None:
        super().__init__(board=board, source=source, model=model)
        self.song = song
        self.snapshot.slots_manifest["extensions"] = {
            "background_music": {
                "extension_id": "input_contract_v2.background_music",
                "values": ["uploads/job/song.mp3"],
                "sha256": [_digest(song.read_bytes())],
                "metadata": [{"object_key": "uploads/job/song.mp3", "sha256": _digest(song.read_bytes()), "size_bytes": len(song.read_bytes())}],
            }
        }

    @contextmanager
    def materialize_extension(self, extension_id: str, *, index: int = 0):
        assert (extension_id, index) == ("background_music", 0)
        yield _Materialized(self.song, _digest(self.song.read_bytes()))


class _RouteRegionsContext:
    def __init__(
        self,
        *,
        product: bool = False,
        model: bool = False,
        ui_video: bool = False,
        ui_target: bool = False,
        ui_rebuild_enabled: bool = False,
        output_language: str | None = None,
        cuts: list[dict[str, object]] | None = None,
    ) -> None:
        absent = {"present": False, "values": [], "metadata": [], "sha256": []}
        slots = {
            "source_video": {"present": True, "values": ["source.mp4"], "metadata": [{}], "sha256": ["a" * 64]},
            "new_product_image": {"present": product, "values": ["product.png"] if product else [], "metadata": [{}] if product else [], "sha256": ["b" * 64] if product else []},
            "new_model_image": {"present": model, "values": ["model.png"] if model else [], "metadata": [{}] if model else [], "sha256": ["c" * 64] if model else []},
            "ui_screenshot": {"present": ui_target, "values": ["ui.png"] if ui_target else [], "metadata": [{}] if ui_target else [], "sha256": ["e" * 64] if ui_target else []},
            "app_store_url": dict(absent),
            "ui_operation_video": {"present": ui_video, "values": ["ui.mp4"] if ui_video else [], "metadata": [{}] if ui_video else [], "sha256": ["d" * 64] if ui_video else []},
            "tail_video": dict(absent),
        }
        self.snapshot = SimpleNamespace(
            slots_manifest={
                "slots": slots,
                "routes": {"ui": "opaque_ui_demo" if ui_video else "generated_ui_demo" if (ui_target or (ui_rebuild_enabled and (product or model or output_language))) else "source_ui_keep"},
                "extensions": {"ui_rebuild_enabled": ui_rebuild_enabled},
                "output_language": output_language,
            }
        )
        self.stage_outputs = {
            "analyze_dynamics": {
                "source_dynamics_analysis": {
                    "source_width": 720,
                    "source_height": 1280,
                    "fps_num": 24,
                    "fps_den": 1,
                    "source_language": "en",
                    "source_cuts": cuts
                    or [
                        {
                            "cut_id": "C01",
                            "start_us": 0,
                            "end_us": 1_000_000,
                            "scene": "full-screen app interface",
                            "action": "dragging a profile card",
                            "transition": "slide_left",
                            "transition_shell": {"entry": {"kind": "slide_left"}, "exit": {"kind": "slide_right"}},
                        },
                        {
                            "cut_id": "C02",
                            "start_us": 1_000_000,
                            "end_us": 2_000_000,
                            "scene": "creator speaking to camera",
                            "action": "points at product",
                            "transition": "cut",
                        },
                    ],
                }
            }
        }
        self.published: list[dict[str, object]] = []

    def publish_bytes(self, *, kind: str, data: bytes, content_type: str, expected_sha256: str, metadata=None):
        assert _digest(data) == expected_sha256
        item = {
            "kind": kind,
            "object_key": f"temporary/job/{kind}-{expected_sha256}",
            "sha256": expected_sha256,
            "size_bytes": len(data),
            "content_type": content_type,
            "metadata": dict(metadata or {}),
        }
        self.published.append(item)
        return item


def test_storyboard_stage_publishes_a_real_image2_board_and_binds_it_to_the_revision(monkeypatch, tmp_path: Path) -> None:
    from server.packaged_stages import StoryboardStage
    from server.review_models import RevisionManifest
    import server.packaged_stages as stages

    reference = tmp_path / "model.png"
    reference.write_bytes(b"target-model-image")
    context = _StoryboardContext(reference=reference)
    image2 = _Image2()

    class _PlannerModule:
        @staticmethod
        def plan_structured_segments(_regions, _cuts):
            return {
                "segments": [
                    {"segment_id": "S01", "cut_ids": ["C01"], "start_ms": 0, "end_ms": 4000, "duration_ms": 4000}
                ]
            }

    monkeypatch.setattr(
        stages,
        "_read_json_artifact",
        lambda *_args, **_kwargs: {
            "cuts": [{"cut_id": "C01", "start_ms": 0, "end_ms": 4000, "scene": "creator holds product", "action": "creator smiles", "camera": "close-up"}],
            "visible_text_locks": [],
            "visible_text_locks_sha256": _EMPTY_VISIBLE_TEXT_LOCKS_SHA,
        },
    )
    real_load_module = stages._load_module
    monkeypatch.setattr(
        stages,
        "_load_module",
        lambda path, *args, **kwargs: _PlannerModule if path.endswith("segment_plan.py") else real_load_module(path, *args, **kwargs),
    )

    # The planner is not relevant to this Stage-7 media binding behavior.
    # Bypass the strongly typed production revision constructor and inject the
    # already-generated text revision exactly as the prior stage would.
    stage = StoryboardStage.__new__(StoryboardStage)
    stage._image_client = image2
    stage._revision = SimpleNamespace(
        run=lambda **_kwargs: {
            "storyboard_revision": RevisionManifest(
                kind="storyboard", revision=1, object_key="temporary/job/storyboard-revision.json",
                sha256="e" * 64, inputs_sha256="f" * 64,
            ),
            "published_artifacts": [],
        }
    )

    source_sheet = tmp_path / "source-keyframes.png"
    source_sheet.write_bytes(_png_bytes())
    stage._source_keyframe_sheet = lambda *_args, **_kwargs: {
        "path": source_sheet,
        "source_video_sha256": "a" * 64,
        "source_keyframes": [{"cut_id": "C01", "timestamp_us": 0, "sha256": "1" * 64}],
        "source_keyframe_sheet_sha256": _digest(source_sheet.read_bytes()),
    }

    result = stage.run(context=context, input_artifacts=[])

    assert len(image2.calls) == 3
    normalize_call, control_call, board_call = image2.calls
    assert normalize_call["aspect_ratio"] == "1:1"
    assert normalize_call["reference_images"] == [reference]
    assert control_call["aspect_ratio"] == "9:16"
    assert control_call["resolution"] == "2k"
    assert control_call["quality"] == "medium"
    assert control_call["reference_images"][0] == source_sheet
    assert control_call["reference_images"][1].name == "new_model_image-00-sheet.png"
    assert "replacement control keyframe sheet" in control_call["prompt"]
    assert "Reference image 1 is the complete source Cut contact sheet" in control_call["prompt"]
    assert "one complete replacement-control sheet" in control_call["prompt"]
    assert "replace only the authorized model identity layer" in control_call["prompt"]
    assert "must remain unchanged" in control_call["prompt"]
    assert "All existing physical text, printed graphics, garment prints, logos, signs and shop boards" in control_call["prompt"]
    assert "Never blur, pixelate, mosaic, smudge, gray out, black out, censor, redact, soften" in control_call["prompt"]
    assert "add unapproved text" not in control_call["prompt"]
    assert "not inside an authorized replacement layer or an approved scene-surface text lock" in control_call["prompt"]
    assert "Do not recreate screen-space subtitle, caption, CTA, lower-third, sticker or wordmark glyphs" in control_call["prompt"]
    assert board_call["aspect_ratio"] == "9:16"
    assert board_call["reference_images"][1:] == []
    assert board_call["reference_images"][0].name == "replacement-control-keyframes.png"
    assert "Reference image 1 is the replacement-control sheet" in board_call["prompt"]
    assert "authorized character identity is already resolved inside Reference image 1" in board_call["prompt"]
    # The production request must be the filled packaged director-board
    # template, not a short hand-written prompt that merely says "layout".
    for required_layout_section in (
        "Use case: infographic-diagram",
        "Fixed layout:",
        "- Top: shared creative direction",
        "- Left: CHARACTER section",
        "- Center: STORYBOARD section",
        "- Right: TARGET EVIDENCE section",
        "- Bottom: large short labels",
        "Storyboard cards:",
        "Exact allowed text:",
    ):
        assert required_layout_section in board_call["prompt"]
    assert board_call["prompt"].lstrip().startswith("Use case: infographic-diagram")
    assert "## Revision-scoped Cut outputs" not in board_call["prompt"]
    assert "{{" not in board_call["prompt"]
    assert "source-keyframes.png" not in {path.name for path in board_call["reference_images"]}
    manifest = result["storyboard_revision"]
    assert manifest.grid_object_key and manifest.grid_sha256
    assert [(cut.cut_id, cut.object_key, cut.sha256) for cut in manifest.cut_images] == [
        ("C01", manifest.grid_object_key, manifest.grid_sha256)
    ]
    board = next(item for item in context.published if item["kind"] == "storyboard_image")
    from server.visible_text_contract import visible_text_locks_sha256

    assert board["metadata"]["segment_id"] == "S01"
    assert board["metadata"]["storyboard_revision"] == 1
    assert board["metadata"]["logical_name"] == "storyboards/segment_01_v1.png"
    assert board["metadata"]["presentation"] == "image_set"
    assert board["metadata"]["approval_scope"] == "all_segments_together"
    assert board["metadata"]["text_only_substitute_forbidden"] is True
    assert board["metadata"]["storyboard_manifest_sha256"] == "e" * 64
    assert board["metadata"]["source_video_sha256"] == "a" * 64
    assert board["metadata"]["source_keyframe_sheet_sha256"] == _digest(source_sheet.read_bytes())
    assert board["metadata"]["replacement_target_sha256s"] == [_digest(reference.read_bytes())]
    assert board["metadata"]["approved_visible_text_locks_sha256"] == visible_text_locks_sha256([])
    assert len(board["metadata"]["replacement_control_keyframe_sheet_sha256"]) == 64
    assert len(board["metadata"]["replacement_control_keyframe_receipt_sha256"]) == 64
    control = next(item for item in context.published if item["kind"] == "replacement_control_keyframe_sheet")
    assert control["metadata"]["source_keyframe_sheet_sha256"] == _digest(source_sheet.read_bytes())
    assert control["metadata"]["generator_kind"] == "runninghub_image2"
    assert control["metadata"]["generation_mode"] == "single_sheet_image_to_image"
    assert control["metadata"]["image2_call_count"] == 1
    normalized = next(item for item in context.published if item["kind"] == "normalized_target_asset_sheet")
    assert normalized["metadata"]["slot_id"] == "new_model_image"
    assert normalized["metadata"]["source_asset_sha256"] == _digest(reference.read_bytes())


def test_storyboard_stage_keeps_the_source_control_chain_when_no_visual_target_is_supplied(
    monkeypatch, tmp_path: Path
) -> None:
    """Language-only/source-preserve generation still needs a reviewable control board lineage."""

    from server.packaged_stages import StoryboardStage
    from server.review_models import RevisionManifest
    import server.packaged_stages as stages

    reference = tmp_path / "unused-model.png"
    reference.write_bytes(b"unused")
    context = _StoryboardContext(reference=reference)
    context.snapshot.slots_manifest["slots"]["new_model_image"] = {
        "present": False, "values": [], "metadata": [], "sha256": []
    }
    image2 = _Image2()

    class _PlannerModule:
        @staticmethod
        def plan_structured_segments(_regions, _cuts):
            return {"segments": [{"segment_id": "S01", "cut_ids": ["C01"], "start_ms": 0, "end_ms": 4000, "duration_ms": 4000}]}

    monkeypatch.setattr(
        stages,
        "_read_json_artifact",
        lambda *_args, **_kwargs: {
            "cuts": [{"cut_id": "C01", "start_ms": 0, "end_ms": 4000, "scene": "source scene", "action": "source action", "camera": "source camera"}],
            "visible_text_locks": [],
            "visible_text_locks_sha256": _EMPTY_VISIBLE_TEXT_LOCKS_SHA,
        },
    )
    real_load_module = stages._load_module
    monkeypatch.setattr(
        stages,
        "_load_module",
        lambda path, *args, **kwargs: _PlannerModule if path.endswith("segment_plan.py") else real_load_module(path, *args, **kwargs),
    )
    stage = StoryboardStage.__new__(StoryboardStage)
    stage._image_client = image2
    stage._revision = SimpleNamespace(
        run=lambda **_kwargs: {
            "storyboard_revision": RevisionManifest(
                kind="storyboard", revision=1, object_key="temporary/job/storyboard-revision.json",
                sha256="e" * 64, inputs_sha256="f" * 64,
            ),
            "published_artifacts": [],
        }
    )
    source_sheet = tmp_path / "source-keyframes.png"
    source_sheet.write_bytes(_png_bytes())
    stage._source_keyframe_sheet = lambda *_args, **_kwargs: {
        "path": source_sheet,
        "source_video_sha256": "a" * 64,
        "source_keyframes": [{"cut_id": "C01", "timestamp_us": 0, "sha256": "1" * 64}],
        "source_keyframe_sheet_sha256": _digest(source_sheet.read_bytes()),
    }

    stage.run(context=context, input_artifacts=[])

    assert len(image2.calls) == 2
    control_call, board_call = image2.calls
    assert control_call["reference_images"] == [source_sheet]
    assert control_call["aspect_ratio"] == "9:16"
    assert board_call["reference_images"][0].name == "replacement-control-keyframes.png"


def test_replacement_control_sheet_blocks_localized_blur_before_publication(tmp_path: Path) -> None:
    """A locally censored control panel cannot reach storyboard publication."""

    from PIL import Image, ImageFilter
    from server.errors import ReplicationError
    from server.packaged_stages import StoryboardStage

    source = Image.effect_noise((512, 512), 96).convert("RGB")
    source_path = tmp_path / "source-keyframes.png"
    source.save(source_path, format="PNG")
    blurred = source.copy()
    blurred.paste(source.crop((128, 128, 256, 256)).filter(ImageFilter.GaussianBlur(radius=12)), (128, 128))
    rendered = io.BytesIO()
    blurred.save(rendered, format="PNG")

    class BlurImage2:
        def run_image2(self, **_kwargs):
            return {
                "task_id": "image2-task",
                "image_bytes": rendered.getvalue(),
                "receipt": {"request_sha256": "c" * 64, "response_sha256": "d" * 64, "task_id": "image2-task"},
            }

    reference = tmp_path / "model.png"
    reference.write_bytes(b"target-model-image")
    context = _StoryboardContext(reference=reference)
    stage = StoryboardStage.__new__(StoryboardStage)
    stage._image_client = BlurImage2()

    with pytest.raises(ReplicationError, match="blurred or censored"):
        stage._replacement_control_sheet(
            context=context,
            source_dynamics={},
            source_sheet={
                "path": source_path,
                "source_keyframes": [{"cut_id": "C01"}],
            },
            target_references=[],
            visible_text_locks=[],
        )
    assert context.published == []


def test_replacement_control_prompt_uses_surface_locks_and_excludes_overlay_glyphs(tmp_path: Path) -> None:
    """Physical copy is prompt-bound; approved screen overlays stay in the deterministic lane."""

    from server.errors import ReplicationError
    from server.packaged_stages import StoryboardStage

    source_path = tmp_path / "source-keyframes.png"
    source_path.write_bytes(_png_bytes())
    reference = tmp_path / "model.png"
    reference.write_bytes(b"target-model-image")

    class CapturingImage2:
        def __init__(self) -> None:
            self.prompt = ""

        def run_image2(self, **kwargs):
            self.prompt = str(kwargs["prompt"])
            raise RuntimeError("stop after prompt capture")

    image2 = CapturingImage2()
    context = _StoryboardContext(reference=reference)
    stage = StoryboardStage.__new__(StoryboardStage)
    stage._image_client = image2
    surface_placement = {
        "carrier_id": "shop-sign-1",
        "surface_relation": "painted on the wall",
        "motion_behavior": "moves with the camera pan",
    }
    locks = [
        {
            "text_id": "surface-replace",
            "cut_ids": ["C01"],
            "start_ms": 0,
            "end_ms": 1000,
            "kind": "physical_sign_text",
            "source_evidence_sha256": "a" * 64,
            "approved_text": "NEW OFFER",
            "disposition": "replace",
            "placement": surface_placement,
        },
        {
            "text_id": "surface-remove",
            "cut_ids": ["C01"],
            "start_ms": 0,
            "end_ms": 1000,
            "kind": "wardrobe_text",
            "source_evidence_sha256": "b" * 64,
            "approved_text": "",
            "disposition": "remove",
            "placement": {
                "carrier_id": "shirt-1",
                "surface_relation": "printed on the shirt",
                "motion_behavior": "folds with the shirt",
            },
        },
        {
            "text_id": "overlay-keep",
            "cut_ids": ["C01"],
            "start_ms": 0,
            "end_ms": 1000,
            "kind": "subtitle",
            "source_evidence_sha256": "c" * 64,
            "approved_text": "Tap to buy",
            "disposition": "keep",
            "placement": {},
        },
    ]

    with pytest.raises(ReplicationError, match="replacement control generation failed"):
        stage._replacement_control_sheet(
            context=context,
            source_dynamics={},
            source_sheet={"path": source_path, "source_keyframes": [{"cut_id": "C01"}]},
            target_references=[],
            visible_text_locks=locks,
        )

    assert 'render the exact approved text "NEW OFFER"' in image2.prompt
    assert 'remove the source text from physical carrier "shirt-1"' in image2.prompt
    assert "Tap to buy" not in image2.prompt


def test_source_keyframe_sheet_extracts_one_real_frame_for_each_source_cut(monkeypatch, tmp_path: Path) -> None:
    """The source-control chain must work without the storyboard test double."""

    from PIL import Image
    from server.packaged_stages import StoryboardStage
    import server.packaged_stages as stages

    source = tmp_path / "source.mp4"
    source.write_bytes(b"source-video")
    source_sha = _digest(source.read_bytes())
    calls: list[list[str]] = []

    class Context:
        work_dir = tmp_path

        def __init__(self) -> None:
            self.published: list[dict[str, object]] = []

        @contextmanager
        def materialize_slot(self, slot_id: str, *, index: int = 0):
            assert (slot_id, index) == ("source_video", 0)
            yield _Materialized(source, source_sha)

        def publish_bytes(self, *, kind: str, data: bytes, content_type: str, expected_sha256: str, metadata=None):
            assert _digest(data) == expected_sha256
            artifact = {"kind": kind, "sha256": expected_sha256, "metadata": dict(metadata or {})}
            self.published.append(artifact)
            return artifact

    def fake_ffmpeg(command, **_kwargs):
        calls.append(list(command))
        output_pattern = str(command[-1])
        for index in range(1, 3):
            output = Path(output_pattern.replace("%03d", f"{index:03d}"))
            output.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (16, 9), "black").save(output, format="PNG")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(stages.subprocess, "run", fake_ffmpeg)
    result = StoryboardStage._source_keyframe_sheet(
        Context(),
        {
            "fps_num": 30,
            "fps_den": 1,
            "source_cuts": [
                {"cut_id": "C01", "start_us": 0, "end_us": 1_000_000},
                {"cut_id": "C02", "start_us": 1_000_000, "end_us": 2_000_000},
            ]
        },
    )

    assert [item["cut_id"] for item in result["source_keyframes"]] == ["C01", "C02"]
    assert len(calls) == 1
    assert "select=" in calls[0][calls[0].index("-vf") + 1]
    assert calls[0][calls[0].index("-vsync") + 1] == "0"
    assert result["path"].is_file()


def test_person_region_box_detects_a_static_right_side_ui_panel(tmp_path: Path) -> None:
    from PIL import Image
    import server.packaged_stages as stages

    paths: list[Path] = []
    for index, tone in enumerate((0, 255, 64), start=1):
        image = Image.new("L", (100, 160), 128)
        image.paste(tone, (0, 0, 40, 160))
        path = tmp_path / f"source-{index:02d}.png"
        image.save(path, format="PNG")
        paths.append(path)

    assert stages._person_region_box(paths) == (0, 40)


def test_person_region_box_keeps_full_frame_when_no_decisive_static_panel_exists(tmp_path: Path) -> None:
    from PIL import Image
    import server.packaged_stages as stages

    paths: list[Path] = []
    for index, tone in enumerate((0, 255, 64), start=1):
        image = Image.new("L", (100, 160), tone)
        path = tmp_path / f"source-{index:02d}.png"
        image.save(path, format="PNG")
        paths.append(path)

    assert stages._person_region_box(paths) is None


def test_source_keyframe_sheet_crops_detected_static_ui_panel_before_assembly(monkeypatch, tmp_path: Path) -> None:
    from PIL import Image
    from server.packaged_stages import StoryboardStage
    import server.packaged_stages as stages

    source = tmp_path / "source.mp4"
    source.write_bytes(b"source-video")
    source_sha = _digest(source.read_bytes())

    class Context:
        work_dir = tmp_path

        @contextmanager
        def materialize_slot(self, slot_id: str, *, index: int = 0):
            assert (slot_id, index) == ("source_video", 0)
            yield _Materialized(source, source_sha)

        def publish_bytes(self, *, kind: str, data: bytes, content_type: str, expected_sha256: str, metadata=None):
            return {"kind": kind, "sha256": expected_sha256, "metadata": dict(metadata or {})}

    def fake_ffmpeg(command, **_kwargs):
        output_pattern = str(command[-1])
        for index, tone in enumerate((0, 255, 64), start=1):
            image = Image.new("L", (100, 160), 128)
            image.paste(tone, (0, 0, 40, 160))
            output = Path(output_pattern.replace("%03d", f"{index:03d}"))
            output.parent.mkdir(parents=True, exist_ok=True)
            image.save(output, format="PNG")

    monkeypatch.setattr(stages.subprocess, "run", fake_ffmpeg)
    result = StoryboardStage._source_keyframe_sheet(
        Context(),
        {
            "fps_num": 30,
            "fps_den": 1,
            "source_cuts": [
                {"cut_id": "C01", "start_us": 0, "end_us": 1_000_000, "subject_presence": "identifiable"},
                {"cut_id": "C02", "start_us": 1_000_000, "end_us": 2_000_000, "subject_presence": "identifiable"},
                {"cut_id": "C03", "start_us": 2_000_000, "end_us": 3_000_000, "subject_presence": "identifiable"},
            ],
        },
    )

    with Image.open(tmp_path / "reference_frames" / "source-C01.png") as frame:
        assert frame.size == (40, 160)
    assert result["person_region_crop"] == [0, 40]
    assert all(item["person_region_crop"] == [0, 40] for item in result["source_keyframes"])


def test_director_storyboard_prompt_forbids_asset_showcase_panels() -> None:
    from server.packaged_stages import StoryboardStage

    prompt = StoryboardStage._segment_prompt(
        segment={"segment_id": "S01", "cut_ids": ["C01"], "duration_ms": 4_000},
        cuts={"C01": {"cut_id": "C01", "start_ms": 0, "end_ms": 4_000, "scene": "creator", "action": "shows product", "camera": "close-up"}},
        visible_text_locks=[],
    )

    for forbidden in ("asset showcase panel", "character sheet", "product sheet", "reference gallery", "split-screen comparison"):
        assert forbidden in prompt


def test_source_keyframe_sheet_filters_ui_only_cuts_without_creating_empty_slots(monkeypatch, tmp_path: Path) -> None:
    from PIL import Image
    from server.packaged_stages import StoryboardStage
    import server.packaged_stages as stages

    source = tmp_path / "source.mp4"
    source.write_bytes(b"source-video")
    source_sha = _digest(source.read_bytes())

    class Context:
        work_dir = tmp_path

        def __init__(self) -> None:
            self.published: list[dict[str, object]] = []

        @contextmanager
        def materialize_slot(self, slot_id: str, *, index: int = 0):
            assert (slot_id, index) == ("source_video", 0)
            yield _Materialized(source, source_sha)

        def publish_bytes(self, *, kind: str, data: bytes, content_type: str, expected_sha256: str, metadata=None):
            artifact = {"kind": kind, "sha256": expected_sha256, "metadata": dict(metadata or {})}
            self.published.append(artifact)
            return artifact

    def fake_ffmpeg(command, **_kwargs):
        output_pattern = str(command[-1])
        output = Path(output_pattern.replace("%03d", "001"))
        output.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (16, 9), "black").save(output, format="PNG")

    monkeypatch.setattr(stages.subprocess, "run", fake_ffmpeg)
    result = StoryboardStage._source_keyframe_sheet(
        Context(),
        {
            "fps_num": 30,
            "fps_den": 1,
            "source_cuts": [
                {"cut_id": "C01", "start_us": 0, "end_us": 1_000_000, "subject_presence": "screen_pixels_only"},
                {"cut_id": "C02", "start_us": 1_000_000, "end_us": 2_000_000, "subject_presence": "identifiable"},
            ],
        },
    )

    assert [item["cut_id"] for item in result["source_keyframes"]] == ["C02"]
    assert result["person_filter_applied"] is True
    published = result["published_artifacts"][0]
    assert published["metadata"]["source_cut_count"] == 2
    assert published["metadata"]["selected_cut_count"] == 1


def test_source_keyframe_sheet_falls_back_to_all_cuts_when_no_person_cut_is_known(monkeypatch, tmp_path: Path) -> None:
    from PIL import Image
    from server.packaged_stages import StoryboardStage
    import server.packaged_stages as stages

    source = tmp_path / "source.mp4"
    source.write_bytes(b"source-video")
    source_sha = _digest(source.read_bytes())

    class Context:
        work_dir = tmp_path

        @contextmanager
        def materialize_slot(self, slot_id: str, *, index: int = 0):
            yield _Materialized(source, source_sha)

        def publish_bytes(self, *, kind: str, data: bytes, content_type: str, expected_sha256: str, metadata=None):
            return {"kind": kind, "sha256": expected_sha256, "metadata": dict(metadata or {})}

    def fake_ffmpeg(command, **_kwargs):
        output_pattern = str(command[-1])
        for index in range(1, 3):
            output = Path(output_pattern.replace("%03d", f"{index:03d}"))
            output.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (16, 9), "black").save(output, format="PNG")

    monkeypatch.setattr(stages.subprocess, "run", fake_ffmpeg)
    result = StoryboardStage._source_keyframe_sheet(
        Context(),
        {
            "fps_num": 30,
            "fps_den": 1,
            "source_cuts": [
                {"cut_id": "C01", "start_us": 0, "end_us": 1_000_000, "subject_presence": "screen_pixels_only"},
                {"cut_id": "C02", "start_us": 1_000_000, "end_us": 2_000_000, "subject_presence": "none"},
            ],
        },
    )

    assert [item["cut_id"] for item in result["source_keyframes"]] == ["C01", "C02"]
    assert result["person_filter_applied"] is False


def test_storyboard_pagination_supports_twelve_cuts_and_rejects_thirteen() -> None:
    from server.packaged_stages import StoryboardStage
    from server.errors import ReplicationError

    pages = StoryboardStage._partition_storyboard_cuts([f"C{i:02d}" for i in range(1, 13)])
    assert [len(page) for page in pages] == [6, 6]
    assert pages[0] == tuple(f"C{i:02d}" for i in range(1, 7))
    assert pages[1] == tuple(f"C{i:02d}" for i in range(7, 13))
    with pytest.raises(ReplicationError, match="one to 12"):
        StoryboardStage._partition_storyboard_cuts([f"C{i:02d}" for i in range(1, 14)])


def test_seedance_audit_uploads_only_the_approved_storyboard_artifact(monkeypatch, tmp_path: Path) -> None:
    from server.packaged_stages import SeedanceAuditStage
    import server.packaged_stages as stages

    board = tmp_path / "board.png"
    board.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x02\xd0\x00\x00\x05\x00\x08\x02\x00\x00\x00"
    )
    context = _AuditContext(board=board)
    uploader = _Uploader()
    stage = SeedanceAuditStage(provider=object(), media_uploader=uploader)
    storyboard_url = stage._upload_storyboard(context, segment_id="S01")
    assert uploader.paths == [board]
    assert storyboard_url == "https://media.example.test/board.png"


def test_seedance_audit_uploads_only_the_matching_source_segment_with_a_verified_binding(monkeypatch, tmp_path: Path) -> None:
    from server.packaged_stages import SeedanceAuditStage
    import server.packaged_stages as stages

    board = tmp_path / "board.png"
    model = tmp_path / "model.png"
    source = tmp_path / "source.mp4"
    board.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR\x00\x00\x02\xd0\x00\x00\x05\x00\x08\x02\x00\x00\x00")
    model.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR\x00\x00\x02\xd0\x00\x00\x05\x00\x08\x02\x00\x00\x00model")
    source.write_bytes(b"source-video-bytes")
    context = _VideoAuditContext(board=board, source=source, model=model)
    uploader = _Uploader()

    segment_plan = {"segments": [{"segment_id": "S01", "start_ms": 0, "end_ms": 4000, "duration_ms": 4000, "cut_ids": ["C01"]}]}
    segment_plan_sha256 = _canonical_digest(segment_plan)
    contract = {
        "segment_plan": segment_plan, "segment_plan_sha256": segment_plan_sha256,
        "segments": [{
            "segment_id": "S01", "segment_plan_sha256": segment_plan_sha256,
            "compiled_prompt": {
                "prompt": _source_video_prompt("@Image1 is the approved character reference. @Image2 is the approved storyboard page."),
                "compiler": {"output_sha256": "b" * 64},
                "source_contract": {"segment": {"duration_ms": 4000}},
            },
        }],
    }
    monkeypatch.setattr(stages, "_read_json_artifact", lambda *_args, **_kwargs: contract)

    def segmenter(*, source_path: Path, start_ms: int, end_ms: int, destination: Path) -> Path:
        assert source_path == source
        assert (start_ms, end_ms) == (0, 4000)
        destination.write_bytes(b"\x00\x00\x00\x18ftypisomsource-segment")
        return destination

    stage = SeedanceAuditStage(provider=object(), media_uploader=uploader, video_segmenter=segmenter)
    result = stage.run(context=context, input_artifacts=[])

    row = result["seedance_request_audit"]["segments"][0]
    assert row["payload_template"]["imageUrls"] == [
        "https://media.example.test/model.png", "https://media.example.test/board.png"
    ]
    assert row["payload_template"]["videoUrls"] == ["https://media.example.test/S01-source-reference.mp4"]
    assert row["video_reference_binding"] == {
        "schema_version": "usfr-video-reference/v1",
        "url": "https://media.example.test/S01-source-reference.mp4",
        "source_video_sha256": _digest(source.read_bytes()),
        "source_slice_sha256": _digest(b"\x00\x00\x00\x18ftypisomsource-segment"),
        "segment_id": "S01",
        "segment_plan_sha256": segment_plan_sha256,
        "source_video_reference_artifact_id": f"artifact-source_video_reference-{_digest(b'\x00\x00\x00\x18ftypisomsource-segment')}",
        "start_ms": 0,
        "end_ms": 4000,
        "image_reference_binding_sha256": standard_contract.image_reference_binding_sha256(row["image_reference_binding"]),
        "target_changes": [{"kind": "new_model_image", "sha256": _digest(model.read_bytes())}],
    }


def test_seedance_prompt_reference_roles_follow_the_fixed_image_order() -> None:
    from server.packaged_stages import SeedancePromptStage

    absent = {"present": False, "sha256": []}
    context = SimpleNamespace(
        artifacts=({
            "kind": "storyboard_image",
            "metadata": {"segment_id": "S01", "segment_ids": ["S01"], "storyboard_page": 1},
        },),
        snapshot=SimpleNamespace(
            slots_manifest={
                "slots": {
                    "source_video": {"present": True, "sha256": ["a" * 64]},
                    "new_model_image": {"present": True, "sha256": ["b" * 64]},
                    "new_product_image": {"present": True, "sha256": ["c" * 64, "d" * 64]},
                    "ui_screenshot": dict(absent),
                    "app_store_url": dict(absent),
                    "ui_operation_video": dict(absent),
                    "tail_video": dict(absent),
                }
            }
        )
    )

    assert SeedancePromptStage._reference_roles(context, segment_id="S01") == [
        {
            "slot": 1,
            "tag": "@Image1",
            "kind": "new_model_identity",
            "subject_label": "Subject 1",
            "replaces_source_person": "",
            "role": "fixed new_model_image target truth",
        },
        {"slot": 2, "tag": "@Image2", "role": "fixed new_product_image target truth"},
        {"slot": 3, "tag": "@Image3", "role": "approved storyboard visual control page 1/1"},
        {"slot": 4, "tag": "@Image4", "role": "additional verified new_product_image detail"},
    ]


def test_route_regions_keeps_detected_source_ui_when_only_product_or_model_is_supplied() -> None:
    from server.packaged_stages import RouteRegionsStage

    result = RouteRegionsStage().run(
        context=_RouteRegionsContext(product=True, model=True),
        input_artifacts=[],
    )

    ui_region, ordinary_region = result["timeline_regions"]["regions"]
    assert ui_region["region_type"] == "source_interval"
    assert ui_region["media_origin"] == "source_interval"
    assert ui_region["assembly_policy"] == "splice_source_interval"
    assert ordinary_region["region_type"] == "generated"


def test_route_regions_rebuilds_ui_from_explicit_target_evidence() -> None:
    from server.packaged_stages import RouteRegionsStage

    result = RouteRegionsStage().run(
        context=_RouteRegionsContext(product=True, ui_target=True),
        input_artifacts=[],
    )

    ui_region = result["timeline_regions"]["regions"][0]
    assert ui_region["region_type"] == "generated_ui_demo"
    assert ui_region["media_origin"] == "generated_ui"
    assert ui_region["assembly_policy"] == "render_generated_ui"
    assert ui_region["source_ui_interaction_contract"]["language"] == {
        "source": "en",
        "target": "en",
        "mode": "preserve_source",
    }


def test_route_regions_can_opt_in_to_automatic_ui_rebuild_for_product_change() -> None:
    from server.packaged_stages import RouteRegionsStage

    result = RouteRegionsStage().run(
        context=_RouteRegionsContext(product=True, ui_rebuild_enabled=True),
        input_artifacts=[],
    )

    ui_region = result["timeline_regions"]["regions"][0]
    assert ui_region["region_type"] == "generated_ui_demo"


def test_route_regions_keeps_source_ui_when_only_output_language_is_requested() -> None:
    from server.packaged_stages import RouteRegionsStage

    result = RouteRegionsStage().run(
        context=_RouteRegionsContext(product=True, output_language="pt"),
        input_artifacts=[],
    )

    region = result["timeline_regions"]["regions"][0]
    assert region["region_type"] == "source_interval"
    assert region["media_origin"] == "source_interval"


def test_route_regions_preserves_uploaded_ui_video_priority_and_source_transition_shell() -> None:
    from server.packaged_stages import RouteRegionsStage

    result = RouteRegionsStage().run(
        context=_RouteRegionsContext(product=True, model=True, ui_video=True),
        input_artifacts=[],
    )

    ui_region = result["timeline_regions"]["regions"][0]
    assert ui_region["region_type"] == "opaque_ui_demo"
    assert ui_region["media_origin"] == "opaque_ui"
    assert ui_region["transition_shell"] == {
        "entry": {"kind": "slide_left"},
        "exit": {"kind": "slide_right"},
    }
    assert "source_ui_interaction_contract" not in ui_region


def test_route_regions_does_not_create_ui_rebuild_when_source_contains_no_ui_cut() -> None:
    from server.packaged_stages import RouteRegionsStage

    result = RouteRegionsStage().run(
        context=_RouteRegionsContext(
            product=True,
            cuts=[
                {
                    "cut_id": "C01",
                    "start_us": 0,
                    "end_us": 1_000_000,
                    "scene": "creator speaking to camera",
                    "action": "holds the product",
                    "transition": "cut",
                }
            ],
        ),
        input_artifacts=[],
    )

    region = result["timeline_regions"]["regions"][0]
    assert region["region_type"] == "generated"
    assert "source_ui_interaction_contract" not in region


def test_provider_request_carries_the_video_reference_binding_outside_the_standard_payload() -> None:
    from server.packaged_stages import SubmitProviderVideoStage

    payload = {
        "prompt": _source_video_prompt("@Image1 follow the approved source performance."),
        "resolution": "720p", "duration": "4",
        "imageUrls": ["https://media.example.test/board.png", "https://media.example.test/model.png"],
        "videoUrls": ["https://media.example.test/source-segment.mp4"],
        "audioUrls": [], "generateAudio": True, "ratio": "9:16",
        "realPersonMode": True, "conversionSlots": ["all"], "returnLastFrame": False, "seed": -1,
    }
    binding = {
        "schema_version": "usfr-video-reference/v1", "url": payload["videoUrls"][0],
        "source_video_sha256": "a" * 64, "source_slice_sha256": "b" * 64,
        "segment_id": "S01", "segment_plan_sha256": "d" * 64,
        "source_video_reference_artifact_id": "source-s01-artifact", "start_ms": 0, "end_ms": 4000,
        "image_reference_binding_sha256": "e" * 64,
        "target_changes": [{"kind": "new_model_image", "sha256": "c" * 64}],
    }
    lineage = {
        "schema_version": "seedance-final-reference-lineage/v1",
        "segment_id": "S01", "segment_plan_sha256": "d" * 64,
        "ordered_image_urls": list(payload["imageUrls"]), "ordered_video_urls": list(payload["videoUrls"]),
        "approved_board": {
            "artifact_id": "board-artifact", "object_key": "temporary/job/board.png", "kind": "storyboard_image",
            "sha256": "e" * 64, "segment_id": "S01", "storyboard_revision": 1,
            "storyboard_manifest_sha256": "f" * 64, "url": payload["imageUrls"][0],
            "source_video_sha256": "a" * 64, "source_keyframe_sheet_sha256": "0" * 64,
            "replacement_control_keyframe_sheet_sha256": "1" * 64,
            "replacement_control_keyframe_receipt_sha256": "2" * 64,
            "replacement_target_sha256s": ["c" * 64], "approved_visible_text_locks_sha256": "3" * 64,
        },
        "source_reference": {
            "artifact_id": "source-s01-artifact", "object_key": "temporary/job/source-s01.mp4",
            "kind": "source_video_reference", "sha256": "b" * 64, "source_video_sha256": "a" * 64,
            "segment_id": "S01", "segment_plan_sha256": "d" * 64,
            "start_ms": 0, "end_ms": 4000, "url": payload["videoUrls"][0],
        },
        "allowed_target_changes": [{"kind": "new_model_image", "sha256": "c" * 64, "image_slot": 2, "url": payload["imageUrls"][1]}],
        "forbidden_artifact_kinds": ["source_keyframe_sheet", "replacement_control_keyframe_sheet", "replacement_control_keyframe_receipt"],
    }

    request = SubmitProviderVideoStage._provider_request(
        payload, binding, final_reference_lineage=lineage, audio_reference_binding=None
    )

    assert dict(request) == payload
    assert request.video_reference_binding == binding
    assert request.final_reference_lineage == lineage


def test_provider_request_rejects_a_source_video_without_the_private_final_reference_lineage() -> None:
    """A valid public URL binding alone cannot substitute an approved-board lineage."""

    from server.packaged_stages import SubmitProviderVideoStage
    from server.errors import ReplicationError

    payload = {
        "prompt": _source_video_prompt("@Image1 follows the approved director board and @Image2 fixes the model identity."),
        "resolution": "720p", "duration": "4",
        "imageUrls": ["https://media.example.test/board.png", "https://media.example.test/model.png"],
        "videoUrls": ["https://media.example.test/source-s01.mp4"],
        "audioUrls": [], "generateAudio": True, "ratio": "9:16",
        "realPersonMode": True, "conversionSlots": ["all"], "returnLastFrame": False, "seed": -1,
    }
    binding = {
        "schema_version": "usfr-video-reference/v1", "url": payload["videoUrls"][0],
        "source_video_sha256": "a" * 64, "source_slice_sha256": "b" * 64,
        "segment_id": "S01", "segment_plan_sha256": "c" * 64,
        "source_video_reference_artifact_id": "source-s01-artifact",
        "start_ms": 0, "end_ms": 4000,
        "image_reference_binding_sha256": "e" * 64,
        "target_changes": [{"kind": "new_model_image", "sha256": "d" * 64}],
    }

    with pytest.raises(ReplicationError, match="final reference lineage"):
        SubmitProviderVideoStage._provider_request(
            payload, binding, audio_reference_binding=None
        )


def test_provider_request_carries_the_audio_reference_binding_outside_the_standard_payload() -> None:
    from server.packaged_stages import SubmitProviderVideoStage

    payload = {
        "prompt": _source_video_prompt("@Image1 keep the approved action. Use @Audio1 only for this song window."),
        "resolution": "720p", "duration": "4",
        "imageUrls": ["https://media.example.test/board.png"],
        "videoUrls": [], "audioUrls": ["https://media.example.test/song-s01.wav"],
        "generateAudio": True, "ratio": "9:16",
        "realPersonMode": False, "conversionSlots": [], "returnLastFrame": False, "seed": -1,
    }
    binding = {
        "schema_version": "usfr-background-music-reference/v1", "url": payload["audioUrls"][0],
        "source_audio_sha256": "a" * 64, "source_slice_sha256": "b" * 64,
        "segment_id": "S01", "start_ms": 0, "end_ms": 4000, "segment_plan_sha256": "c" * 64,
        "replacement_timing_policy": "source_music_cut_in_out_exact",
        "source_music_windows": [{
            "event_id": "M01", "source_start_ms": 0, "source_end_ms": 4000,
            "segment_start_ms": 0, "segment_end_ms": 4000,
            "uploaded_start_ms": 0, "uploaded_end_ms": 4000,
        }],
    }
    receipt = {
        "schema_version": "usfr-background-music-artifact-receipt/v1",
        "artifact_id": "audio-s01-artifact",
        "object_key": "temporary/job/audio-s01-artifact",
        "kind": "background_music_reference",
        "sha256": binding["source_slice_sha256"],
        "source_audio_sha256": binding["source_audio_sha256"],
        "segment_id": binding["segment_id"],
        "start_ms": binding["start_ms"],
        "end_ms": binding["end_ms"],
        "segment_plan_sha256": binding["segment_plan_sha256"],
        "replacement_timing_policy": binding["replacement_timing_policy"],
        "source_music_windows": binding["source_music_windows"],
    }

    request = SubmitProviderVideoStage._provider_request(
        payload, None, audio_reference_binding=binding,
        audio_reference_artifact_receipt=receipt,
    )

    assert dict(request) == payload
    assert request.audio_reference_binding == binding
    assert request.audio_reference_artifact_receipt == receipt


def test_seedance_audit_uses_only_a_duration_bound_uploaded_music_fragment(monkeypatch, tmp_path: Path) -> None:
    from server.packaged_stages import SeedanceAuditStage
    import server.packaged_stages as stages

    board, model, source, song = (tmp_path / name for name in ("board.png", "model.png", "source.mp4", "song.mp3"))
    png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR\x00\x00\x02\xd0\x00\x00\x05\x00\x08\x02\x00\x00\x00"
    board.write_bytes(png)
    model.write_bytes(png)
    source.write_bytes(b"source-video-bytes")
    song.write_bytes(b"whole-uploaded-song-must-not-reach-audioUrls")
    context = _MusicVideoAuditContext(board=board, source=source, model=model, song=song)
    context.snapshot.slots_manifest["slots"]["new_model_image"] = {
        "present": False, "values": [], "metadata": [], "sha256": []
    }
    uploader = _Uploader()
    context.artifacts[0]["metadata"]["replacement_target_sha256s"] = []
    segment_plan = {"segments": [{"segment_id": "S01", "start_ms": 0, "end_ms": 4000, "duration_ms": 4000, "cut_ids": ["C01"]}]}
    segment_plan_sha256 = _canonical_digest(segment_plan)
    contract = {
        "segment_plan": segment_plan, "segment_plan_sha256": segment_plan_sha256,
        "segments": [{"segment_id": "S01", "segment_plan_sha256": segment_plan_sha256, "compiled_prompt": {
            "prompt": _source_video_prompt("@Image1 is the approved storyboard. Use @Audio1 as the approved song fragment."),
            "compiler": {"output_sha256": "b" * 64}, "source_contract": {"segment": {"duration_ms": 4000}},
        }}],
    }
    timeline = {
        "contract": "source-content-timeline/v1",
        "music_events": [{"event_id": "M01", "kind": "music", "start_ms": 0, "end_ms": 4000}],
    }
    monkeypatch.setattr(
        stages,
        "_read_json_artifact",
        lambda _context, *, kind, **_kwargs: {"seedance_input_contract": contract, "source_content_timeline": timeline}[kind],
    )

    def video_segmenter(*, destination: Path, **_kwargs):
        destination.write_bytes(b"\x00\x00\x00\x18ftypisomsource-segment")
        return destination

    def audio_segmenter(*, source_path: Path, start_ms: int, end_ms: int, source_music_windows: list[dict], destination: Path) -> Path:
        assert source_path == song
        assert (start_ms, end_ms) == (0, 4000)
        assert source_music_windows == [{
            "event_id": "M01", "source_start_ms": 0, "source_end_ms": 4000,
            "segment_start_ms": 0, "segment_end_ms": 4000,
            "uploaded_start_ms": 0, "uploaded_end_ms": 4000,
        }]
        destination.write_bytes(b"RIFFduration-bound-song-window")
        return destination

    result = SeedanceAuditStage(
        provider=object(), media_uploader=uploader, video_segmenter=video_segmenter,
        audio_segmenter=audio_segmenter, audit_secret="test-capability-secret"
    ).run(context=context, input_artifacts=[])

    row = result["seedance_request_audit"]["segments"][0]
    assert row["payload_template"]["imageUrls"] == ["https://media.example.test/board.png"]
    assert row["payload_template"]["videoUrls"] == ["https://media.example.test/S01-source-reference.mp4"]
    assert row["payload_template"]["audioUrls"] == ["https://media.example.test/S01-audio-reference.wav"]
    assert "song.mp3" not in row["payload_template"]["audioUrls"][0]
    assert row["audio_reference_binding"] == {
        "schema_version": "usfr-background-music-reference/v1",
        "url": "https://media.example.test/S01-audio-reference.wav",
        "source_audio_sha256": _digest(song.read_bytes()),
        "source_slice_sha256": _digest(b"RIFFduration-bound-song-window"),
        "segment_id": "S01", "start_ms": 0, "end_ms": 4000, "segment_plan_sha256": segment_plan_sha256,
        "replacement_timing_policy": "source_music_cut_in_out_exact",
        "source_music_windows": [{
            "event_id": "M01", "source_start_ms": 0, "source_end_ms": 4000,
            "segment_start_ms": 0, "segment_end_ms": 4000,
            "uploaded_start_ms": 0, "uploaded_end_ms": 4000,
        }],
    }
    assert row["provider_audit_proof"]["schema_version"] == "usfr-provider-audit-proof/v1"
    assert set(row["provider_audit_proof"]) == {"schema_version", "hmac_sha256"}
    assert row["provider_audit_proof"]["hmac_sha256"] not in repr(row["payload_template"])
    assert row["video_reference_binding"]["target_changes"] == [
        {"kind": "background_music", "sha256": _digest(song.read_bytes())}
    ]


def test_seedance_audit_pads_uploaded_audio_to_exact_source_music_windows(monkeypatch, tmp_path: Path) -> None:
    """A user upload must be silent outside the source music cut-in/cut-out."""

    from server.packaged_stages import SeedanceAuditStage
    import server.packaged_stages as stages

    board, model, source, song = (tmp_path / name for name in ("board.png", "model.png", "source.mp4", "song.mp3"))
    png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR\x00\x00\x02\xd0\x00\x00\x05\x00\x08\x02\x00\x00\x00"
    board.write_bytes(png)
    model.write_bytes(png)
    source.write_bytes(b"source-video-bytes")
    song.write_bytes(b"uploaded-audio")
    context = _MusicVideoAuditContext(board=board, source=source, model=model, song=song)
    context.snapshot.slots_manifest["slots"]["new_model_image"] = {
        "present": False, "values": [], "metadata": [], "sha256": []
    }
    context.artifacts[0]["metadata"]["replacement_target_sha256s"] = []
    segment_plan = {"segments": [{"segment_id": "S01", "start_ms": 0, "end_ms": 4000, "duration_ms": 4000, "cut_ids": ["C01"]}]}
    segment_plan_sha256 = _canonical_digest(segment_plan)
    contract = {
        "segment_plan": segment_plan, "segment_plan_sha256": segment_plan_sha256,
        "segments": [{"segment_id": "S01", "segment_plan_sha256": segment_plan_sha256, "compiled_prompt": {
                "prompt": _source_video_prompt("@Image1 approved storyboard. @Audio1 is silent outside the approved source music windows."),
            "compiler": {"output_sha256": "b" * 64}, "source_contract": {"segment": {"duration_ms": 4000}},
        }}],
    }
    timeline = {
        "contract": "source-content-timeline/v1",
        "music_events": [{"event_id": "M01", "kind": "music", "start_ms": 900, "end_ms": 3600}],
    }
    monkeypatch.setattr(
        stages,
        "_read_json_artifact",
        lambda _context, *, kind, **_kwargs: {"seedance_input_contract": contract, "source_content_timeline": timeline}[kind],
    )

    def video_segmenter(*, destination: Path, **_kwargs):
        destination.write_bytes(b"\x00\x00\x00\x18ftypisomsource-segment")
        return destination

    def audio_segmenter(*, source_path: Path, start_ms: int, end_ms: int, source_music_windows: list[dict], destination: Path) -> Path:
        assert source_path == song
        assert (start_ms, end_ms) == (0, 4000)
        assert source_music_windows == [
            {
                "event_id": "M01",
                "source_start_ms": 900,
                "source_end_ms": 3600,
                "segment_start_ms": 900,
                "segment_end_ms": 3600,
                "uploaded_start_ms": 0,
                "uploaded_end_ms": 2700,
            }
        ]
        destination.write_bytes(b"RIFFsilence-padded-exact-window")
        return destination

    result = SeedanceAuditStage(
        provider=object(), media_uploader=_Uploader(), video_segmenter=video_segmenter,
        audio_segmenter=audio_segmenter, audit_secret="test-capability-secret",
    ).run(context=context, input_artifacts=[])

    binding = result["seedance_request_audit"]["segments"][0]["audio_reference_binding"]
    assert binding["replacement_timing_policy"] == "source_music_cut_in_out_exact"
    assert binding["source_music_windows"] == [
        {
            "event_id": "M01",
            "source_start_ms": 900,
            "source_end_ms": 3600,
            "segment_start_ms": 900,
            "segment_end_ms": 3600,
            "uploaded_start_ms": 0,
            "uploaded_end_ms": 2700,
        }
    ]


def test_segment_music_bindings_resume_uploaded_audio_after_each_source_music_gap() -> None:
    from server.packaged_stages import _segment_music_window_bindings

    bindings = _segment_music_window_bindings(
        [
            {"event_id": "M01", "start_ms": 900, "end_ms": 3600},
            {"event_id": "M02", "start_ms": 5200, "end_ms": 7400},
        ],
        segment_start_ms=4000,
        segment_end_ms=8000,
    )

    assert bindings == [
        {
            "event_id": "M02",
            "source_start_ms": 5200,
            "source_end_ms": 7400,
            "segment_start_ms": 1200,
            "segment_end_ms": 3400,
            "uploaded_start_ms": 2700,
            "uploaded_end_ms": 4900,
        }
    ]


def test_seedance_prompt_marks_uploaded_music_as_audio1_before_compilation() -> None:
    from server.packaged_stages import SeedancePromptStage

    context = SimpleNamespace(
        snapshot=SimpleNamespace(
            slots_manifest={
                "extensions": {"background_music": {"extension_id": "input_contract_v2.background_music"}}
            }
        )
    )
    assert SeedancePromptStage._audio_instruction(context) == (
        "Use @Audio1 as the only uploaded audio reference. Match this segment's approved music cut-in/cut-out exactly; "
        "do not substitute a full-song track, new lyrics, or unrelated music."
    )


def _verified_uploaded_song_prompt_context(tmp_path: Path):
    """One frozen MV lyric line with the approved performer and song upload."""

    from test_performance_audio_contracts import _approved_lines, _lines

    song = tmp_path / "uploaded-song.wav"
    song.write_bytes(b"RIFFuploaded-song")
    timeline_sha = "a" * 64
    approved_line = dict(_approved_lines()[0])
    performance_line = {
        **_lines()[0],
        "final_audio_carrier": "source_audio_global_window_postproduction",
    }
    plan = {
        "segments": [
            {"segment_id": "S01", "cut_ids": ["C01"], "start_ms": 0, "end_ms": 4000, "duration_ms": 4000}
        ]
    }
    source_timeline = {
        "contract": "source-content-timeline/v1",
        "audio_lines": [{
            "line_id": "A01", "content_type": "sung", "start_ms": 0, "end_ms": 4000,
            "confidence": 0.99, "speaker_assignment": dict(approved_line["speaker_assignment"]),
        }],
        "music_events": [{"event_id": "M01", "kind": "music", "start_ms": 0, "end_ms": 4000}],
    }
    performance_contract = {
        "contract": "performance-line/v1",
        "source_content_timeline_sha256": timeline_sha,
        "cuts": [performance_line],
    }
    script = {
        "cuts": [{
            "cut_id": "C01", "start_ms": 0, "end_ms": 4000, "scene": "singer at the lake",
            "action": "sings toward camera", "camera": "close-up", "dialogue": "I will meet you by the lake",
        }]
    }
    storyboard = {"cuts": [{"cut_id": "C01", "composition": "close portrait", "continuity": "holds gaze"}]}
    sidecar = {
        "contract": "approved-script-lines/v1", "revision": 1, "script_sha256": "b" * 64,
        "source_content_timeline_sha256": timeline_sha, "line_contracts": [approved_line],
    }

    class Context:
        job_id = "mv-prompt-job"
        artifacts = (
            {"kind": "source_content_timeline", "artifact_id": "timeline", "sha256": timeline_sha},
            {"kind": "performance_line_contract", "artifact_id": "performance", "sha256": "c" * 64},
            {"kind": "uploaded_audio_classification", "artifact_id": "uploaded-audio", "sha256": "f" * 64},
            {"kind": "storyboard_image", "artifact_id": "storyboard", "sha256": "d" * 64,
             "metadata": {"segment_id": "S01", "segment_ids": ["S01"], "storyboard_page": 1}},
        )

        def __init__(self) -> None:
            self.snapshot = SimpleNamespace(
                approved_script_sha256="b" * 64,
                approved_storyboard_sha256="d" * 64,
                current_script_revision=1,
                slots_manifest={
                    "slots": {
                        "source_video": {"present": True, "sha256": ["e" * 64]},
                        "new_product_image": {"present": False, "sha256": []},
                        "new_model_image": {"present": False, "sha256": []},
                        "ui_screenshot": {"present": False, "sha256": []},
                        "app_store_url": {"present": False, "sha256": []},
                        "ui_operation_video": {"present": False, "sha256": []},
                        "tail_video": {"present": False, "sha256": []},
                    },
                    "extensions": {"background_music": {
                        "extension_id": "input_contract_v2.background_music", "sha256": ["f" * 64],
                    }},
                },
            )
            self.job_store = SimpleNamespace(get_script_approval=lambda _job_id, _revision: sidecar)
            self.published: list[dict[str, object]] = []

        @contextmanager
        def materialize_extension(self, extension_id: str, *, index: int = 0):
            assert (extension_id, index) == ("background_music", 0)
            yield _Materialized(song, _digest(song.read_bytes()))

        def publish_bytes(self, **kwargs):
            self.published.append(kwargs)
            return {"kind": kwargs["kind"], "sha256": kwargs["expected_sha256"]}

    values = {
        "script_revision": script,
        "storyboard_revision": storyboard,
        "segment_plan": plan,
        "source_content_timeline": source_timeline,
        "performance_line_contract": performance_contract,
        "uploaded_audio_classification": {
            "contract": "uploaded-audio-classification/v1",
            "audio_sha256": "f" * 64,
            "kind": "song",
            "confidence": 0.97,
            "classification_evidence_sha256": "1" * 64,
            "lyrics": [{"start_ms": 0, "end_ms": 4000, "text": "I will meet you by the lake"}],
        },
    }
    return Context(), values, performance_line


def test_seedance_prompt_uses_uploaded_song_audio_without_transcribing_lyrics(monkeypatch, tmp_path: Path) -> None:
    from server.packaged_stages import SeedancePromptStage
    import server.packaged_stages as stages

    context, artifacts, performance_line = _verified_uploaded_song_prompt_context(tmp_path)
    captured: dict[str, object] = {}

    class Compiler:
        @staticmethod
        def compile_prompt(**kwargs):
            captured.update(kwargs)
            return {"prompt": kwargs["segment"]["shots"][0]["audio"]}

    monkeypatch.setattr(stages, "_read_json_artifact", lambda _context, *, kind, **_kwargs: artifacts[kind])
    monkeypatch.setattr(stages, "_load_module", lambda *_args, **_kwargs: Compiler)
    transcriptions: list[Path] = []

    def transcribe(path: Path, *, language: str | None = None):
        transcriptions.append(path)
        assert language == "en"
        return [{"start": 0.0, "end": 4.0, "text": "I will meet you by the lake"}]

    adapter = SimpleNamespace(prompt_skill_files={"seedance-20": tmp_path / "seedance.md"})
    result = SeedancePromptStage(
        invocation_adapter=adapter, uploaded_song_transcriber=transcribe
    ).run(context=context, input_artifacts=[])

    assert transcriptions == []
    assert captured["performance_lines"] == []
    prompt = result["seedance_input_contract"]["segments"][0]["compiled_prompt"]["prompt"]
    assert "@Audio1" in prompt
    assert "audio-driven song performance" in prompt
    assert "Do not transcribe, quote, invent, or display lyrics" in prompt
    assert "0-4000ms" in captured["segment"]["shots"][0]["audio"]
    assert "silent outside" in captured["segment"]["shots"][0]["audio"]


def test_seedance_prompt_uses_confirmed_source_lyrics_without_an_uploaded_song(monkeypatch, tmp_path: Path) -> None:
    """A source music-video singer must not silently become a BGM-only prompt."""

    from server.packaged_stages import SeedancePromptStage
    import server.packaged_stages as stages

    context, artifacts, performance_line = _verified_uploaded_song_prompt_context(tmp_path)
    context.snapshot.slots_manifest["extensions"] = {}
    captured: dict[str, object] = {}

    class Compiler:
        @staticmethod
        def compile_prompt(**kwargs):
            captured.update(kwargs)
            line = kwargs["performance_lines"][0]
            return {"prompt": f'{line["speaker_assignment"]["speaker_id"]} sings exactly, "{line["exact_sung_text"]}".'}

    monkeypatch.setattr(stages, "_read_json_artifact", lambda _context, *, kind, **_kwargs: artifacts[kind])
    monkeypatch.setattr(stages, "_load_module", lambda *_args, **_kwargs: Compiler)
    adapter = SimpleNamespace(prompt_skill_files={"seedance-20": tmp_path / "seedance.md"})

    result = SeedancePromptStage(invocation_adapter=adapter).run(context=context, input_artifacts=[])

    assert captured["performance_lines"] == [performance_line]
    prompt = result["seedance_input_contract"]["segments"][0]["compiled_prompt"]["prompt"]
    assert "CHARACTER_A sings exactly" in prompt
    assert '"I will meet you by the lake"' in prompt


def test_seedance_prompt_does_not_compile_uploaded_song_lyrics_into_performance_lines(monkeypatch, tmp_path: Path) -> None:
    from server.packaged_stages import SeedancePromptStage
    import server.packaged_stages as stages

    context, artifacts, _performance_line = _verified_uploaded_song_prompt_context(tmp_path)
    replacement_lyric = "Meet me where the morning starts"
    artifacts["source_content_timeline"]["audio_lines"][0]["text"] = "I will meet you by the lake"
    approval = context.job_store.get_script_approval(context.job_id, 1)
    approval["line_contracts"][0]["text"]["exact"] = replacement_lyric
    approval["line_contracts"][0]["text"]["normalized"] = replacement_lyric.casefold()
    artifacts["uploaded_audio_classification"]["lyrics"] = [{"text": replacement_lyric}]
    captured: dict[str, object] = {}

    class Compiler:
        @staticmethod
        def compile_prompt(**kwargs):
            captured.update(kwargs)
            return {"prompt": "@Audio1 CHARACTER_A sings exactly."}

    monkeypatch.setattr(stages, "_read_json_artifact", lambda _context, *, kind, **_kwargs: artifacts[kind])
    monkeypatch.setattr(stages, "_load_module", lambda *_args, **_kwargs: Compiler)
    adapter = SimpleNamespace(prompt_skill_files={"seedance-20": tmp_path / "seedance.md"})

    SeedancePromptStage(
        invocation_adapter=adapter,
        uploaded_song_transcriber=lambda *_args, **_kwargs: [
            {"start": 0.0, "end": 4.0, "text": replacement_lyric}
        ],
    ).run(context=context, input_artifacts=[])

    assert captured["performance_lines"] == []
    assert "audio-driven song performance" in captured["segment"]["shots"][0]["audio"]


def test_seedance_prompt_uses_an_uploaded_non_song_as_window_bound_replacement_without_singing(monkeypatch, tmp_path: Path) -> None:
    from server.packaged_stages import SeedancePromptStage
    import server.packaged_stages as stages

    context, artifacts, _performance_line = _verified_uploaded_song_prompt_context(tmp_path)
    artifacts["uploaded_audio_classification"] = {
        "contract": "uploaded-audio-classification/v1",
        "audio_sha256": "f" * 64,
        "kind": "non_song",
        "confidence": 0.97,
        "classification_evidence_sha256": "1" * 64,
        "lyrics": [],
    }
    captured: dict[str, object] = {}

    class Compiler:
        @staticmethod
        def compile_prompt(**kwargs):
            captured.update(kwargs)
            return {"prompt": "Use @Audio1 only as the approved non-song replacement."}

    monkeypatch.setattr(stages, "_read_json_artifact", lambda _context, *, kind, **_kwargs: artifacts[kind])
    monkeypatch.setattr(stages, "_load_module", lambda *_args, **_kwargs: Compiler)
    adapter = SimpleNamespace(prompt_skill_files={"seedance-20": tmp_path / "seedance.md"})

    SeedancePromptStage(
        invocation_adapter=adapter,
        uploaded_song_transcriber=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("lyrics must be transcribed before script confirmation, never during prompt compilation")
        ),
    ).run(context=context, input_artifacts=[])

    assert captured["performance_lines"] == []
    assert "confirmed non-song replacement" in captured["segment"]["shots"][0]["audio"]


def test_seedance_prompt_blocks_an_mv_song_when_performer_assignment_is_not_confirmed(monkeypatch, tmp_path: Path) -> None:
    from server.packaged_stages import SeedancePromptStage
    from server.errors import ReplicationError
    import server.packaged_stages as stages

    context, artifacts, _performance_line = _verified_uploaded_song_prompt_context(tmp_path)
    artifacts["performance_line_contract"]["cuts"][0]["speaker_assignment"] = {
        "status": "PENDING_ASSIGNMENT", "speaker_id": "CHARACTER_A"
    }
    compiler_calls: list[dict[str, object]] = []

    class Compiler:
        @staticmethod
        def compile_prompt(**kwargs):
            compiler_calls.append(kwargs)
            return {"prompt": "Use @Audio1 only as approved background music; do not invent singing."}

    monkeypatch.setattr(stages, "_read_json_artifact", lambda _context, *, kind, **_kwargs: artifacts[kind])
    monkeypatch.setattr(stages, "_load_module", lambda *_args, **_kwargs: Compiler)
    adapter = SimpleNamespace(prompt_skill_files={"seedance-20": tmp_path / "seedance.md"})

    with pytest.raises(ReplicationError, match="source-verified performer and timing contract"):
        SeedancePromptStage(
            invocation_adapter=adapter,
            uploaded_song_transcriber=lambda *_args, **_kwargs: [
                {"start": 0.0, "end": 3.0, "text": "changed lyrics"}
            ],
        ).run(context=context, input_artifacts=[])

    assert compiler_calls == []


def test_seedance_prompt_ignores_uploaded_song_lyric_text_and_keeps_audio_driven_routing(monkeypatch, tmp_path: Path) -> None:
    from server.packaged_stages import SeedancePromptStage
    from server.errors import ReplicationError
    import server.packaged_stages as stages

    context, artifacts, _performance_line = _verified_uploaded_song_prompt_context(tmp_path)
    compiler_calls: list[dict[str, object]] = []

    class Compiler:
        @staticmethod
        def compile_prompt(**kwargs):
            compiler_calls.append(kwargs)
            return {"prompt": "Use @Audio1 only as approved background music."}

    monkeypatch.setattr(stages, "_read_json_artifact", lambda _context, *, kind, **_kwargs: artifacts[kind])
    monkeypatch.setattr(stages, "_load_module", lambda *_args, **_kwargs: Compiler)
    artifacts["uploaded_audio_classification"]["lyrics"] = [
        {"start_ms": 0, "end_ms": 3999, "text": "I will meet you by a different lake"}
    ]

    adapter = SimpleNamespace(prompt_skill_files={"seedance-20": tmp_path / "seedance.md"})
    SeedancePromptStage(invocation_adapter=adapter).run(context=context, input_artifacts=[])

    assert len(compiler_calls) == 1
    assert compiler_calls[0]["performance_lines"] == []


def test_seedance_prompt_blocks_an_uploaded_song_when_no_generated_segment_intersects_the_confirmed_singing_window(monkeypatch, tmp_path: Path) -> None:
    from server.packaged_stages import SeedancePromptStage
    from server.errors import ReplicationError
    import server.packaged_stages as stages

    context, artifacts, _performance_line = _verified_uploaded_song_prompt_context(tmp_path)
    artifacts["segment_plan"] = {
        "segments": [{"segment_id": "S01", "cut_ids": ["C01"], "start_ms": 5000, "end_ms": 9000, "duration_ms": 4000}]
    }
    compiler_calls: list[dict[str, object]] = []

    class Compiler:
        @staticmethod
        def compile_prompt(**kwargs):
            compiler_calls.append(kwargs)
            return {"prompt": "Use @Audio1 only as approved background music."}

    monkeypatch.setattr(stages, "_read_json_artifact", lambda _context, *, kind, **_kwargs: artifacts[kind])
    monkeypatch.setattr(stages, "_load_module", lambda *_args, **_kwargs: Compiler)
    adapter = SimpleNamespace(prompt_skill_files={"seedance-20": tmp_path / "seedance.md"})
    with pytest.raises(ReplicationError, match="source-verified performer and timing contract"):
        SeedancePromptStage(
            invocation_adapter=adapter,
            uploaded_song_transcriber=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("non-overlapping song must not be transcribed")
            ),
        ).run(context=context, input_artifacts=[])

    assert compiler_calls == []


def test_segment_plan_publication_keeps_the_exact_canonical_json_in_artifact_metadata() -> None:
    from server.packaged_stages import _canonical, _publish_json

    observed = {}

    class Context:
        def publish_bytes(self, **kwargs):
            observed.update(kwargs)
            return kwargs

    plan = {"segments": [{"segment_id": "S01", "cut_ids": ["C01"]}]}
    _publish_json(Context(), kind="segment_plan", value=plan, metadata={"canonical_json": _canonical(plan).decode("utf-8")})

    assert observed["metadata"] == {"canonical_json": _canonical(plan).decode("utf-8")}


@pytest.mark.parametrize(
    ("audio_kind", "audio_plan_overrides", "output_language", "dialogue_change", "prompt_markers"),
    [
        (
            "background_music",
            {"background_music_strategy": "replace_uploaded_background_music", "mv_lip_sync_route": "none"},
            None,
            None,
            ("@Audio1",),
        ),
        (
            "voiceover",
            {"background_music_strategy": "replace_uploaded_voiceover", "mv_lip_sync_route": "none", "voiceover_route": "seedance_audio_reference"},
            None,
            {"change_id": "D01", "kind": "dialogue", "start_ms": 1000, "end_ms": 2000, "speaker": "PersonA", "text": "Approved voiceover line."},
            ("Approved voiceover line.",),
        ),
    ],
    ids=["background-music", "voiceover"],
)
def test_v2_non_song_audio_routes_use_explicit_seedance_audio_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    audio_kind: str,
    audio_plan_overrides: dict[str, str],
    output_language: str | None,
    dialogue_change: dict[str, object] | None,
    prompt_markers: tuple[str, ...],
) -> None:
    """RED: BGM and uploaded voiceover need distinct v2 Prompt/Audit contracts."""

    from server.errors import ReplicationError
    from test_v2_packaged_stage_ports import _make_v2_song_mv_case

    case = _make_v2_song_mv_case(
        monkeypatch,
        tmp_path,
        protection_windows=[],
        audio_kind=audio_kind,
        audio_plan_overrides=audio_plan_overrides,
        output_language=output_language,
        dialogue_change=dialogue_change,
    )
    names = {str(item["name"]) for item in case.plan}
    forbidden = {"run_song_lip_sync", "run_tts", "run_final_lip_sync", "replace_voiceover_audio"}
    failures = [f"forbidden audio stage scheduled: {name}" for name in sorted(names & forbidden)]

    prompt_result = case.ports["stage_ports"]["compile_seedance20_prompt"].run(
        context=case.context, input_artifacts=[]
    )
    prompt = prompt_result["seedance_input_contract"]["segments"][0]["compiled_prompt"]["prompt"]
    failures.extend(f"prompt missing {marker!r}" for marker in prompt_markers if marker not in prompt)

    try:
        audit_result = case.ports["stage_ports"]["audit_seedance_request"].run(
            context=case.context, input_artifacts=[]
        )
    except ReplicationError as exc:
        failures.append(f"AuditStage rejected the explicit {audio_kind} route before provider payload: {exc.code}")
    else:
        payload = audit_result["seedance_request_audit"]["segments"][0]["payload_template"]
        if len(payload.get("audioUrls") or []) != 1:
            failures.append("Seedance payload must carry exactly the current BGM/voiceover audio reference")
        reference = audit_result["seedance_request_audit"]["segments"][0].get("audio_reference_binding") or {}
        if reference.get("source_audio_sha256") != case.song_sha:
            failures.append("audio reference is not bound to the current upload SHA")
        if reference.get("audio_kind") != audio_kind:
            failures.append("audio reference does not preserve the explicit uploaded classification")
        preservation = audit_result["seedance_request_audit"]["segments"][0].get("audio_preservation") or {}
        if preservation != {"source_speech": "preserve", "source_ambience": "preserve"}:
            failures.append("audit receipt is missing source speech/ambience preservation")

    assert not failures, "\n".join(failures)


def test_v2_voiceover_without_role_and_dialogue_window_fails_before_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RED: a custom voiceover cannot fall through to an unbound audio route."""

    from server.errors import ReplicationError
    from test_v2_packaged_stage_ports import _make_v2_song_mv_case

    case = _make_v2_song_mv_case(
        monkeypatch,
        tmp_path,
        protection_windows=[],
        audio_kind="voiceover",
        audio_plan_overrides={
            "background_music_strategy": "replace_uploaded_voiceover",
            "mv_lip_sync_route": "none",
            "voiceover_route": "seedance_audio_reference",
        },
    )
    forbidden = {"run_song_lip_sync", "run_tts", "run_final_lip_sync", "replace_voiceover_audio"}
    assert not forbidden.intersection(str(item["name"]) for item in case.plan)
    with pytest.raises(ReplicationError) as exc_info:
        case.ports["stage_ports"]["compile_seedance20_prompt"].run(
            context=case.context, input_artifacts=[]
        )
    assert exc_info.value.code == "CONTRACT_INVALID"
    assert not any(provider.requests for provider in case.ports["stage_ports"].values() if hasattr(provider, "requests"))


def test_v2_voiceover_upload_stays_materialized_until_seedance_upload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RED: a voiceover upload path must remain live through media upload."""

    import shutil

    from test_v2_packaged_stage_ports import _make_v2_song_mv_case

    case = _make_v2_song_mv_case(
        monkeypatch,
        tmp_path,
        protection_windows=[],
        audio_kind="voiceover",
        audio_plan_overrides={
            "background_music_strategy": "replace_uploaded_voiceover",
            "mv_lip_sync_route": "none",
            "voiceover_route": "seedance_audio_reference",
        },
        dialogue_change={
            "change_id": "D01",
            "kind": "dialogue",
            "start_ms": 1000,
            "end_ms": 2000,
            "speaker": "PersonA",
            "text": "Approved voiceover line.",
        },
    )

    @contextmanager
    def ephemeral_materializer(extension_id: str, *, index: int = 0):
        assert (extension_id, index) == ("background_music", 0)
        materialized = tmp_path / "ephemeral-voiceover.wav"
        shutil.copyfile(case.song, materialized)
        try:
            yield SimpleNamespace(path=materialized, sha256=case.song_sha)
        finally:
            materialized.unlink(missing_ok=True)

    case.context.materialize_extension = ephemeral_materializer

    def upload_requires_live_path(self, path: Path) -> str:
        assert Path(path).is_file()
        self.uploaded.append(Path(path))
        return f"https://media.example.test/{Path(path).name}"

    monkeypatch.setattr(case.uploader, "upload_media", upload_requires_live_path)
    case.ports["stage_ports"]["compile_seedance20_prompt"].run(
        context=case.context, input_artifacts=[]
    )
    case.ports["stage_ports"]["audit_seedance_request"].run(
        context=case.context, input_artifacts=[]
    )


def test_v2_voiceover_audio_reference_is_segment_local(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RED: only segments containing approved voiceover changes may reference @Audio1."""

    from test_v2_packaged_stage_ports import _make_v2_song_mv_case

    case = _make_v2_song_mv_case(
        monkeypatch,
        tmp_path,
        protection_windows=[],
        audio_kind="voiceover",
        audio_plan_overrides={
            "background_music_strategy": "replace_uploaded_voiceover",
            "mv_lip_sync_route": "none",
            "voiceover_route": "seedance_audio_reference",
        },
        dialogue_change={
            "change_id": "D01",
            "kind": "dialogue",
            "start_ms": 1000,
            "end_ms": 2000,
            "speaker": "PersonA",
            "text": "First segment only.",
        },
        segment_specs=[
            {"segment_id": "S01", "cut_ids": ["C01"], "start_ms": 0, "end_ms": 8000},
            {"segment_id": "S02", "cut_ids": ["C02"], "start_ms": 8000, "end_ms": 16000},
        ],
    )
    prompt = case.ports["stage_ports"]["compile_seedance20_prompt"].run(
        context=case.context, input_artifacts=[]
    )
    prompt_segments = prompt["seedance_input_contract"]["segments"]
    assert len(prompt_segments) == 2
    assert "@Audio1" in prompt_segments[0]["compiled_prompt"]["prompt"]
    assert "PersonA" in prompt_segments[0]["compiled_prompt"]["prompt"]
    assert "@Audio1" not in prompt_segments[1]["compiled_prompt"]["prompt"]
    audit = case.ports["stage_ports"]["audit_seedance_request"].run(
        context=case.context, input_artifacts=[]
    )
    payloads = [row["payload_template"] for row in audit["seedance_request_audit"]["segments"]]
    assert [len(payload.get("audioUrls") or []) for payload in payloads] == [1, 0]


@pytest.mark.parametrize(
    ("audio_kind", "audio_plan_overrides"),
    [
        ("background_music", {"background_music_strategy": "replace_uploaded_voiceover", "mv_lip_sync_route": "none"}),
        ("voiceover", {"background_music_strategy": "replace_uploaded_background_music", "mv_lip_sync_route": "none", "voiceover_route": "seedance_audio_reference"}),
        ("voiceover", {"background_music_strategy": "replace_uploaded_voiceover", "mv_lip_sync_route": "none", "voiceover_route": "legacy_tts"}),
        ("song", {"background_music_strategy": "replace_uploaded_background_music", "mv_lip_sync_route": "song_lipsync"}),
    ],
    ids=["bgm-poison-voiceover", "voiceover-poison-bgm", "voiceover-poison-legacy-route", "song-poison-bgm"],
)
def test_v2_audio_kind_and_approved_plan_must_match_before_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    audio_kind: str,
    audio_plan_overrides: dict[str, str],
) -> None:
    """RED: explicit classification cannot silently accept a contradictory approved route."""

    from server.errors import ReplicationError
    from test_v2_packaged_stage_ports import _make_v2_song_mv_case

    case = _make_v2_song_mv_case(
        monkeypatch,
        tmp_path,
        protection_windows=[],
        audio_kind=audio_kind,
        audio_plan_overrides=audio_plan_overrides,
        dialogue_change=(
            {
                "change_id": "D01",
                "kind": "dialogue",
                "start_ms": 1000,
                "end_ms": 2000,
                "speaker": "PersonA",
                "text": "Approved voiceover line.",
            }
            if audio_kind == "voiceover"
            else None
        ),
    )
    with pytest.raises(ReplicationError) as exc_info:
        case.ports["stage_ports"]["compile_seedance20_prompt"].run(
            context=case.context, input_artifacts=[]
        )
    assert exc_info.value.code == "CONTRACT_INVALID"
    assert exc_info.value.category == "audio"

