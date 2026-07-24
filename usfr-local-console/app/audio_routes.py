from __future__ import annotations

from collections.abc import Mapping, Sequence


OPAQUE_AUDIO_POLICIES = (
    "opaque_audio_keep",
    "opaque_audio_mute_with_localized_voiceover",
    "opaque_audio_target_verified",
    "opaque_audio_deep_localize",
)


class AudioRouteError(ValueError):
    pass


def build_audio_route(
    *,
    execution_map: Mapping[str, object],
    output_language: str | None,
    opaque_policies: Mapping[str, str],
) -> dict[str, object]:
    run_mode = execution_map.get("run_mode")
    if run_mode == "language_only":
        return {
            "mode": "language_only_audio1",
            "audio_reference": "Audio1",
            "regions": [],
            "full_video_lip_sync": True,
        }
    regions = execution_map.get("regions") or []
    if not isinstance(regions, list):
        raise AudioRouteError("AUDIO_ROUTE_INVALID")
    routed_regions: list[dict[str, object]] = []
    for region in regions:
        if not isinstance(region, Mapping):
            raise AudioRouteError("AUDIO_ROUTE_INVALID")
        region_id = region.get("region_id")
        media_origin = region.get("media_origin")
        if not isinstance(region_id, str) or not isinstance(media_origin, str):
            raise AudioRouteError("AUDIO_ROUTE_INVALID")
        if media_origin in {"opaque_ui", "opaque_tail"}:
            policy = opaque_policies.get(region_id)
            if policy is None and output_language:
                raise AudioRouteError("AUDIO_LAYER_POLICY_REQUIRED")
            policy = policy or "opaque_audio_keep"
            if policy not in OPAQUE_AUDIO_POLICIES:
                raise AudioRouteError("AUDIO_LAYER_POLICY_INVALID")
            if output_language and policy == "opaque_audio_keep":
                raise AudioRouteError("AUDIO_LAYER_POLICY_REQUIRED")
            routed_regions.append(
                {
                    "region_id": region_id,
                    "policy": policy,
                    "audio_owner": _opaque_audio_owner(policy),
                }
            )
            continue
        routed_regions.append(
            {
                "region_id": region_id,
                "policy": "generated_target_audio" if media_origin == "generated" else "source_audio_keep",
                "audio_owner": "generated_target_audio" if media_origin == "generated" else "source_audio_keep",
            }
        )
    return {
        "mode": "composite_localization" if output_language else "source_audio_preserve",
        "audio_reference": "Audio1" if output_language else None,
        "full_video_lip_sync": False,
        "regions": routed_regions,
    }


def build_background_music_route(
    *,
    source_music_timeline: Mapping[str, object],
    uploaded_audio: Mapping[str, object],
    visible_singer_regions: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    sha256 = uploaded_audio.get("sha256")
    duration_ms = uploaded_audio.get("duration_ms")
    start_offset_ms = uploaded_audio.get("start_offset_ms", 0)
    if not _sha256(sha256) or not isinstance(duration_ms, int) or duration_ms <= 0:
        raise AudioRouteError("BACKGROUND_MUSIC_INPUT_INVALID")
    if not isinstance(start_offset_ms, int) or start_offset_ms < 0:
        raise AudioRouteError("BACKGROUND_MUSIC_INPUT_INVALID")
    raw_windows = source_music_timeline.get("windows")
    if not isinstance(raw_windows, list) or not raw_windows:
        raise AudioRouteError("MUSIC_TIMELINE_CONTRACT_REQUIRED")
    cursor_ms = start_offset_ms
    previous_source_end = -1
    windows: list[dict[str, object]] = []
    for raw_window in raw_windows:
        if not isinstance(raw_window, Mapping):
            raise AudioRouteError("MUSIC_TIMELINE_CONTRACT_INVALID")
        source_start = raw_window.get("source_start_frame")
        source_end = raw_window.get("source_end_frame")
        output_start = raw_window.get("output_start_frame")
        output_end = raw_window.get("output_end_frame")
        window_duration = raw_window.get("duration_ms")
        if not all(isinstance(value, int) for value in (source_start, source_end, output_start, output_end, window_duration)):
            raise AudioRouteError("MUSIC_TIMELINE_CONTRACT_INVALID")
        if (
            source_start < 0
            or source_end <= source_start
            or source_start < previous_source_end
            or window_duration <= 0
        ):
            raise AudioRouteError("MUSIC_TIMELINE_CONTRACT_INVALID")
        if source_start != output_start or source_end != output_end:
            raise AudioRouteError("BACKGROUND_MUSIC_TIMELINE_MISMATCH")
        next_cursor = cursor_ms + window_duration
        if next_cursor > duration_ms:
            raise AudioRouteError("BACKGROUND_MUSIC_DURATION_INSUFFICIENT")
        windows.append(
            {
                "source_start_frame": source_start,
                "source_end_frame": source_end,
                "output_start_frame": output_start,
                "output_end_frame": output_end,
                "uploaded_start_ms": cursor_ms,
                "uploaded_end_ms": next_cursor,
                "continuity": "continue_uploaded_audio_after_source_pause",
            }
        )
        cursor_ms = next_cursor
        previous_source_end = source_end
    singing_qa = _singing_qa(visible_singer_regions)
    return {
        "schema_version": 1,
        "provider_route": "seedance_audio_reference",
        "provider_asset_type": "Audio",
        "provider_content_type": "audio_url",
        "provider_content_role": "reference_audio",
        "prompt_reference_tag": "@Audio1",
        "forbidden_provider_field": "reference_audios",
        "uploaded_audio_sha256": sha256,
        "final_audio_source": "uploaded_exact_audio",
        "allow_loop_or_time_stretch": False,
        "windows": windows,
        "singing_qa": singing_qa,
    }


def validate_background_music_delivery(
    *,
    route: Mapping[str, object],
    final_audio_sha256: str,
    mix_receipt: Mapping[str, object] | None,
) -> None:
    if not isinstance(mix_receipt, Mapping) or mix_receipt.get("passed") is not True:
        raise AudioRouteError("BACKGROUND_MUSIC_MIX_RECEIPT_REQUIRED")
    if not _sha256(final_audio_sha256):
        raise AudioRouteError("BACKGROUND_MUSIC_FINAL_AUDIO_UNVERIFIED")
    if mix_receipt.get("final_audio_sha256") != final_audio_sha256:
        raise AudioRouteError("BACKGROUND_MUSIC_FINAL_AUDIO_UNVERIFIED")
    if mix_receipt.get("uploaded_audio_sha256") != route.get("uploaded_audio_sha256"):
        raise AudioRouteError("BACKGROUND_MUSIC_FINAL_AUDIO_UNVERIFIED")
    expected_windows = route.get("windows")
    observed_windows = mix_receipt.get("window_receipts")
    if not isinstance(expected_windows, list) or not isinstance(observed_windows, list) or len(expected_windows) != len(observed_windows):
        raise AudioRouteError("BACKGROUND_MUSIC_FRAGMENT_RECEIPT_REQUIRED")
    for expected, observed in zip(expected_windows, observed_windows):
        if not isinstance(expected, Mapping) or not isinstance(observed, Mapping):
            raise AudioRouteError("BACKGROUND_MUSIC_FRAGMENT_RECEIPT_REQUIRED")
        for field in (
            "source_start_frame",
            "source_end_frame",
            "output_start_frame",
            "output_end_frame",
            "uploaded_start_ms",
            "uploaded_end_ms",
        ):
            if observed.get(field) != expected.get(field):
                raise AudioRouteError("BACKGROUND_MUSIC_FRAGMENT_RECEIPT_REQUIRED")
        if not _sha256(observed.get("fragment_sha256")):
            raise AudioRouteError("BACKGROUND_MUSIC_FRAGMENT_RECEIPT_REQUIRED")
        if any(observed.get(flag) is not False for flag in ("looped", "time_stretched", "pitch_shifted", "generated_substitute")):
            raise AudioRouteError("BACKGROUND_MUSIC_TRANSFORM_FORBIDDEN")
    _validate_final_singing_receipts(route, mix_receipt)


def _opaque_audio_owner(policy: str) -> str:
    return {
        "opaque_audio_keep": "opaque_audio_keep",
        "opaque_audio_mute_with_localized_voiceover": "localized_voiceover_mix",
        "opaque_audio_target_verified": "opaque_audio_target_verified",
        "opaque_audio_deep_localize": "opaque_audio_deep_localize",
    }[policy]


def _singing_qa(regions: Sequence[Mapping[str, object]]) -> dict[str, object]:
    visible = [region for region in regions if region.get("visible") is True]
    if not visible:
        return {
            "status": "skipped",
            "reason": "no_visible_singing_person",
            "regions": [],
        }
    receipts: list[dict[str, object]] = []
    for region in visible:
        alignment = region.get("lyrics_phoneme_alignment")
        lip_sync = region.get("lip_sync_qa")
        if (
            not isinstance(alignment, Mapping)
            or alignment.get("passed") is not True
            or not _sha256(alignment.get("receipt_sha256"))
        ):
            raise AudioRouteError("SINGING_ALIGNMENT_REQUIRED")
        if (
            not isinstance(lip_sync, Mapping)
            or lip_sync.get("passed") is not True
            or not _sha256(lip_sync.get("receipt_sha256"))
        ):
            raise AudioRouteError("SINGING_LIP_SYNC_QA_REQUIRED")
        receipts.append(
            {
                "region_id": region.get("region_id"),
                "alignment_receipt_sha256": alignment["receipt_sha256"],
                "lip_sync_receipt_sha256": lip_sync["receipt_sha256"],
            }
        )
    return {"status": "required", "reason": None, "regions": receipts}


def _validate_final_singing_receipts(route: Mapping[str, object], mix_receipt: Mapping[str, object]) -> None:
    singing_qa = route.get("singing_qa")
    if not isinstance(singing_qa, Mapping) or singing_qa.get("status") != "required":
        return
    expected = singing_qa.get("regions")
    observed = mix_receipt.get("singing_receipts")
    if not isinstance(expected, list) or not isinstance(observed, list) or len(expected) != len(observed):
        raise AudioRouteError("SINGING_FINAL_RECEIPT_REQUIRED")
    for required, receipt in zip(expected, observed):
        if not isinstance(required, Mapping) or not isinstance(receipt, Mapping):
            raise AudioRouteError("SINGING_FINAL_RECEIPT_REQUIRED")
        for field in ("region_id", "alignment_receipt_sha256", "lip_sync_receipt_sha256"):
            if receipt.get(field) != required.get(field):
                raise AudioRouteError("SINGING_FINAL_RECEIPT_REQUIRED")


def _sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)
