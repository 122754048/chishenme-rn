from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import fakeredis
import pytest
from PIL import Image

from server.cleanup import CleanupSweeper
from server.ephemeral_driver import EphemeralStageDriver
from server.ephemeral_service import ReplicationService
from server.ephemeral_worker import EphemeralWorkerManager
from server.job_models import WorkMessage
from server.object_store import FinalVideoStore, S3ObjectStore, TemporaryMediaStore
from server.redis_job_store import RedisEphemeralJobStore
from server.review_models import RevisionManifest

from test_object_lifecycle import MemoryS3


FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def _run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def _clip(path: Path, *, color: str, frequency: int, duration: float) -> None:
    _run([
        FFMPEG, "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"color=c={color}:s=180x320:r=30:d={duration}",
        "-f", "lavfi", "-i", f"sine=frequency={frequency}:sample_rate=48000:duration={duration}",
        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path),
    ])


def _probe(path: Path) -> dict:
    result = subprocess.run(
        [FFPROBE, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


class JsonStage:
    def __init__(self, kind: str) -> None:
        self.kind = kind

    def run(self, *, context, input_artifacts):
        payload = json.dumps({"stage": context.stage, "inputs": len(input_artifacts)}, sort_keys=True).encode()
        artifact = context.publish_bytes(
            kind=self.kind,
            data=payload,
            content_type="application/json",
            expected_sha256=hashlib.sha256(payload).hexdigest(),
        )
        return {"published_artifacts": [artifact]}


class ScriptStage:
    def run(self, *, context, input_artifacts):
        del input_artifacts
        payload = json.dumps({"cuts": [{"cut_id": "c1", "dialogue": "Try the new app"}]}, sort_keys=True).encode()
        artifact = context.publish_bytes(kind="script_revision", data=payload, content_type="application/json", expected_sha256=hashlib.sha256(payload).hexdigest())
        return {
            "script_revision": RevisionManifest(
                kind="script", revision=1, object_key=artifact["object_key"], sha256=artifact["sha256"],
                inputs_sha256="1" * 64, created_at=datetime.now(timezone.utc).isoformat(), output_language="en",
            )
        }


class StoryboardStage:
    def run(self, *, context, input_artifacts):
        del input_artifacts
        image_path = context.work_dir / "storyboard.png"
        Image.new("RGB", (180, 320), (32, 180, 96)).save(image_path)
        payload = image_path.read_bytes()
        artifact = context.publish_bytes(kind="storyboard_grid", data=payload, content_type="image/png", expected_sha256=hashlib.sha256(payload).hexdigest())
        return {
            "storyboard_revision": RevisionManifest(
                kind="storyboard", revision=1, object_key=artifact["object_key"], sha256=artifact["sha256"],
                inputs_sha256="2" * 64, created_at=datetime.now(timezone.utc).isoformat(),
                parent_script_sha256=context.snapshot.approved_script_sha256,
            )
        }


class ProviderStage:
    def __init__(self, generated: Path) -> None:
        self.generated = generated

    def run(self, *, context, input_artifacts):
        del input_artifacts
        payload = self.generated.read_bytes()
        artifact = context.publish_bytes(kind="provider_video", data=payload, content_type="video/mp4", expected_sha256=hashlib.sha256(payload).hexdigest())
        return {"published_artifacts": [artifact]}


class SpliceStage:
    def run(self, *, context, input_artifacts):
        del input_artifacts
        with context.materialize_artifact("provider_video") as generated, context.materialize_slot("ui_operation_video") as ui, context.materialize_slot("tail_video") as tail:
            output = context.work_dir / "assembled.mp4"
            d0 = float(_probe(generated.path)["format"]["duration"])
            d1 = float(_probe(ui.path)["format"]["duration"])
            overlap = 0.10
            filter_graph = (
                "[0:v]fps=30,scale=180:320,setsar=1,settb=AVTB,setpts=PTS-STARTPTS[v0];"
                "[1:v]fps=30,scale=180:320,setsar=1,settb=AVTB,setpts=PTS-STARTPTS[v1];"
                "[2:v]fps=30,scale=180:320,setsar=1,settb=AVTB,setpts=PTS-STARTPTS[v2];"
                f"[v0][v1]xfade=transition=fade:duration={overlap}:offset={d0-overlap}[v01];"
                f"[v01][v2]xfade=transition=fade:duration={overlap}:offset={d0+d1-2*overlap}[v];"
                "[0:a]aresample=48000,asetpts=PTS-STARTPTS[a0];"
                "[1:a]aresample=48000,asetpts=PTS-STARTPTS[a1];"
                "[2:a]aresample=48000,asetpts=PTS-STARTPTS[a2];"
                f"[a0][a1]acrossfade=d={overlap}:c1=tri:c2=tri[a01];"
                f"[a01][a2]acrossfade=d={overlap}:c1=tri:c2=tri[a]"
            )
            _run([
                FFMPEG, "-y", "-loglevel", "error", "-i", str(generated.path), "-i", str(ui.path), "-i", str(tail.path),
                "-filter_complex", filter_graph, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "18",
                "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(output),
            ])
            payload = output.read_bytes()
        artifact = context.publish_bytes(kind="assembled_video", data=payload, content_type="video/mp4", expected_sha256=hashlib.sha256(payload).hexdigest())
        return {"published_artifacts": [artifact]}


class QcStage:
    def run(self, *, context, input_artifacts):
        del input_artifacts
        artifacts = [item for item in context.job_store.list_artifacts(context.job_id) if item.kind == "assembled_video"]
        assert len(artifacts) == 1
        with context.materialize_artifact("assembled_video") as media:
            probe = _probe(media.path)
            stream_types = {stream["codec_type"] for stream in probe["streams"]}
            assert stream_types == {"video", "audio"}
            duration = float(probe["format"]["duration"])
            assert 3.0 < duration < 3.4
            scan = subprocess.run(
                [FFMPEG, "-hide_banner", "-i", str(media.path), "-vf", "blackdetect=d=0.02:pix_th=0.10", "-an", "-f", "null", "-"],
                capture_output=True,
                text=True,
            )
            assert scan.returncode == 0
            assert "black_start" not in scan.stderr
        report = json.dumps({"passed": True, "duration": duration, "black_intervals": []}, sort_keys=True).encode()
        context.publish_bytes(kind="qc_report", data=report, content_type="application/json", expected_sha256=hashlib.sha256(report).hexdigest())
        return {"qc_passed": True, "final_artifact_id": artifacts[0].artifact_id}


def _process_next(driver, manager, store, job_id: str) -> str | None:
    message = driver.enqueue_next(job_id)
    if message is None:
        return None
    checkpoint = store.claim_stage(job_id=job_id, stage=message.stage, dedupe_key=message.dedupe_key, owner="e2e-worker", ttl_seconds=60)
    result = manager.process_work_message(message=message, checkpoint=checkpoint, owner="e2e-worker")
    store.complete_stage(
        job_id=job_id, stage=message.stage, dedupe_key=message.dedupe_key, owner="e2e-worker",
        output_artifact_ids=result["output_artifact_ids"], ttl_seconds=3600,
    )
    return message.stage


@pytest.mark.skipif(FFMPEG is None or FFPROBE is None, reason="FFmpeg runtime is required")
def test_full_inprocess_video_job_two_approvals_natural_ui_tail_and_final_only(tmp_path: Path) -> None:
    source, ui, tail, generated = (tmp_path / name for name in ("source.mp4", "ui.mp4", "tail.mp4", "generated.mp4"))
    _clip(source, color="red", frequency=440, duration=1.5)
    _clip(ui, color="blue", frequency=660, duration=1.1)
    _clip(tail, color="yellow", frequency=880, duration=0.7)
    _clip(generated, color="green", frequency=550, duration=1.5)

    redis = fakeredis.FakeRedis(decode_responses=False)
    store = RedisEphemeralJobStore(redis, prefix="video-e2e")
    client = MemoryS3()
    object_store = S3ObjectStore(client, bucket="test")
    temporary = TemporaryMediaStore(object_store)
    final = FinalVideoStore(object_store)
    job = store.create_job(
        slots_manifest={"slots": {}, "routes": {"product": "replace_from_slot", "ui": "opaque_ui_demo", "tail": "opaque_app_tail_card"}, "review_route": "route_2"},
        capability_token_hash="a" * 64,
        ttl_seconds=3600,
    )
    refs = {
        "source_video": temporary.put_bytes(job_id=job.job_id, logical_path="inputs/source.mp4", data=source.read_bytes(), content_type="video/mp4"),
        "ui_operation_video": temporary.put_bytes(job_id=job.job_id, logical_path="inputs/ui.mp4", data=ui.read_bytes(), content_type="video/mp4"),
        "tail_video": temporary.put_bytes(job_id=job.job_id, logical_path="inputs/tail.mp4", data=tail.read_bytes(), content_type="video/mp4"),
    }
    slots = {
        name: {"present": True, "values": [ref.object_key], "metadata": [{"object_key": ref.object_key, "sha256": ref.sha256, "size_bytes": ref.size_bytes}]}
        for name, ref in refs.items()
    }
    job = store.cas_transition(
        job_id=job.job_id, expected_version=job.version, command="bind_e2e_inputs",
        updates={"slots_manifest": {"slots": slots, "routes": {"product": "replace_from_slot", "ui": "opaque_ui_demo", "tail": "opaque_app_tail_card"}, "review_route": "route_2"}, "review_route": "route_2", "state": "ANALYZING"},
        ttl_seconds=3600,
    )
    queue = SimpleNamespace(enqueue=lambda **kwargs: WorkMessage(**kwargs))
    driver = EphemeralStageDriver(store, queue)
    stages = {
        "bind_inputs": JsonStage("input_binding"), "probe_source": JsonStage("source_probe"),
        "analyze_dynamics": JsonStage("source_dynamics"), "route_regions": JsonStage("timeline_regions"),
        "build_script": ScriptStage(), "generate_storyboards": StoryboardStage(),
        "compile_seedance20_prompt": JsonStage("compiled_prompt"), "audit_seedance_request": JsonStage("request_audit"),
        "submit_provider_video": JsonStage("provider_submit"), "wait_provider_video": ProviderStage(generated),
        "splice_timeline": SpliceStage(), "run_qc": QcStage(),
    }
    manager = EphemeralWorkerManager(
        job_store=store, temporary_store=temporary, final_store=final, stage_ports=stages,
        profile_bundle_resolver=SimpleNamespace(immutable=True), capability_ports={},
        materializer=__import__("server.media_materializer", fromlist=["MediaMaterializer"]).MediaMaterializer(
            SimpleNamespace(
                head=lambda key: {"object_key": key, "sha256": object_store.head(key).sha256, "size_bytes": object_store.head(key).size_bytes, "content_type": object_store.head(key).content_type},
                open_stream=lambda key: client.get_object(Bucket="test", Key=key)["Body"],
            )
        ),
    )
    service = ReplicationService(job_store=store, review_ttl_seconds=3600)

    pre_script = []
    while True:
        stage = _process_next(driver, manager, store, job.job_id)
        if stage is None:
            break
        pre_script.append(stage)
    assert pre_script[-1] == "build_script"
    script = store.get_current_revision(job.job_id, "script")
    current = store.get_job(job.job_id)
    service.approve_script_revision(job.job_id, revision=1, expected_version=current.version, expected_sha256=script.sha256)

    assert _process_next(driver, manager, store, job.job_id) == "generate_storyboards"
    assert _process_next(driver, manager, store, job.job_id) is None
    storyboard = store.get_current_revision(job.job_id, "storyboard")
    current = store.get_job(job.job_id)
    service.approve_storyboard_revision(job.job_id, revision=1, expected_version=current.version, expected_sha256=storyboard.sha256)

    post_storyboard = []
    while True:
        stage = _process_next(driver, manager, store, job.job_id)
        if stage is None:
            break
        post_storyboard.append(stage)
    assert post_storyboard[-1] == "run_qc"
    completed = store.get_job(job.job_id)
    assert completed.state == "SUCCEEDED"
    final_key = f"final/{job.job_id}/result.mp4"
    assert completed.final_ref["object_key"] == final_key
    final_bytes = client.objects[final_key]["body"]
    final_path = tmp_path / "result.mp4"
    final_path.write_bytes(final_bytes)
    final_probe = _probe(final_path)
    assert {stream["codec_type"] for stream in final_probe["streams"]} == {"video", "audio"}
    assert 3.0 < float(final_probe["format"]["duration"]) < 3.4
    evidence_output = (os.getenv("USFR_INPROCESS_E2E_OUTPUT", "") or "").strip()
    if evidence_output:
        evidence_path = Path(evidence_output)
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_bytes(final_bytes)

    sweeper = CleanupSweeper(redis, temporary, final, prefix="video-e2e")
    assert sweeper.cleanup_job(job.job_id, preserve_final=True) is True
    assert store.get_job(job.job_id) is None
    assert set(client.objects) == {final_key}
