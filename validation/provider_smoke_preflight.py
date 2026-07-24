"""Prepare a non-secret, no-network receipt for a real USFR provider smoke."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any


REQUIRED_PROVIDER_CONFIGURATION = (
    "RUNNINGHUB_API_KEY",
    "YOUDAO_API_KEY",
    "YOUDAO_BASE_URL",
)

LOCAL_RUNNINGHUB_SMOKE_CONTRACT = {
    "upload_url": "https://www.runninghub.ai/openapi/v2/media/upload/binary",
    "query_url": "https://www.runninghub.ai/openapi/v2/query",
    "asr": {"workflow_id": "2080170949061038081", "node_id": "1", "field_name": "video"},
    "tts": {
        "workflow_id": "2080177717619118082",
        "audio_node_id": "4",
        "audio_field_name": "audio",
        "prompt_node_id": "11",
        "prompt_field_name": "prompt",
    },
    "lip_sync": {
        "url": "https://www.runninghub.ai/openapi/v2/run/ai-app/2080140197518823426",
        "workflow_id": "2080140197518823426",
        "audio_node_id": "3",
        "audio_field_name": "audio",
        "video_node_id": "6",
        "video_field_name": "video",
    },
}


def build_provider_smoke_preflight(
    *,
    source_video: Path,
    background_music: Path,
    environment: Mapping[str, str],
) -> dict[str, Any]:
    """Return a receipt only; this function never performs provider I/O."""
    source_sha256 = _sha256_file(source_video)
    music_sha256 = _sha256_file(background_music)
    runninghub_contract_sha256 = _canonical_sha256(LOCAL_RUNNINGHUB_SMOKE_CONTRACT)
    missing = [
        name
        for name in REQUIRED_PROVIDER_CONFIGURATION
        if not isinstance(environment.get(name), str) or not environment[name].strip()
    ]
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "environment": "local-real-provider-smoke",
        "provider_tasks_created": 0,
        "input_sha256": {
            "source_video": source_sha256,
            "background_music": music_sha256,
        },
        "runninghub_contract": LOCAL_RUNNINGHUB_SMOKE_CONTRACT,
        "runninghub_contract_sha256": runninghub_contract_sha256,
        "missing_configuration": missing,
        "execution_manifest": [],
    }
    if missing:
        receipt["status"] = "NOT_RUN"
        return receipt

    receipt["status"] = "READY_FOR_EXPLICIT_EXECUTION"
    receipt["execution_manifest"] = _execution_manifest(
        source_video_sha256=source_sha256,
        background_music_sha256=music_sha256,
    )
    return receipt


def load_private_provider_environment(
    *,
    environment: Mapping[str, str] | None = None,
    env_file: Path | None = None,
) -> dict[str, str]:
    """Load only required values without persisting or displaying their contents."""
    source = environment if environment is not None else os.environ
    resolved = {
        name: value
        for name in REQUIRED_PROVIDER_CONFIGURATION
        if isinstance(value := source.get(name), str) and value.strip()
    }
    if env_file is None:
        configured_path = source.get("SEEDANCE_ENV_FILE")
        env_file = Path(configured_path) if configured_path else None
    if env_file is None:
        return resolved
    if not env_file.is_file():
        raise ValueError("SEEDANCE_ENV_FILE_UNREADABLE")

    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        name = name.strip()
        if name in REQUIRED_PROVIDER_CONFIGURATION and value.strip():
            resolved.setdefault(name, value.strip().strip('"').strip("'"))
    return resolved


def _execution_manifest(*, source_video_sha256: str, background_music_sha256: str) -> list[dict[str, Any]]:
    shared = {
        "maximum_create_attempts": 1,
        "ambiguous_outcome_policy": "query_or_reconcile_only",
        "source_video_sha256": source_video_sha256,
        "background_music_sha256": background_music_sha256,
    }
    return [
        {**shared, "step_id": "runninghub_storyboard_image", "provider": "runninghub", "operation": "image2"},
        {**shared, "step_id": "runninghub_asr", "provider": "runninghub", "operation": "asr"},
        {**shared, "step_id": "runninghub_tts", "provider": "runninghub", "operation": "tts"},
        {**shared, "step_id": "runninghub_lip_sync", "provider": "runninghub", "operation": "lip_sync"},
        {
            **shared,
            "step_id": "youdao_audio_asset",
            "provider": "youdao",
            "operation": "create_audio_asset",
            "asset_type": "Audio",
        },
        {
            **shared,
            "step_id": "youdao_seedance_video",
            "provider": "youdao",
            "operation": "create_seedance_video",
            "audio_content_role": "reference_audio",
            "prompt_reference": "@Audio1",
            "forbidden_top_level_fields": ["reference_audios"],
        },
    ]


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise ValueError("SMOKE_INPUT_FILE_REQUIRED")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare a no-network USFR Provider smoke receipt.")
    parser.add_argument("--source-video", type=Path, required=True)
    parser.add_argument("--background-music", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args(argv)
    try:
        environment = load_private_provider_environment(env_file=args.env_file)
        receipt = build_provider_smoke_preflight(
            source_video=args.source_video,
            background_music=args.background_music,
            environment=environment,
        )
    except ValueError as error:
        receipt = {
            "schema_version": 1,
            "environment": "local-real-provider-smoke",
            "status": "NOT_RUN",
            "provider_tasks_created": 0,
            "preflight_error": str(error),
            "execution_manifest": [],
        }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return 0 if receipt["status"] == "READY_FOR_EXPLICIT_EXECUTION" else 2


if __name__ == "__main__":
    raise SystemExit(main())
