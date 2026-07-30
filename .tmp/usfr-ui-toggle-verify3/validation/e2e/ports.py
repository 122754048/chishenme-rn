"""Deterministic ports for the container control-flow E2E target only.

These adapters prove API/queue/object-store/video plumbing. They are excluded
from the production image and are not model-quality or advertising evidence.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping
from urllib.parse import urlparse

from PIL import Image

from server.capabilities import REQUIRED_CAPABILITIES
from server.capability_ports import REQUIRED_CAPABILITY_METHODS
from server.ephemeral_driver import EXECUTABLE_STAGES
from server.job_models import ArtifactRef
from server.object_store import FinalVideoStore
from server.remote_media_import import OssUrlPolicy, RemoteMediaImporter
from server.review_models import RevisionManifest, StoryboardCutRef


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-2000:])
    return result


def _probe(path: Path) -> dict[str, Any]:
    return json.loads(
        _run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ]
        ).stdout
    )


def _publish_json(context: Any, kind: str, value: Any) -> dict[str, Any]:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return context.publish_bytes(
        kind=kind,
        data=payload,
        content_type="application/json",
        expected_sha256=hashlib.sha256(payload).hexdigest(),
    )


class JsonStage:
    def __init__(self, kind: str) -> None:
        self.kind = kind

    def run(self, *, context: Any, input_artifacts: list[dict[str, Any]]) -> dict[str, Any]:
        artifact = _publish_json(
            context,
            self.kind,
            {"stage": context.stage, "input_artifact_count": len(input_artifacts)},
        )
        return {"published_artifacts": [artifact]}


class ImportSourcesStage:
    """Validation-only HTTPS-OSS facade backed by preloaded MinIO objects."""

    def run(self, *, context: Any, input_artifacts: list[dict[str, Any]]) -> dict[str, Any]:
        del input_artifacts
        intake = context.snapshot.slots_manifest.get("public_intake")
        if not isinstance(intake, Mapping):
            raise RuntimeError("public intake is missing")
        import boto3

        client = boto3.client("s3", endpoint_url=os.getenv("USFR_S3_ENDPOINT"))
        bucket = os.getenv("USFR_S3_BUCKET", "usfr-media")

        def fetch(validated: Any, destination: Path, max_bytes: int) -> None:
            key = urlparse(validated.url).path.lstrip("/")
            response = client.get_object(Bucket=bucket, Key=key)
            size = 0
            with destination.open("wb") as output:
                while True:
                    chunk = response["Body"].read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        raise RuntimeError("validation source exceeds import limit")
                    output.write(chunk)
            response["Body"].close()

        importer = RemoteMediaImporter(
            object_store=context.temporary_store.object_store,
            policy=OssUrlPolicy(("e2e-oss.example",), resolver=lambda _host: ("8.8.8.8",)),
            fetcher=fetch,
        )
        manifest = importer.import_request(
            job_id=context.job_id,
            request=intake,
            work_dir=context.work_dir,
        )
        return {"slots_manifest": manifest}


class ScriptStage:
    def run(self, *, context: Any, input_artifacts: list[dict[str, Any]]) -> dict[str, Any]:
        del input_artifacts
        artifact = _publish_json(
            context,
            "script_revision",
            {"cuts": [{"cut_id": "c1", "dialogue": "Try the app today"}]},
        )
        return {
            "script_revision": RevisionManifest(
                kind="script",
                revision=1,
                object_key=artifact["object_key"],
                sha256=artifact["sha256"],
                inputs_sha256="1" * 64,
                created_at=datetime.now(UTC).isoformat(),
                output_language=str(context.snapshot.slots_manifest.get("output_language") or "en"),
            )
        }


class StoryboardStage:
    def run(self, *, context: Any, input_artifacts: list[dict[str, Any]]) -> dict[str, Any]:
        del input_artifacts
        image_buffer = io.BytesIO()
        Image.new("RGB", (180, 320), "#1f6feb").save(image_buffer, format="PNG")
        image_payload = image_buffer.getvalue()
        cut_image = context.publish_bytes(
            kind="storyboard_cut",
            data=image_payload,
            content_type="image/png",
            expected_sha256=hashlib.sha256(image_payload).hexdigest(),
        )
        artifact = _publish_json(
            context,
            "storyboard_revision",
            {"cuts": [{"cut_id": "c1", "object_key": cut_image["object_key"]}]},
        )
        return {
            "storyboard_revision": RevisionManifest(
                kind="storyboard",
                revision=1,
                object_key=artifact["object_key"],
                sha256=artifact["sha256"],
                inputs_sha256="2" * 64,
                created_at=datetime.now(UTC).isoformat(),
                parent_script_sha256=context.snapshot.approved_script_sha256,
                cut_images=(
                    StoryboardCutRef(
                        cut_id="c1",
                        object_key=cut_image["object_key"],
                        sha256=cut_image["sha256"],
                        width=180,
                        height=320,
                    ),
                ),
            )
        }


class ProviderVideoStage:
    def run(self, *, context: Any, input_artifacts: list[dict[str, Any]]) -> dict[str, Any]:
        del input_artifacts
        output = context.work_dir / "generated.mp4"
        _run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=green:s=180x320:r=30:d=0.9",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=550:sample_rate=48000:duration=0.9",
                "-shortest",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(output),
            ]
        )
        payload = output.read_bytes()
        artifact = context.publish_bytes(
            kind="provider_video",
            data=payload,
            content_type="video/mp4",
            expected_sha256=hashlib.sha256(payload).hexdigest(),
        )
        return {"published_artifacts": [artifact]}


class SpliceStage:
    def run(self, *, context: Any, input_artifacts: list[dict[str, Any]]) -> dict[str, Any]:
        del input_artifacts
        with (
            context.materialize_artifact("provider_video") as generated,
            context.materialize_slot("ui_operation_video") as ui,
            context.materialize_slot("tail_video") as tail,
        ):
            output = context.work_dir / "assembled.mp4"
            generated_duration = float(_probe(generated.path)["format"]["duration"])
            ui_duration = float(_probe(ui.path)["format"]["duration"])
            overlap = 0.08
            graph = (
                "[0:v]fps=30,scale=180:320,setsar=1,settb=AVTB,setpts=PTS-STARTPTS[v0];"
                "[1:v]fps=30,scale=180:320,setsar=1,settb=AVTB,setpts=PTS-STARTPTS[v1];"
                "[2:v]fps=30,scale=180:320,setsar=1,settb=AVTB,setpts=PTS-STARTPTS[v2];"
                f"[v0][v1]xfade=transition=fade:duration={overlap}:offset={generated_duration-overlap}[v01];"
                f"[v01][v2]xfade=transition=fade:duration={overlap}:offset={generated_duration+ui_duration-2*overlap}[v];"
                "[0:a]aresample=48000,asetpts=PTS-STARTPTS[a0];"
                "[1:a]aresample=48000,asetpts=PTS-STARTPTS[a1];"
                "[2:a]aresample=48000,asetpts=PTS-STARTPTS[a2];"
                f"[a0][a1]acrossfade=d={overlap}:c1=tri:c2=tri[a01];"
                f"[a01][a2]acrossfade=d={overlap}:c1=tri:c2=tri[a]"
            )
            _run(
                [
                    "ffmpeg",
                    "-y",
                    "-loglevel",
                    "error",
                    "-i",
                    str(generated.path),
                    "-i",
                    str(ui.path),
                    "-i",
                    str(tail.path),
                    "-filter_complex",
                    graph,
                    "-map",
                    "[v]",
                    "-map",
                    "[a]",
                    "-c:v",
                    "libx264",
                    "-crf",
                    "18",
                    "-preset",
                    "veryfast",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-movflags",
                    "+faststart",
                    str(output),
                ]
            )
            payload = output.read_bytes()
        artifact = context.publish_bytes(
            kind="assembled_video",
            data=payload,
            content_type="video/mp4",
            expected_sha256=hashlib.sha256(payload).hexdigest(),
        )
        return {"published_artifacts": [artifact]}


class QcStage:
    def run(self, *, context: Any, input_artifacts: list[dict[str, Any]]) -> dict[str, Any]:
        del input_artifacts
        artifacts = [
            item
            for item in context.job_store.list_artifacts(context.job_id)
            if item.kind == "assembled_video"
        ]
        if len(artifacts) != 1:
            raise RuntimeError("container E2E expected one assembled video")
        with context.materialize_artifact("assembled_video") as media:
            probe = _probe(media.path)
            if {stream["codec_type"] for stream in probe["streams"]} != {"video", "audio"}:
                raise RuntimeError("container E2E output must contain video and audio")
            duration = float(probe["format"]["duration"])
            scan = _run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-i",
                    str(media.path),
                    "-vf",
                    "blackdetect=d=0.02:pix_th=0.10",
                    "-an",
                    "-f",
                    "null",
                    "-",
                ]
            )
            if "black_start" in scan.stderr:
                raise RuntimeError("container E2E output contains a black interval")
        _publish_json(
            context,
            "qc_report",
            {"passed": True, "duration_seconds": duration, "black_intervals": []},
        )
        return {"qc_passed": True, "final_artifact_id": artifacts[0].artifact_id}


class CapabilityPort:
    def __init__(self, name: str) -> None:
        self.name = name
        self.sha256 = hashlib.sha256(f"usfr-container-e2e:{name}".encode()).hexdigest()

    def capability_identity(self) -> dict[str, str]:
        return {
            "capability": self.name,
            "implementation": f"validation.e2e.ports:{self.name}",
            "version": "1",
            "sha256": self.sha256,
        }

    def _result(self, operation: str) -> dict[str, Any]:
        return {"status": "ready", "operation": operation, "e2e_only": True}

    def analyze(self, **_: Any) -> dict[str, Any]:
        return self._result("analyze")

    def transcribe(self, **_: Any) -> dict[str, Any]:
        return self._result("transcribe")

    def render_and_verify(self, **_: Any) -> dict[str, Any]:
        return self._result("render_and_verify")

    def invoke_a(self, **_: Any) -> dict[str, Any]:
        return self._result("invoke_a")

    def invoke_b(self, **_: Any) -> dict[str, Any]:
        return self._result("invoke_b")

    def compose(self, **_: Any) -> dict[str, Any]:
        return self._result("compose")

    def run(self, **_: Any) -> dict[str, Any]:
        return self._result("run")

    def create_asset(self, **_: Any) -> dict[str, Any]:
        return self._result("create_asset")

    def create_video(self, **_: Any) -> dict[str, Any]:
        return self._result("create_video")

    def lookup(self, **_: Any) -> dict[str, Any]:
        return self._result("lookup")


class ValidationPublicFinalStore:
    """MinIO-backed public-result adapter used only by the container E2E image."""

    def __init__(self, *, internal_store: Any, bucket: str) -> None:
        self.delegate = FinalVideoStore(internal_store)
        self.bucket = bucket
        self.public_base_url = os.getenv(
            "USFR_E2E_PUBLIC_OBJECT_BASE",
            "http://minio:9000",
        ).rstrip("/")

    def promote(self, *, job_id: str, source: ArtifactRef) -> ArtifactRef:
        promoted = self.delegate.promote(job_id=job_id, source=source)
        public_url = f"{self.public_base_url}/{self.bucket}/{promoted.object_key}"
        return replace(
            promoted,
            metadata={"public_url": public_url, "storage": "validation_minio"},
        )

    def has_final(self, job_id: str) -> bool:
        try:
            self.delegate.object_store.head(self.delegate._key(job_id))
            return True
        except Exception:
            return False

    def validate_final_ref(self, job_id: str, ref: Mapping[str, Any] | ArtifactRef) -> bool:
        value = ref if isinstance(ref, ArtifactRef) else ArtifactRef(**dict(ref))
        if value.object_key != self.delegate._key(job_id) or not self.delegate.exists(value):
            raise RuntimeError("validation final reference mismatch")
        return True

    def delete_job(self, job_id: str, *, preserve_result: bool = False) -> int:
        return self.delegate.delete_job(job_id, preserve_result=preserve_result)


def build_validation_final_store(*, internal_store: Any, bucket: str, **_: Any) -> ValidationPublicFinalStore:
    return ValidationPublicFinalStore(internal_store=internal_store, bucket=bucket)


def build_ports() -> dict[str, dict[str, Any]]:
    stage_ports: dict[str, Any] = {
        stage: JsonStage(f"{stage}_evidence") for stage in EXECUTABLE_STAGES
    }
    stage_ports.update(
        {
            "import_sources": ImportSourcesStage(),
            "build_script": ScriptStage(),
            "generate_storyboards": StoryboardStage(),
            "wait_provider_video": ProviderVideoStage(),
            "splice_timeline": SpliceStage(),
            "run_qc": QcStage(),
        }
    )
    capability_ports = {name: CapabilityPort(name) for name in REQUIRED_CAPABILITIES}
    for name, methods in REQUIRED_CAPABILITY_METHODS.items():
        if any(not callable(getattr(capability_ports[name], method, None)) for method in methods):
            raise RuntimeError(f"incomplete E2E capability port: {name}")
    return {
        "stage_ports": stage_ports,
        "capability_ports": capability_ports,
        "final_store_factory": build_validation_final_store,
    }


__all__ = ["build_ports"]
