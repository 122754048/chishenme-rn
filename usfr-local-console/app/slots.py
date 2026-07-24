from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


FIXED_SLOT_IDS = (
    "source_video",
    "new_product_image",
    "new_model_image",
    "ui_screenshot",
    "app_store_url",
    "ui_operation_video",
    "tail_video",
)
FILE_SLOT_IDS = (
    "source_video",
    "new_product_image",
    "new_model_image",
    "ui_screenshot",
    "ui_operation_video",
    "tail_video",
)
OPTIONAL_SLOT_IDS = FIXED_SLOT_IDS[1:]
EXTENSION_FILE_IDS = ("background_music",)
OUTPUT_LANGUAGES = ("en", "ja", "ko", "fr", "de", "es", "pt", "id", "zh")
OPAQUE_AUDIO_POLICIES = (
    "opaque_audio_keep",
    "opaque_audio_mute_with_localized_voiceover",
    "opaque_audio_target_verified",
    "opaque_audio_deep_localize",
)


class IntakeError(ValueError):
    pass


@dataclass(frozen=True)
class Intake:
    source_video: Path
    optional_files: dict[str, Path]
    extension_files: dict[str, Path]
    app_store_url: str | None
    output_language: str | None
    opaque_audio_policies: dict[str, str]


@dataclass(frozen=True)
class ValidatedIntake:
    source_video: Path
    optional_files: dict[str, Path]
    extension_files: dict[str, Path]
    app_store_url: str | None
    output_language: str | None
    duration_seconds: float
    admission: dict[str, bool]
    routes: dict[str, str]
    opaque_audio_policies: dict[str, str]


def build_intake(
    *,
    source_video: Path | str,
    new_product_image: Path | str | None = None,
    new_model_image: Path | str | None = None,
    ui_screenshot: Path | str | None = None,
    app_store_url: str | None = None,
    ui_operation_video: Path | str | None = None,
    tail_video: Path | str | None = None,
    background_music: Path | str | None = None,
    output_language: str | None = None,
    opaque_audio_policies: dict[str, str] | None = None,
) -> Intake:
    optional_values = {
        "new_product_image": new_product_image,
        "new_model_image": new_model_image,
        "ui_screenshot": ui_screenshot,
        "ui_operation_video": ui_operation_video,
        "tail_video": tail_video,
    }
    return Intake(
        source_video=Path(source_video),
        optional_files={key: Path(value) for key, value in optional_values.items() if value},
        extension_files={"background_music": Path(background_music)} if background_music else {},
        app_store_url=app_store_url.strip() if app_store_url and app_store_url.strip() else None,
        output_language=output_language.strip().lower() if output_language else None,
        opaque_audio_policies=dict(opaque_audio_policies or {}),
    )


def probe_video_duration(path: Path) -> float:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, check=True, text=True, timeout=20)
        duration = float(json.loads(result.stdout)["format"]["duration"])
    except (FileNotFoundError, subprocess.SubprocessError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise IntakeError("SOURCE_VIDEO_UNREADABLE") from error
    if duration <= 0:
        raise IntakeError("SOURCE_VIDEO_UNREADABLE")
    return duration


def validate_intake(
    intake: Intake, *, probe_duration: Callable[[Path], float] = probe_video_duration
) -> ValidatedIntake:
    if not intake.source_video.is_file():
        raise IntakeError("SOURCE_VIDEO_REQUIRED")
    if intake.output_language and intake.output_language not in OUTPUT_LANGUAGES:
        raise IntakeError("OUTPUT_LANGUAGE_UNSUPPORTED")
    if intake.app_store_url and not intake.app_store_url.startswith(("https://", "http://")):
        raise IntakeError("APP_STORE_URL_INVALID")
    for slot_id, path in intake.optional_files.items():
        if slot_id not in OPTIONAL_SLOT_IDS or not path.is_file():
            raise IntakeError("OPTIONAL_INPUT_INVALID")
    for extension_id, path in intake.extension_files.items():
        if extension_id not in EXTENSION_FILE_IDS or not path.is_file():
            raise IntakeError("OPTIONAL_INPUT_INVALID")
    for region_kind, policy in intake.opaque_audio_policies.items():
        if region_kind not in {"ui", "tail"} or policy not in OPAQUE_AUDIO_POLICIES:
            raise IntakeError("AUDIO_LAYER_POLICY_INVALID")

    has_background_music = "background_music" in intake.extension_files
    has_optional_input = bool(intake.optional_files or intake.app_store_url or intake.extension_files)
    if not has_optional_input and not intake.output_language:
        raise IntakeError("MIN_ONE_OPTIONAL_INPUT_REQUIRED")

    duration_seconds = probe_duration(intake.source_video)
    if duration_seconds > 30:
        raise IntakeError("SOURCE_VIDEO_TOO_LONG")

    language_only = bool(intake.output_language and not has_optional_input)
    routes = {
        "tail_video": "append_user_tail_video" if "tail_video" in intake.optional_files else "omit_source_end_card",
        "ui_operation_video": (
            "replace_source_ui_with_user_video"
            if "ui_operation_video" in intake.optional_files
            else "generated_ui_demo"
        ),
        "semantic": "language_replacement_only" if language_only else "full_replication",
        "background_music": "seedance_audio_reference" if has_background_music else "none",
    }
    return ValidatedIntake(
        source_video=intake.source_video,
        optional_files=intake.optional_files,
        extension_files=intake.extension_files,
        app_store_url=intake.app_store_url,
        output_language=intake.output_language,
        duration_seconds=duration_seconds,
        admission={
            "has_optional_input": has_optional_input,
            "language_only": language_only,
            "background_music": has_background_music,
        },
        routes=routes,
        opaque_audio_policies=intake.opaque_audio_policies,
    )
